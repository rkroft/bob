"""The opener pass: fetch whole threads whose first email the search cut off.

`search_threads` shows only the newest five messages of a thread. On a long
introduction thread the opening email -- the one that made the introduction --
is not among them, so detection credits whoever sent the oldest *visible*
message: a later replier. Seen for real in Cowork on 2026-09-18, twice in one
scan.

Gmail's thread id is the id of the thread's first message (checked 2026-09-18
against every multi-message thread in a Takeout export and a live
`search_threads` page), so a thread whose id is not among its messages' ids is
missing its opener. That costs nothing to check, which is what makes a
targeted fetch possible instead of a `get_thread` for every thread.

All people here are the repo's fixture cast.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import bob  # noqa: E402
from connector_source import (  # noqa: E402
    ConnectorSource, missing_opener, thread_from_json,
)
from intro_detect import detect  # noqa: E402

ME = "alice.tran@example.com"
DANA = "dana.okafor@example.com"      # makes the introduction
BEN = "ben.mercer@otherco.io"
KAI = "kai.rivera@example.com"


def _m(mid, frm, to, subject, date):
    return {"id": mid, "sender": frm, "toRecipients": list(to),
            "subject": subject, "date": date}


def _opener(tid="t1"):
    # The intro itself: Dana to Alice and Ben. Its id IS the thread id.
    return _m(tid, DANA, [ME, BEN], "Intro: Alice <> Ben",
              "2026-03-01T10:00:00Z")


def _replies(tid="t1", n=5):
    # Alice and Ben carry on without Dana. Later repliers, never the connector.
    out = []
    for i in range(n):
        frm, to = (ME, [BEN]) if i % 2 else (BEN, [ME])
        out.append(_m(f"{tid}r{i}", frm, to, "Re: Intro: Alice <> Ben",
                      f"2026-03-{2 + i:02d}T10:00:00Z"))
    return out


def _search_view(tid="t1"):
    """What search_threads returns: the newest five, opener cut off."""
    return {"id": tid, "messages": _replies(tid)}


def _full_view(tid="t1"):
    """What get_thread returns: every message."""
    return {"id": tid, "messages": [_opener(tid)] + _replies(tid)}


def _write(path, lines):
    path.write_text("".join(json.dumps(x) + "\n" for x in lines),
                    encoding="utf-8")
    return path


def _todo(capsys, *files, extra=()):
    capsys.readouterr()
    rc = bob.main(["scan-todo", "--connector", *map(str, files),
                   "--principal", ME, *extra])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


# --- the free check ---------------------------------------------------------

def test_a_thread_without_its_own_id_among_its_messages_is_missing_its_opener():
    assert missing_opener(thread_from_json(_search_view()))


def test_a_thread_holding_its_first_message_is_whole():
    assert not missing_opener(thread_from_json(_full_view()))


def test_a_thread_with_no_message_ids_is_never_called_truncated():
    """Unknown is not truncated -- guessing here would send the agent off to
    fetch threads for no reason."""
    t = thread_from_json({"id": "t1", "messages": [
        {"sender": DANA, "toRecipients": [ME, BEN], "subject": "Intro"}]})
    assert not missing_opener(t)


# --- the bug, and the fix ---------------------------------------------------

def test_the_search_view_credits_a_later_replier():
    """The failure this pass exists for, pinned so it stays understood."""
    d = detect(thread_from_json(_search_view()), ME)
    assert d.connector != DANA


def test_merging_the_fetched_thread_credits_the_real_introducer(tmp_path):
    f = _write(tmp_path / "threads.jsonl", [
        _search_view(), _full_view(), {"fetched": "t1", "status": "ok"}])
    [t] = ConnectorSource(ME, f).all_threads()
    d = detect(t, ME)
    assert d.is_intro and d.connector == DANA
    assert set(d.parties) == {ME, BEN}


# --- scan-todo: which threads to fetch --------------------------------------

def test_scan_todo_lists_a_truncated_intro(tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl", [_search_view()])
    out = _todo(capsys, f)
    assert out["batch"] == ["t1"]
    assert out["remaining"] == 1
    assert out["format"] == "MINIMAL"


def test_scan_todo_skips_a_whole_thread(tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl", [_full_view()])
    assert _todo(capsys, f)["batch"] == []


def test_scan_todo_skips_a_truncated_thread_with_no_intro_signal(tmp_path, capsys):
    """A long two-person thread about lunch is not worth a fetch."""
    chat = {"id": "t9", "messages": [
        _m(f"t9r{i}", ME if i % 2 else KAI, [KAI] if i % 2 else [ME],
           "Re: lunch thursday", f"2026-04-{1 + i:02d}T10:00:00Z")
        for i in range(5)]}
    f = _write(tmp_path / "threads.jsonl", [chat])
    assert _todo(capsys, f)["batch"] == []


def test_scan_todo_skips_automated_mail(tmp_path, capsys):
    blast = {"id": "t8", "messages": [
        _m(f"t8r{i}", "noreply@example.com", [ME], "Intro to our new pricing",
           f"2026-05-{1 + i:02d}T10:00:00Z") for i in range(5)]}
    f = _write(tmp_path / "threads.jsonl", [blast])
    assert _todo(capsys, f)["batch"] == []


def test_a_fetched_thread_is_not_listed_again(tmp_path, capsys):
    """Even when the opener is still missing afterwards -- a deleted first
    email stays deleted, and asking again would loop forever."""
    f = _write(tmp_path / "threads.jsonl", [
        _search_view(), {"fetched": "t1", "status": "ok"}])
    out = _todo(capsys, f)
    assert out["batch"] == [] and out["done"] == 1


def test_a_failed_fetch_is_retried_then_given_up(tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl", [
        _search_view(), {"fetched": "t1", "status": "blocked"}])
    assert _todo(capsys, f)["batch"] == ["t1"]
    _write(f, [_search_view(), {"fetched": "t1", "status": "blocked"},
               {"fetched": "t1", "status": "blocked"}])
    out = _todo(capsys, f)
    assert out["batch"] == [] and out["gave_up"] == ["t1"]


def test_fetch_markers_are_neither_threads_nor_skipped_lines(tmp_path):
    f = _write(tmp_path / "threads.jsonl", [
        _full_view(), {"fetched": "t1", "status": "ok"}])
    src = ConnectorSource(ME, f)
    assert src.threads_read == 1
    assert src.skipped_lines == 0


def test_scan_todo_batches(tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl",
               [_search_view(f"t{i}") for i in range(7)])
    out = _todo(capsys, f, extra=("--batch", "3"))
    assert len(out["batch"]) == 3 and out["remaining"] == 7


# --- scan: never pass a cut-off thread off as settled -----------------------

def _scan(tmp_path, f):
    return bob.main(["scan", "--connector", str(f), "--principal", ME,
                     "--out", str(tmp_path / "intros.csv"),
                     "--people", str(tmp_path / "people.csv")])


def test_scan_says_when_intros_rest_on_unfetched_openers(tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl", [_search_view()])
    assert _scan(tmp_path, f) == 0
    out = capsys.readouterr().out
    assert "first email" in out
    # The user sees this line and cannot run anything -- no command in it.
    assert "`" not in out.split("first email")[0].rsplit("⚠", 1)[-1]


def test_scan_is_quiet_about_openers_once_they_are_fetched(tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl", [
        _search_view(), _full_view(), {"fetched": "t1", "status": "ok"}])
    assert _scan(tmp_path, f) == 0
    assert "first email" not in capsys.readouterr().out


def test_a_separator_word_alone_is_not_worth_a_fetch(tmp_path, capsys):
    """"drinks and dinner" matches the name-separator pattern; it is not an
    intro, and every fetch costs the user tokens."""
    chat = {"id": "t7", "messages": [
        _m(f"t7r{i}", ME if i % 2 else KAI, [KAI] if i % 2 else [ME],
           "Re: drinks and dinner", f"2026-04-{1 + i:02d}T10:00:00Z")
        for i in range(5)]}
    f = _write(tmp_path / "threads.jsonl", [chat])
    assert _todo(capsys, f)["batch"] == []


def test_an_out_of_office_as_the_oldest_visible_reply_still_gets_fetched(
        tmp_path, capsys):
    view = _search_view()
    view["messages"][0] = _m("t1r0", BEN, [ME],
                             "Automatic reply: Intro: Alice <> Ben",
                             "2026-03-02T10:00:00Z")
    f = _write(tmp_path / "threads.jsonl", [view])
    assert _todo(capsys, f)["batch"] == ["t1"]


def test_data_dir_finds_the_scan_file(tmp_path, capsys):
    _write(tmp_path / "threads.jsonl", [_search_view()])
    capsys.readouterr()
    assert bob.main(["scan-todo", "--data-dir", str(tmp_path),
                     "--principal", ME]) == 0
    assert json.loads(capsys.readouterr().out)["batch"] == ["t1"]


def test_scan_warns_about_a_thread_given_up_on(tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl", [
        _search_view(), {"fetched": "t1", "status": "blocked"},
        {"fetched": "t1", "status": "blocked"}])
    assert _scan(tmp_path, f) == 0
    assert "could not be read back" in capsys.readouterr().out


def test_scan_warns_when_a_fetched_thread_still_lacks_its_opener(tmp_path, capsys):
    """Marked ok, but no whole copy in the file -- a deleted opener, or an
    append that never happened. The marker ends the loop; it does not make
    the row right."""
    f = _write(tmp_path / "threads.jsonl", [
        _search_view(), {"fetched": "t1", "status": "ok"}])
    assert _scan(tmp_path, f) == 0
    assert "could not be read back" in capsys.readouterr().out


# --- an ask that became an introduction, cut off by the search ---------------
# The 2026-09-21 Cowork miss, end to end. Dana asks Alice first, then adds Ben;
# the search shows only the five newest messages, all Alice and Ben, so neither
# the ask, the yes nor the handoff is visible. Fetching restores them, and
# detection then has to read the handoff from message 3, not message 1.

def _asked_full(tid="t5"):
    s = "Intro to Ben Mercer?"
    return {"id": tid, "messages": [
        _m(tid, DANA, [ME], s, "2024-09-03T20:00:00Z"),
        _m(f"{tid}a", ME, [DANA], f"Re: {s}", "2024-09-03T20:10:00Z"),
        _m(f"{tid}b", DANA, [ME, BEN], f"Re: {s}", "2024-09-03T20:30:00Z"),
    ] + [_m(f"{tid}r{i}", *((ME, [BEN]) if i % 2 else (BEN, [ME])), f"Re: {s}",
            f"2024-09-{4 + i:02d}T10:00:00Z") for i in range(5)]}


def _asked_search(tid="t5"):
    full = _asked_full(tid)
    return {"id": tid, "messages": full["messages"][-5:]}


def test_a_cut_off_asked_first_intro_is_fetched_and_scanned_as_inbound(
        tmp_path, capsys):
    f = _write(tmp_path / "threads.jsonl", [_asked_search()])
    assert _todo(capsys, f)["batch"] == ["t5"]

    _write(f, [_asked_search(), _asked_full(), {"fetched": "t5", "status": "ok"}])
    assert _scan(tmp_path, f) == 0
    rows = (tmp_path / "intros.csv").read_text(encoding="utf-8")
    [row] = [l for l in rows.splitlines() if l.startswith("t5,")]
    # The principal stays in `introduced` on an inbound row, by design.
    assert f",inbound,{DANA},{ME};{BEN}," in row


def test_a_cut_off_thread_showing_a_handoff_is_fetched_before_it_is_judged(
        tmp_path, capsys):
    """On a cut-off thread, anyone from the missing messages looks newly added,
    so a visible handoff must be read whole before anyone is credited."""
    view = {"id": "t6", "messages": [
        _m("t6a", BEN, [ME], "Re: next week", "2026-03-02T10:00:00Z"),
        _m("t6b", BEN, [ME, KAI], "Re: next week", "2026-03-03T10:00:00Z"),
        _m("t6c", KAI, [ME], "Re: next week", "2026-03-04T10:00:00Z"),
        _m("t6d", ME, [KAI], "Re: next week", "2026-03-05T10:00:00Z"),
        _m("t6e", KAI, [ME], "Re: next week", "2026-03-06T10:00:00Z"),
    ]}
    f = _write(tmp_path / "threads.jsonl", [view])
    assert _todo(capsys, f)["batch"] == ["t6"]


def test_a_cut_off_thread_scoring_as_an_intro_on_its_snippet_is_fetched(
        tmp_path, capsys):
    """The snippet can make a cut-off reply look like the intro, crediting the
    replier. Fetch it before anyone is credited. Found in review, 2026-09-21."""
    m = _m("t4r", BEN, [ME, KAI], "Re: Burma trip", "2026-03-04T10:00:00Z")
    m["snippet"] = "Alice, you should meet Kai. I'd like to introduce you two."
    rest = [_m(f"t4r{i}", KAI if i % 2 else ME, [ME] if i % 2 else [KAI],
               "Re: Burma trip", f"2026-03-{5 + i:02d}T10:00:00Z") for i in range(4)]
    f = _write(tmp_path / "threads.jsonl", [{"id": "t4", "messages": [m] + rest}])
    assert _todo(capsys, f)["batch"] == ["t4"]


# --- a thread the principal started ------------------------------------------
# Measured 2026-09-21 on a real scan: 76 of 209 opener fetches were threads the
# principal started. Gmail gives such a thread the id of the DRAFT it began as,
# and drafts are never returned, so the id is missing from its own messages
# even when every message is there. Search cuts a thread to exactly five, so
# fewer than five shown means the thread is whole.

def test_a_short_thread_whose_id_is_a_draft_is_whole():
    t = thread_from_json({"id": "d1", "messages": [
        _m("d1a", ME, [KAI], "Hello", "2026-02-09T18:19:27Z"),
        _m("d1b", KAI, [ME], "Re: Hello", "2026-02-09T20:29:27Z")]})
    assert not missing_opener(t)


def test_a_long_thread_fetched_whole_is_whole_even_without_its_id():
    msgs = [_m(f"d2{i}", ME if i % 2 else BEN, [BEN] if i % 2 else [ME],
               "Intro: Alice <> Ben", f"2026-03-{1 + i:02d}T10:00:00Z")
            for i in range(8)]
    assert not missing_opener(thread_from_json({"id": "d2", "messages": msgs}))


def test_scan_does_not_warn_about_a_short_thread_it_never_needed_to_fetch(
        tmp_path, capsys):
    view = {"id": "d3", "messages": [
        _m("d3a", DANA, [ME, BEN], "Intro: Alice <> Ben", "2026-03-01T10:00:00Z"),
        _m("d3b", BEN, [ME], "Re: Intro: Alice <> Ben", "2026-03-02T10:00:00Z")]}
    f = _write(tmp_path / "threads.jsonl", [view])
    assert _todo(capsys, f)["batch"] == []
    assert _scan(tmp_path, f) == 0
    assert "first email" not in capsys.readouterr().out



def test_a_fetched_long_thread_still_missing_its_first_email_is_disclosed(
        tmp_path, capsys):
    """Fetched whole, eight messages, and the first one deleted: that is the
    case the disclosure exists for. Found in review, 2026-09-21."""
    # The oldest message left is Ben's reply: Dana's opener is the one gone.
    whole = [_m(f"t9r{i}", ME if i % 2 else BEN, [BEN] if i % 2 else [ME],
                "Re: Intro: Alice <> Ben", f"2026-03-{2 + i:02d}T10:00:00Z")
             for i in range(8)]
    f = _write(tmp_path / "threads.jsonl", [
        {"id": "t9", "messages": whole[-5:]}, {"id": "t9", "messages": whole},
        {"fetched": "t9", "status": "ok"}])
    assert _scan(tmp_path, f) == 0
    assert "could not be read back" in capsys.readouterr().out


def test_a_fetched_thread_the_principal_started_is_not_disclosed(tmp_path, capsys):
    """Her own threads carry the id of the draft they began as, so a whole
    fetched copy still lacks the thread id. The oldest message held is hers:
    nothing is missing. 10 of 10 such warnings were false on a real scan
    (gate review, 2026-09-21)."""
    whole = [_m(f"u{i}", ME if i % 2 == 0 else BEN, [BEN] if i % 2 == 0 else [ME],
                "Intro: Alice <> Ben", f"2026-03-{2 + i:02d}T10:00:00Z")
             for i in range(8)]
    f = _write(tmp_path / "threads.jsonl", [
        {"id": "u", "messages": whole[-5:]}, {"id": "u", "messages": whole},
        {"fetched": "u", "status": "ok"}])
    assert _scan(tmp_path, f) == 0
    assert "could not be read back" not in capsys.readouterr().out


def test_a_deleted_opener_under_the_principals_reply_is_still_disclosed(
        tmp_path, capsys):
    """Her oldest surviving message is a reply ("Re:"), so something came
    before it: not a thread she started."""
    whole = [_m(f"v{i}", ME if i % 2 == 0 else BEN, [BEN] if i % 2 == 0 else [ME],
                "Re: Intro: Alice <> Ben", f"2026-03-{2 + i:02d}T10:00:00Z")
             for i in range(8)]
    f = _write(tmp_path / "threads.jsonl", [
        {"id": "v", "messages": whole[-5:]}, {"id": "v", "messages": whole},
        {"fetched": "v", "status": "ok"}])
    assert _scan(tmp_path, f) == 0
    assert "could not be read back" in capsys.readouterr().out
