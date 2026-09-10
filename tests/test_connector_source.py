"""ConnectorSource tests.

All people here are invented placeholders (repo rule — never real contacts).

The fixtures are shaped exactly as `search_threads(view=THREAD_VIEW_MINIMAL)`
returns a thread, because that shape is the contract: the agent appends the API's
own objects to a file without reformatting, and any transformation here would
test a shape nothing produces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from connector_source import (  # noqa: E402
    ConnectorSource, load, read_jsonl, thread_from_json,
)

CONNECTOR = "dana.okafor@example.com"
ALICE = "alice.tran@examplecorp.com"
BEN = "ben.mercer@otherco.io"
PRINCIPAL = ALICE


def _msg(mid, frm, to, subject, date="2026-03-04T17:00:00Z", cc=None, bcc=None):
    m = {"id": mid, "sender": frm, "toRecipients": list(to),
         "subject": subject, "date": date}
    if cc:
        m["ccRecipients"] = list(cc)
    if bcc:
        m["bccRecipients"] = list(bcc)
    return m


def _thread(tid, messages):
    return {"id": tid, "messages": messages}


def _write(tmp_path, name, threads):
    p = tmp_path / name
    p.write_text("".join(json.dumps(t) + "\n" for t in threads), encoding="utf-8")
    return p


# --- mapping ---------------------------------------------------------------

def test_maps_the_fields_detection_reads():
    t = thread_from_json(_thread("t1", [
        _msg("m1", CONNECTOR, [ALICE, BEN], "Intro: Alice <> Ben"),
    ]))
    m = t.messages[0]
    assert t.id == "t1"
    assert m.from_addr == CONNECTOR
    assert m.to_addrs == [ALICE, BEN]
    assert m.subject == "Intro: Alice <> Ben"
    assert m.date is not None


def test_body_is_none_because_this_path_has_no_bodies():
    """Metadata mode is the shipping mode, not a degraded one.

    `None` rather than `""` matters: `Message.body_text` is documented as None in
    metadata mode, and `_first_body` treats a falsy body the same either way, but
    an empty string would read as "the body was empty" to anyone debugging.
    """
    t = thread_from_json(_thread("t1", [_msg("m1", CONNECTOR, [ALICE], "hi")]))
    assert t.messages[0].body_text is None


def test_missing_recipient_lists_become_empty_not_none():
    """A one-to-nobody message is common in sent mail and must not crash."""
    t = thread_from_json(_thread("t1", [
        {"id": "m1", "sender": CONNECTOR, "subject": "x", "date": "2026-03-04T17:00:00Z"},
    ]))
    assert t.messages[0].to_addrs == []
    assert t.messages[0].cc_addrs == []


def test_bcc_is_dropped_rather_than_folded_into_cc():
    """Folding BCC into CC would invent a participant.

    The principal BCCing themselves on their own sent mail is ordinary, and
    counting that as a third party would turn a two-party thread into a
    three-body one — manufacturing exactly the shape detection looks for.
    """
    t = thread_from_json(_thread("t1", [
        _msg("m1", ALICE, [BEN], "note", bcc=[ALICE]),
    ]))
    assert t.messages[0].cc_addrs == []
    assert t.messages[0].to_addrs == [BEN]


def test_names_are_absent_because_the_connector_sends_bare_addresses():
    """Documents a real gap, so a later fix has a failing expectation to flip.

    `search_threads` returns a bare address, never `"Name <addr>"`, so
    `best_name` has no candidates and the graph renders local-parts (HAP-295).

    Names stay positionally paired with addresses (`_pair`), so a recipient
    yields an empty name rather than no entry — the alignment is preserved, and
    what is missing is the name itself.
    """
    t = thread_from_json(_thread("t1", [_msg("m1", CONNECTOR, [ALICE, BEN], "x")]))
    m = t.messages[0]
    assert m.from_name == ""
    assert m.to_names == ["", ""]
    assert len(m.to_names) == len(m.to_addrs)


def test_unparseable_date_becomes_none_and_sorts_last():
    """An undated message must not be silently reordered to the front.

    `Thread` sorts undated messages last and keeps their relative order, so the
    opener detection reasons about stays the real opener.
    """
    t = thread_from_json(_thread("t1", [
        _msg("m1", CONNECTOR, [ALICE], "first", date="not-a-date"),
        _msg("m2", ALICE, [CONNECTOR], "second", date="2026-03-04T17:00:00Z"),
    ]))
    assert t.messages[0].id == "m2"
    assert t.messages[1].date is None


# --- reading ---------------------------------------------------------------

def test_malformed_line_is_skipped_not_fatal(tmp_path):
    """One truncated line — an interrupted page — must not cost the file."""
    p = tmp_path / "scan.jsonl"
    good = json.dumps(_thread("t1", [_msg("m1", CONNECTOR, [ALICE], "x")]))
    p.write_text(good + "\n{ broken\n\n" + good.replace("t1", "t2") + "\n",
                 encoding="utf-8")
    assert [o["id"] for o in read_jsonl(p)] == ["t1", "t2"]


def test_load_dedupes_across_files(tmp_path):
    """The net runs fifteen overlapping queries; the same thread arrives often.

    Without this an introduction is counted once per query that found it.
    """
    t = _thread("shared", [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro")])
    a = _write(tmp_path, "q1.jsonl", [t])
    b = _write(tmp_path, "q2.jsonl", [t, _thread("only-b", [
        _msg("m2", BEN, [ALICE], "hello")])])
    assert sorted(x.id for x in load([a, b])) == ["only-b", "shared"]


def test_load_accepts_a_single_path(tmp_path):
    p = _write(tmp_path, "q.jsonl", [_thread("t1", [
        _msg("m1", CONNECTOR, [ALICE], "x")])])
    assert [t.id for t in load(p)] == ["t1"]


# --- the source ------------------------------------------------------------

def test_search_raises_because_retrieval_already_happened(tmp_path):
    """A caller that searches here has misunderstood the split.

    Returning an empty list would look like "no results" — a silent wrong
    answer, which is the failure this whole path is built to avoid.
    """
    p = _write(tmp_path, "q.jsonl", [_thread("t1", [
        _msg("m1", CONNECTOR, [ALICE], "x")])])
    src = ConnectorSource(PRINCIPAL, p)
    with pytest.raises(NotImplementedError):
        src.search("subject:intro")


def test_fetch_returns_known_ids_and_skips_unknown(tmp_path):
    p = _write(tmp_path, "q.jsonl", [_thread("t1", [
        _msg("m1", CONNECTOR, [ALICE], "x")])])
    src = ConnectorSource(PRINCIPAL, p)
    assert [t.id for t in src.fetch(["t1", "nope"])] == ["t1"]


def test_principal_and_all_threads(tmp_path):
    p = _write(tmp_path, "q.jsonl", [
        _thread("t1", [_msg("m1", CONNECTOR, [ALICE], "x")]),
        _thread("t2", [_msg("m2", BEN, [ALICE], "y")]),
    ])
    src = ConnectorSource(PRINCIPAL, p)
    assert src.principal() == PRINCIPAL
    assert sorted(t.id for t in src.all_threads()) == ["t1", "t2"]


# --- "I could not look" is not "there is nothing" (HAP-312, HAP-309) ---------
#
# granola-silence-is-not-evidence as a return type. Before this, an empty scan
# file produced `0 introductions` and exit 0 -- a finding -- and a missing one
# produced a bare FileNotFoundError traceback.

def test_a_missing_scan_file_is_refused_by_name(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        ConnectorSource(PRINCIPAL, tmp_path / "absent.jsonl")

    assert "absent.jsonl" in str(exc.value)


def test_an_empty_scan_file_is_blocked_not_zero(tmp_path):
    path = tmp_path / "threads.jsonl"
    path.write_text("")

    source = ConnectorSource(PRINCIPAL, path)

    assert source.blocked
    assert source.threads_read == 0


def test_a_file_of_only_malformed_lines_is_blocked(tmp_path):
    """Nothing parsed, so nothing was read. Reporting 0 introductions here
    would present a failed retrieval as an empty mailbox."""
    path = tmp_path / "threads.jsonl"
    path.write_text("{half a page\n{another\n")

    source = ConnectorSource(PRINCIPAL, path)

    assert source.blocked
    assert source.skipped_lines == 2


def test_one_good_thread_is_not_blocked(tmp_path):
    path = tmp_path / "threads.jsonl"
    path.write_text(json.dumps({
        "id": "t1",
        "messages": [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro: Alice <> Ben")],
    }) + "\n")

    source = ConnectorSource(PRINCIPAL, path)

    assert not source.blocked
    assert source.threads_read == 1


def test_skipped_lines_are_counted_alongside_good_ones(tmp_path):
    """`read_jsonl`'s docstring: "The count of skipped lines is the caller's to
    report; silence about them would be the failure this whole module is trying
    to avoid." Until now nothing counted them."""
    path = tmp_path / "threads.jsonl"
    path.write_text(json.dumps({
        "id": "t1",
        "messages": [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro")],
    }) + "\n{truncated\n")

    source = ConnectorSource(PRINCIPAL, path)

    assert source.threads_read == 1
    assert source.skipped_lines == 1
    assert not source.blocked


def test_a_thread_with_no_id_is_counted_as_skipped(tmp_path):
    """`load` drops it -- it cannot be de-duplicated -- and a silent drop is
    the thing this module's docstring warns about."""
    path = tmp_path / "threads.jsonl"
    path.write_text(json.dumps({"messages": []}) + "\n")

    source = ConnectorSource(PRINCIPAL, path)

    assert source.skipped_lines == 1
    assert source.blocked


def test_blank_lines_are_not_counted_as_skipped(tmp_path):
    """A trailing newline is not a lost page."""
    path = tmp_path / "threads.jsonl"
    path.write_text(json.dumps({
        "id": "t1",
        "messages": [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro")],
    }) + "\n\n\n")

    assert ConnectorSource(PRINCIPAL, path).skipped_lines == 0


def test_counts_accumulate_across_several_files(tmp_path):
    good = json.dumps({
        "id": "t1",
        "messages": [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro")],
    })
    (tmp_path / "a.jsonl").write_text(good + "\n{bad\n")
    (tmp_path / "b.jsonl").write_text(
        good.replace('"t1"', '"t2"') + "\n{bad\n")

    source = ConnectorSource(PRINCIPAL,
                             [tmp_path / "a.jsonl", tmp_path / "b.jsonl"])

    assert source.threads_read == 2
    assert source.skipped_lines == 2


def test_a_duplicate_thread_is_not_a_skipped_line(tmp_path):
    """The net runs overlapping queries, so the same thread arrives several
    times by design. De-duplication is not a loss."""
    good = json.dumps({
        "id": "t1",
        "messages": [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro")],
    })
    path = tmp_path / "threads.jsonl"
    path.write_text(good + "\n" + good + "\n")

    source = ConnectorSource(PRINCIPAL, path)

    assert source.threads_read == 1
    assert source.skipped_lines == 0


# --- one bad line must not cost the file: the three remaining crash paths -----

def test_a_valid_json_line_of_the_wrong_shape_is_counted_not_fatal(tmp_path):
    """`[1,2]` parses as JSON and then blows up in thread_from_json. A page
    half-written can just as easily be a half-written array as a broken
    brace."""
    path = tmp_path / "threads.jsonl"
    path.write_text(json.dumps({
        "id": "t1",
        "messages": [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro")],
    }) + "\n[1,2]\n")

    source = ConnectorSource(PRINCIPAL, path)

    assert source.threads_read == 1
    assert source.skipped_lines == 1


def test_a_non_utf8_byte_is_counted_not_fatal(tmp_path):
    """UnicodeDecodeError is a ValueError and was killing the whole scan
    inside read_jsonl's own iteration."""
    path = tmp_path / "threads.jsonl"
    good = json.dumps({
        "id": "t1",
        "messages": [_msg("m1", CONNECTOR, [ALICE, BEN], "Intro")],
    })
    path.write_bytes(good.encode() + b"\n" + b'{"id": "t2", \xff\xfe}\n')

    source = ConnectorSource(PRINCIPAL, path)

    assert source.threads_read == 1
    assert source.skipped_lines == 1
