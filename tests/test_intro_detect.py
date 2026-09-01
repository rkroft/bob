"""Detector tests.

All people here are invented placeholders (repo rule — never real contacts).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from intro_detect import CONFIDENT_THRESHOLD, detect, search_queries  # noqa: E402
from mail_source import Message, Thread  # noqa: E402

CONNECTOR = "dana.okafor@example.com"
ALICE = "alice.tran@examplecorp.com"
BEN = "ben.mercer@otherco.io"
CARA = "cara.silva@thirdco.com"
PRINCIPAL = ALICE


def msg(i, frm, to, subject, body=None, day=1, **kw):
    return Message(
        id=f"m{i}", from_addr=frm, to_addrs=to, subject=subject,
        body_text=body, date=datetime(2026, 3, day), **kw,
    )


def test_classic_double_opt_in_is_detected():
    """Connector opens with both parties, then drops off the reply."""
    t = Thread(id="t1", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Alice <> Ben",
            "Alice, wanted to introduce you to Ben — you two should connect.", day=1),
        msg(2, ALICE, [BEN], "Re: Alice <> Ben",
            "Thanks Dana, moving you to bcc. Ben, great to meet you.", day=2),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert d.is_confident
    assert "structural_dropout" in d.signals
    assert "subject_arrow" in d.signals
    assert d.connector == CONNECTOR
    assert set(d.parties) == {ALICE, BEN}
    assert d.principal_role == "party"


def test_principal_is_the_connector():
    """Principal introduces two *other* people and then steps back."""
    t = Thread(id="t2", messages=[
        msg(1, PRINCIPAL, [CONNECTOR, BEN], "intro: Dana / Ben",
            "Putting you in touch — I think you two should meet.", day=1),
        msg(2, CONNECTOR, [BEN], "Re: intro", "moving Alice to bcc, thanks!", day=2),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert d.connector == PRINCIPAL
    assert set(d.parties) == {CONNECTOR, BEN}
    assert d.principal_role == "connector"


def test_structural_signal_fires_without_any_intro_language():
    """The point of the structural signal: no keywords anywhere, still an intro."""
    t = Thread(id="t3", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "you two", "See below.", day=1),
        msg(2, ALICE, [BEN], "Re: you two", "Hi Ben — free Thursday?", day=2),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert set(d.signals) == {"structural_dropout", "three_party_open"}
    assert d.kind == "handoff"


def test_metadata_mode_ignores_bodies():
    """Body-only signals must not fire when bodies aren't available."""
    t = Thread(id="t4", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Quick note",
            "wanted to introduce you to Ben, moving you to bcc", day=1),
    ])
    full = detect(t, principal=PRINCIPAL, mode="full")
    meta = detect(t, principal=PRINCIPAL, mode="metadata")

    assert "body_handoff" in full.signals and "bcc_handoff" in full.signals
    assert "body_handoff" not in meta.signals and "bcc_handoff" not in meta.signals
    assert meta.confidence < full.confidence


def test_one_to_one_thread_is_not_an_intro():
    """Two-party threads are allowed now, but only in the request/forward
    shapes. Generic handoff language about a *thing* must still be rejected."""
    t = Thread(id="t5", messages=[
        msg(1, CONNECTOR, [ALICE], "intro",
            "wanted to introduce you to a book I'm reading", day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert not d.is_intro
    assert d.disqualified_by == "weak_two_party"


def test_two_party_thread_with_unambiguous_subject_is_admitted():
    """The mirror of the test above, and a real miss from run two.

    'Nadia/Alice intro' scored 0.00 because shape was gating scoring. Two
    names plus the word is near-unambiguous, so it gets in without the
    three-party structure.
    """
    t = Thread(id="t16", messages=[
        msg(1, CONNECTOR, [ALICE], "Nadia/Alice intro", "See below.", day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert "subject_pair_intro" in d.signals


# --- two-party shapes, added after the first scoring run ------------------
# The "3+ participants" precondition disqualified 27 of 100 hand-labeled
# threads before scoring. These are the two real shapes it was throwing away.

def test_intro_request_is_detected_and_flips_the_seat():
    """'Intro to Nadia Okonjo?' — the principal ASKING for an introduction.

    Two participants, and the third party is named in prose with no address on
    the thread at all. No participant count can ever surface this.
    """
    t = Thread(id="t11", messages=[
        msg(1, PRINCIPAL, [CONNECTOR], "Intro to Nadia Okonjo?",
            "Any chance you could introduce me to Beth? Would love an intro.", day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert d.kind == "request"
    assert d.principal_role == "requester"
    assert d.connector == CONNECTOR       # the person being asked
    assert "request_subject" in d.signals


def test_inbound_request_makes_the_principal_the_connector():
    """Someone asking the principal to make an intro."""
    t = Thread(id="t12", messages=[
        msg(1, CONNECTOR, [PRINCIPAL], "Intro to Ben Mercer?",
            "Would you be open to introducing me to Ben?", day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert d.kind == "request"
    assert d.principal_role == "connector"


def test_forwarded_intro_recovers_participants_from_quoted_headers():
    """'Fwd: Nadia to Alice' — two-party on the surface, three-party inside."""
    body = (
        "See below — great person.\n\n"
        "---------- Forwarded message ---------\n"
        f"From: Dana Okafor <{CONNECTOR}>\n"
        f"To: {ALICE}, {BEN}\n"
        "Subject: you two\n\n"
        "You should meet."
    )
    t = Thread(id="t13", messages=[
        msg(1, BEN, [ALICE], "Fwd: Ben to Alice", body, day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert d.kind == "forward"
    assert "forward_recovered" in d.signals


def test_forward_recovery_is_off_in_metadata_mode():
    """Quoted headers live in the body — unavailable without body scope."""
    body = (
        "---------- Forwarded message ---------\n"
        f"From: <{CONNECTOR}>\nTo: {ALICE}, {BEN}\n\n"
        "wanted to introduce you to Ben"
    )
    t = Thread(id="t14", messages=[msg(1, BEN, [ALICE], "Fwd: intro", body, day=1)])

    assert detect(t, principal=PRINCIPAL, mode="full").is_intro
    assert not detect(t, principal=PRINCIPAL, mode="metadata").is_intro


def test_bare_intro_subject_clears_the_threshold():
    """A real miss from the first run: 4 people, subject literally 'Intro',
    scored 0.30 and fell below the bar."""
    t = Thread(id="t15", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Intro", "See below.", day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.is_intro
    assert "subject_intro_only" in d.signals


@pytest.mark.parametrize("frm,subject,kw,expected", [
    ("no-reply@newsletter.example.com", "Introducing our new product", {}, "automated_sender"),
    (CONNECTOR, "Invitation: Coffee @ Thu Mar 5", {}, "automated_subject"),
    (CONNECTOR, "Alice <> Ben", {"is_calendar_invite": True}, "calendar_invite"),
    (CONNECTOR, "Introducing the spring lineup", {"is_bulk": True}, "bulk_mail"),
])
def test_hard_negatives(frm, subject, kw, expected):
    t = Thread(id="t6", messages=[
        msg(1, frm, [ALICE, BEN], subject, "introduce you to something", day=1, **kw),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert not d.is_intro
    assert d.disqualified_by == expected


def test_large_group_thread_is_rejected():
    many = [f"person{i}@example.com" for i in range(8)]
    t = Thread(id="t7", messages=[
        msg(1, CONNECTOR, many, "Introducing the team", "connecting you all", day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert not d.is_intro
    assert d.disqualified_by == "group_thread"


def test_messages_are_sorted_chronologically():
    """Structural detection depends on knowing which message came first."""
    t = Thread(id="t8", messages=[
        msg(2, ALICE, [BEN], "Re: hello", "thanks!", day=9),
        msg(1, CONNECTOR, [ALICE, BEN], "hello", "meet each other", day=2),
    ])
    assert [m.id for m in t.messages] == ["m1", "m2"]
    assert detect(t, principal=PRINCIPAL).is_intro


def test_addresses_are_normalized():
    t = Thread(id="t9", messages=[
        msg(1, "Dana Okafor <Dana.Okafor@Example.COM>", [f"Alice <{ALICE.upper()}>", BEN],
            "Alice <> Ben", "introduce you to Ben", day=1),
        msg(2, ALICE, [BEN], "Re:", "moving you to bcc", day=2),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.connector == CONNECTOR
    assert d.principal_role == "party"


def test_weak_thread_is_detected_but_not_confident():
    """Onboarding shows only confident detections — this one shouldn't surface."""
    t = Thread(id="t10", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Alice / Ben catchup", "See notes.", day=1),
    ])
    d = detect(t, principal=PRINCIPAL)

    assert d.confidence < CONFIDENT_THRESHOLD
    assert not d.is_confident


# --------------------------------------------------------------------------
# Findings from the reference mailbox, 2026-08-20.
#
# The first run against a mailbox the detector was not tuned on. It contained
# no real introductions at all, and still produced one confident detection and
# one marginal one. Both failure classes are recorded here as tests.
# --------------------------------------------------------------------------


def test_self_pitch_is_not_an_introduction():
    """"Introduction to <the sender's own company>" is a cold pitch.

    Scored 0.80 in the reference run — above the display bar, so it would
    have been the headline of a first run. For an investor's mailbox this subject line is
    one of the most common there is.
    """
    t = Thread(id="t", messages=[msg(
        1, "kai@fourthco.dev", [PRINCIPAL],
        "Introduction to Fourthco AI",
        "Hi Alice, I'm a co-founder of Fourthco and we exist because "
        "scheduling is broken. I'd love to share what we're building. Let me "
        "know if it makes sense to find a time for an introduction.",
    )])
    d = detect(t, principal=PRINCIPAL)
    assert not d.is_intro, f"scored {d.confidence:.2f} via {d.signals}"


def test_request_subject_does_not_restack_the_same_words():
    """One subject line must not score three times.

    "Introduction to X" fired request_subject (0.45) + subject_keyword (0.20)
    + subject_separator (0.15) — three signals re-reading the same six words.
    """
    t = Thread(id="t", messages=[msg(
        1, "someone@unrelated-domain.test", [PRINCIPAL],
        "Introduction to Acme Robotics", "Have a look at what we do.",
    )])
    d = detect(t, principal=PRINCIPAL)
    assert d.confidence < CONFIDENT_THRESHOLD, (
        f"a bare request subject must not clear the display bar; "
        f"got {d.confidence:.2f} via {d.signals}"
    )


def test_meeting_recap_bot_is_not_an_introduction():
    """"A <> B" is meeting-title syntax in any mailbox with a scheduling tool.

    Six of twelve reference-run rejects were calendar artifacts using the
    arrow. This one — a Fireflies recap — still reached 0.50.
    """
    t = Thread(id="t", messages=[msg(
        1, "notifications@fireflies.ai", [CARA, PRINCIPAL],
        "Your meeting recap - Alice Tran <> Cara Silva",
        "Here are the notes from your meeting.",
    )])
    d = detect(t, principal=PRINCIPAL)
    assert not d.is_intro, f"scored {d.confidence:.2f} via {d.signals}"


def test_genuine_inbound_intro_request_still_detected():
    """Regression guard: someone asking Rachel for an intro to a real person
    must survive the self-pitch and double-count fixes."""
    t = Thread(id="t", messages=[msg(
        1, "ben.mercer@otherco.io", [PRINCIPAL],
        "Intro to Nadia Okonjo?",
        "Any chance you could introduce me to Nadia? Would love to talk to her "
        "about the fund.",
    )])
    d = detect(t, principal=PRINCIPAL)
    assert d.is_intro, f"scored {d.confidence:.2f} via {d.signals}"


def test_classic_handoff_unaffected():
    """Regression guard: the shape the whole product is about."""
    t = Thread(id="t", messages=[msg(
        1, CONNECTOR, [ALICE, BEN], "Intro: Alice <> Ben",
        "I'd like to introduce you two. Moving myself to bcc.",
    )])
    d = detect(t, principal=ALICE)
    assert d.is_intro and d.is_confident, f"scored {d.confidence:.2f} via {d.signals}"


def test_a_scheduling_notification_is_not_an_introduction():
    """Vimcal names a booked meeting with the same "A <> B" syntax Rachel uses
    for introductions, so a booking scored 1.00 and five of them reached her
    top-ten connector list. Someone using your booking link is not an
    introduction, and the tool that mailed you about it did not make one."""
    t = Thread(id="t", messages=[msg(
        1, "invite@vimcal.com", [PRINCIPAL],
        "Alice Tran <> Cara Silva (from alice@examplecorp.com)",
        "A new event was scheduled!",
    )])
    d = detect(t, principal=PRINCIPAL)
    assert not d.is_intro, f"scored {d.confidence:.2f} via {d.signals}"


def test_other_scheduling_tools_are_covered_too():
    for sender in ("notifications@calendly.com", "no-reply@savvycal.com",
                   "hello@cal.com", "meetings@hubspot.com"):
        t = Thread(id="t", messages=[msg(
            1, sender, [PRINCIPAL], "Alice <> Ben", "Event scheduled")])
        assert not detect(t, principal=PRINCIPAL).is_intro, sender


def test_a_real_intro_from_a_person_still_detects():
    """Guard: the scheduling rule must not swallow ordinary mail."""
    t = Thread(id="t", messages=[msg(
        1, CONNECTOR, [ALICE, BEN], "Intro: Alice <> Ben",
        "I'd like to introduce you two. Moving myself to bcc.")])
    assert detect(t, principal=ALICE).is_intro


def test_no_query_in_the_net_is_punctuation_only():
    """Gmail ignores punctuation in search, so `subject:"<>"` collapses to an
    empty subject match and returns the entire mailbox. It sat in the net
    inherited from the CRM, contributing nothing but bulk, and a 500-result cap
    disguised it as a popular query rather than a broken one. Uncapped it made
    a scan 325,000 threads and 32 hours instead of 4,200 and 25 minutes.

    The `A <> B` convention is still caught — by the DETECTOR's subject_arrow
    signal, on threads other queries surface. Retrieval and adjudication are
    different jobs and this is the seam between them.
    """
    import re
    for q in search_queries():
        terms = re.findall(r'"([^"]*)"', q) or [q.split(":", 1)[-1]]
        for t in terms:
            assert re.search(r"[A-Za-z0-9]", t), (
                f"query {q!r} has no searchable characters — Gmail will match "
                f"everything"
            )
