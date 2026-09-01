"""MboxSource tests.

All people here are invented placeholders (repo rule — never real contacts).
"""

from __future__ import annotations

import mailbox
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from mbox_source import MboxSource  # noqa: E402

CONNECTOR = "dana.okafor@example.com"
ALICE = "alice.tran@examplecorp.com"
BEN = "ben.mercer@otherco.io"
PRINCIPAL = ALICE


def _msg(
    frm, to, subject, body="", *, mid=None, thrid=None, refs=None,
    cc=None, day=1, headers=None, html=None,
):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = ", ".join(to)
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Subject"] = subject
    m["Date"] = f"Tue, {day:02d} Mar 2026 09:00:00 -0800"
    if mid:
        m["Message-ID"] = mid
    if thrid:
        m["X-GM-THRID"] = thrid
    if refs:
        m["References"] = " ".join(refs)
        m["In-Reply-To"] = refs[-1]
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content(body)
    if html is not None:
        m.add_alternative(html, subtype="html")
    return m


def _write(tmp_path, messages, name="All mail.mbox") -> Path:
    path = tmp_path / name
    box = mailbox.mbox(str(path), create=True)
    for m in messages:
        box.add(m)
    box.flush()
    box.close()
    return path


def _src(tmp_path, messages, **kw) -> MboxSource:
    return MboxSource(_write(tmp_path, messages), principal=PRINCIPAL, **kw)


# -- threading ------------------------------------------------------------


def test_groups_by_gmail_thread_id(tmp_path):
    src = _src(tmp_path, [
        _msg(CONNECTOR, [ALICE, BEN], "Intro: Alice <> Ben", "connecting you two", thrid="9001", day=1),
        _msg(BEN, [ALICE], "Re: Intro: Alice <> Ben", "great to meet you", thrid="9001", day=2),
        _msg(CONNECTOR, [ALICE], "Unrelated", "lunch?", thrid="9002", day=3),
    ])
    assert set(src.search("subject:intro")) == {"9001"}
    (thread,) = src.fetch(["9001"])
    assert len(thread.messages) == 2


def test_falls_back_to_references_when_no_gmail_header(tmp_path):
    src = _src(tmp_path, [
        _msg(CONNECTOR, [ALICE, BEN], "Intro", "like to introduce you", mid="<a@x>", day=1),
        _msg(BEN, [ALICE], "Re: Intro", "thanks!", mid="<b@x>", refs=["<a@x>"], day=2),
    ])
    ids = src.search("subject:intro")
    assert len(ids) == 1, "reply must join the original thread, not start a new one"
    (thread,) = src.fetch(ids)
    assert len(thread.messages) == 2


def test_messages_come_back_in_chronological_order(tmp_path):
    src = _src(tmp_path, [
        _msg(BEN, [ALICE], "Re: Intro", "second", thrid="7", day=9),
        _msg(CONNECTOR, [ALICE, BEN], "Intro", "introduce you to Ben", thrid="7", day=2),
    ])
    (thread,) = src.fetch(["7"])
    assert [m.body_text for m in thread.messages] == ["second", "introduce you to Ben"][::-1]


# -- the query dialect ----------------------------------------------------


def test_subject_scoped_query_ignores_body_matches(tmp_path):
    src = _src(tmp_path, [
        _msg(CONNECTOR, [ALICE], "Coffee", "an introduction is coming", thrid="1"),
        _msg(CONNECTOR, [ALICE], "Introduction", "hi", thrid="2"),
    ])
    assert set(src.search("subject:introduction")) == {"2"}


def test_quoted_phrase_matches_the_body(tmp_path):
    src = _src(tmp_path, [
        _msg(CONNECTOR, [ALICE, BEN], "Two people", "I'd like to introduce you to Ben.", thrid="1"),
        _msg(CONNECTOR, [ALICE], "Two people", "unrelated note", thrid="2"),
    ])
    assert set(src.search('"like to introduce"')) == {"1"}


def test_query_is_case_insensitive(tmp_path):
    src = _src(tmp_path, [_msg(CONNECTOR, [ALICE], "INTRO: Alice <> Ben", "Connecting You Two", thrid="1")])
    assert set(src.search("subject:intro")) == {"1"}
    assert set(src.search('"connecting you"')) == {"1"}


def test_angle_bracket_subject_query(tmp_path):
    src = _src(tmp_path, [
        _msg(CONNECTOR, [ALICE, BEN], "Alice <> Ben", "you two should talk", thrid="1"),
        _msg(CONNECTOR, [ALICE], "Alice and Ben", "you two should talk", thrid="2"),
    ])
    assert set(src.search('subject:"<>"')) == {"1"}


def test_prescan_matches_individual_searches(tmp_path):
    msgs = [
        _msg(CONNECTOR, [ALICE, BEN], "Intro: Alice <> Ben", "putting you in touch", thrid="1"),
        _msg(BEN, [ALICE], "Coffee", "nothing to see", thrid="2"),
    ]
    queries = ["subject:intro", '"putting you in touch"', '"moving you to bcc"']
    one_pass = _src(tmp_path, msgs, )
    one_pass.prescan(queries)
    per_query = _src(tmp_path, msgs)
    for q in queries:
        assert set(one_pass.search(q)) == set(per_query.search(q)), q


# -- message normalization ------------------------------------------------


def test_addresses_are_normalized_and_cc_captured(tmp_path):
    src = _src(tmp_path, [
        _msg("Dana Okafor <Dana.Okafor@EXAMPLE.com>", ["Alice Tran <ALICE.TRAN@examplecorp.com>"],
             "Intro", "hello", cc=["Ben Mercer <ben.mercer@OTHERCO.io>"], thrid="1"),
    ])
    (thread,) = src.fetch(["1"])
    msg = thread.messages[0]
    assert msg.from_addr == CONNECTOR
    assert msg.to_addrs == [ALICE]
    assert msg.cc_addrs == [BEN]


def test_include_bodies_false_omits_body(tmp_path):
    src = _src(tmp_path, [_msg(CONNECTOR, [ALICE], "Intro", "secret contents", thrid="1")])
    (thread,) = src.fetch(["1"], include_bodies=False)
    assert thread.messages[0].body_text is None
    assert thread.messages[0].subject == "Intro"


def test_prefers_plain_text_over_html_alternative(tmp_path):
    src = _src(tmp_path, [
        _msg(CONNECTOR, [ALICE], "Intro", "plain version", html="<p>html version</p>", thrid="1"),
    ])
    (thread,) = src.fetch(["1"])
    assert "plain version" in thread.messages[0].body_text
    assert "html version" not in thread.messages[0].body_text


def test_bulk_and_calendar_flags(tmp_path):
    src = _src(tmp_path, [
        _msg(CONNECTOR, [ALICE], "Newsletter", "we'd like to introduce our new feature",
             thrid="1", headers={"List-Unsubscribe": "<mailto:x@example.com>"}),
        _msg(CONNECTOR, [ALICE], "Plain", "hello", thrid="2"),
    ])
    (bulk,) = src.fetch(["1"])
    (plain,) = src.fetch(["2"])
    assert bulk.messages[0].is_bulk is True
    assert plain.messages[0].is_bulk is False


def test_malformed_date_does_not_lose_the_message(tmp_path):
    # Built as raw text: Python's header registry refuses to construct this.
    raw = (
        f"From: {CONNECTOR}\n"
        f"To: {ALICE}\n"
        "Subject: Intro\n"
        "Date: not a date\n"
        "X-GM-THRID: 1\n"
        "\n"
        "hello\n"
    )
    path = tmp_path / "All mail.mbox"
    box = mailbox.mbox(str(path), create=True)
    box.add(raw)
    box.flush()
    box.close()
    src = MboxSource(path, principal=PRINCIPAL)
    (thread,) = src.fetch(["1"])
    assert thread.messages[0].date is None
    assert thread.messages[0].subject == "Intro"


# -- construction ---------------------------------------------------------


def test_missing_file_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        MboxSource(tmp_path / "nope.mbox", principal=PRINCIPAL)


def test_directory_of_mbox_files_is_read_as_one_corpus(tmp_path):
    _write(tmp_path, [_msg(CONNECTOR, [ALICE], "Intro one", "like to introduce", thrid="1")], "a.mbox")
    _write(tmp_path, [_msg(CONNECTOR, [BEN], "Intro two", "like to introduce", thrid="2")], "b.mbox")
    src = MboxSource(tmp_path, principal=PRINCIPAL)
    assert set(src.search("subject:intro")) == {"1", "2"}
