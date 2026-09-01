"""What happened after the introduction. Invented placeholder people only.

The triage buckets in Plugin MVP §4.6 need to know whether the principal
replied, whether the other party did, and whether a meeting got scheduled.
All three are in the thread the scan already reads — they were just never kept.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from after import after_signal  # noqa: E402
from mail_source import Message, Thread  # noqa: E402

ME = "alice@examplecorp.com"
DANA = "dana@example.com"        # the introducer
BEN = "ben@otherco.io"           # the person introduced


def msg(frm, day, **kw):
    return Message(id=f"m{day}", from_addr=frm, to_addrs=[ME, DANA, BEN],
                   date=datetime(2026, 3, day), **kw)


def thread(*messages):
    return Thread(id="t1", messages=list(messages))


def test_the_intro_alone_is_not_a_reply():
    a = after_signal(thread(msg(DANA, 1)), ME)
    assert a.principal_replied is False
    assert a.other_replied is False
    assert a.first_reply == ""


def test_the_principal_replying_is_the_took_hold_signal():
    a = after_signal(thread(msg(DANA, 1), msg(ME, 2)), ME)
    assert a.principal_replied is True
    assert a.first_reply == "2026-03-02"


def test_the_other_party_replying_alone_is_not_the_principal_replying():
    """Ben answered; Alice never did. That is not the same thing, and §4.6's
    took-hold test is about the principal."""
    a = after_signal(thread(msg(DANA, 1), msg(BEN, 2)), ME)
    assert a.principal_replied is False
    assert a.other_replied is True


def test_the_span_runs_to_the_last_real_message():
    a = after_signal(thread(msg(DANA, 1), msg(ME, 2), msg(BEN, 9)), ME)
    assert a.last_exchange == "2026-03-09"


def test_a_calendar_invite_in_the_thread_means_they_met():
    """Free meeting evidence, without the Calendar connector — §4.6 says a
    meeting upgrades never-landed from a guess to a finding."""
    a = after_signal(
        thread(msg(DANA, 1), msg(BEN, 3, is_calendar_invite=True)), ME)
    assert a.meeting_invited is True


def test_a_bulk_message_is_not_an_exchange():
    """Replying to a newsletter is not contact, and a newsletter landing in the
    thread is not the introduction taking hold."""
    a = after_signal(thread(msg(DANA, 1), msg(BEN, 4, is_bulk=True)), ME)
    assert a.other_replied is False
    assert a.last_exchange == ""


def test_the_principals_own_bulk_mail_is_not_a_reply_either():
    a = after_signal(thread(msg(DANA, 1), msg(ME, 4, is_bulk=True)), ME)
    assert a.principal_replied is False


def test_nothing_before_the_intro_counts():
    """Only what happened AFTER the introduction is evidence about it."""
    a = after_signal(thread(msg(ME, 1), msg(DANA, 2)), ME, intro_index=1)
    assert a.principal_replied is False


def test_an_undated_message_does_not_invent_a_date():
    t = thread(msg(DANA, 1))
    t.messages.append(Message(id="x", from_addr=ME, to_addrs=[DANA], date=None))
    a = after_signal(t, ME)
    assert a.principal_replied is True     # it still happened
    assert a.first_reply == ""             # but we cannot say when


def test_the_principal_is_matched_case_insensitively():
    a = after_signal(thread(msg(DANA, 1), msg("Alice@ExampleCorp.com", 2)), ME)
    assert a.principal_replied is True


def test_it_keeps_no_message_count():
    """§4.6: evidence is events and spans, never tallies — a message count
    reads as surveillance wherever it appears. The count is not stored, so it
    cannot leak into copy."""
    a = after_signal(thread(msg(DANA, 1), msg(ME, 2), msg(ME, 3), msg(BEN, 4)), ME)
    assert not any("count" in f or "n_" in f for f in vars(a))
    assert not any(isinstance(v, int) and not isinstance(v, bool)
                   for v in vars(a).values())


# --------------------------------------------------------------------------
# The three buckets (§4.6). Two are actionable; the third means say nothing.
# --------------------------------------------------------------------------

from after import triage  # noqa: E402


def test_a_reply_from_the_principal_is_took_hold():
    assert triage(after_signal(thread(msg(DANA, 1), msg(ME, 2)), ME)) == "took_hold"


def test_a_meeting_is_took_hold_even_with_no_reply():
    """§4.6: a meeting is one of the three took-hold tests in its own right."""
    a = after_signal(thread(msg(DANA, 1), msg(BEN, 2, is_calendar_invite=True)), ME)
    assert triage(a) == "took_hold"


def test_silence_from_the_principal_is_never_landed():
    assert triage(after_signal(thread(msg(DANA, 1)), ME)) == "never_landed"


def test_the_other_party_writing_and_getting_no_answer_is_never_landed():
    """The warm intro going to waste — §4.6 calls this the more valuable
    bucket and the cheaper email to send."""
    a = after_signal(thread(msg(DANA, 1), msg(BEN, 2)), ME)
    assert triage(a) == "never_landed"


def test_no_evidence_at_all_is_cant_tell_not_never_landed():
    """A row from a scan that never captured after-signal must not be read as
    'you ignored them'. Bob sees one channel and cannot assert absence."""
    assert triage(None) == "cant_tell"


# --------------------------------------------------------------------------
# The stored row -> a bucket. `observed` is what keeps "we never looked" from
# reading as "you ignored them".
# --------------------------------------------------------------------------

from intro_store import IntroRow, after_of  # noqa: E402


def _row(**kw):
    base = dict(thread_id="t", date="2026-03-01", direction="inbound",
                introducer=DANA, introduced=(BEN,), subject="Intro",
                thread_link="", confidence=0.9)
    return IntroRow(**{**base, **kw})


def test_a_row_from_a_scan_that_never_looked_is_cant_tell():
    assert after_of(_row()) is None
    assert triage(after_of(_row())) == "cant_tell"


def test_a_scanned_row_with_no_reply_is_never_landed_not_cant_tell():
    """Same field values as the row above — only `observed` separates them,
    and it is the difference between drafting an email and staying quiet."""
    assert triage(after_of(_row(observed=True))) == "never_landed"


def test_a_scanned_row_that_took_hold_survives_the_round_trip(tmp_path):
    from intro_store import write_intros, read_intros
    p = tmp_path / "i.csv"
    write_intros([_row(observed=True, replied=True, met=True,
                       first_reply="2026-03-02", last_exchange="2026-03-09")], p)
    back = read_intros(p)[0]
    assert (back.observed, back.replied, back.met) == (True, True, True)
    assert back.first_reply == "2026-03-02"
    assert triage(after_of(back)) == "took_hold"
