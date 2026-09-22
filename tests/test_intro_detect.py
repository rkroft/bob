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


# --- the late handoff: an ask that became an introduction -----------------
# A double opt-in often opens as two people: "OK if I introduce you to Ben?"
# The third person is added two messages later, and the connector drops off
# after that. The only structural check read message 1, so the whole thread
# scored as a request and the scan dropped it. That was a real miss in a Cowork
# run on 2026-09-21, with the introducer's ask, the yes and the handoff all
# present in the thread.

KAI = "kai.rivera@example.com"


def _asked_then_added(asker, asked, subject="Intro to Ben Mercer?"):
    """asker asks asked; the connector adds Ben; Ben writes to Alice alone."""
    connector = CONNECTOR
    return Thread(id="t_late", messages=[
        msg(1, asker, [asked], subject,
            "Had a call with Ben today. OK for me to make an intro?", day=1),
        msg(2, asked, [asker], f"Re: {subject}", "Yes please!", day=1),
        msg(3, connector, [ALICE, BEN], f"Re: {subject}",
            "+Ben. Alice, meet Ben.", day=2),
        msg(4, BEN, [ALICE], f"Re: {subject}",
            "Thanks for the intro, Dana (off to BCC). Friday?", day=2),
    ])


def test_connector_asks_first_then_adds_the_third_person():
    """Dana asks Alice for permission, then introduces Ben: an introduction,
    credited to Dana, with Alice as a party."""
    d = detect(_asked_then_added(CONNECTOR, ALICE), principal=ALICE)

    assert d.is_intro
    assert d.is_confident
    assert d.kind == "handoff"
    assert "late_handoff" in d.signals
    assert d.connector == CONNECTOR
    assert set(d.parties) == {ALICE, BEN}
    assert d.principal_role == "party"


def test_principal_asks_and_the_connector_delivers():
    """Alice asks Dana for an intro to Ben and Dana makes it. The request
    became an introduction, so it is recorded as one."""
    d = detect(_asked_then_added(ALICE, CONNECTOR), principal=ALICE)

    assert d.is_intro
    assert d.kind == "handoff"
    assert d.connector == CONNECTOR
    assert set(d.parties) == {ALICE, BEN}
    assert d.principal_role == "party"


def test_principal_delivers_an_intro_someone_asked_for():
    """Ben asks Alice for an intro to Kai; Alice adds Kai and steps back."""
    t = Thread(id="t_out", messages=[
        msg(1, BEN, [ALICE], "Intro to Kai Rivera?",
            "Would you be open to introducing me to Kai?", day=1),
        msg(2, ALICE, [BEN, KAI], "Re: Intro to Kai Rivera?",
            "Of course. Kai, meet Ben.", day=2),
        msg(3, KAI, [BEN], "Re: Intro to Kai Rivera?",
            "Moving Alice to bcc. Ben, happy to chat.", day=3),
    ])
    d = detect(t, principal=ALICE)

    assert d.is_intro
    assert d.kind == "handoff"
    assert d.connector == ALICE
    assert set(d.parties) == {BEN, KAI}
    assert d.principal_role == "connector"


def test_looping_in_someone_who_never_takes_over_is_not_a_handoff():
    """Adding an assistant to schedule, while the person who added them stays
    on every later message, is not an introduction."""
    t = Thread(id="t_cc", messages=[
        msg(1, CONNECTOR, [ALICE], "Coffee next week?", "Free Tuesday?", day=1),
        msg(2, ALICE, [CONNECTOR, CARA], "Re: Coffee next week?",
            "Adding Cara, who runs my calendar.", day=1),
        msg(3, CARA, [ALICE, CONNECTOR], "Re: Coffee next week?",
            "Tuesday at 10 works.", day=2),
    ])
    d = detect(t, principal=ALICE)

    assert "late_handoff" not in d.signals
    assert not d.is_intro


def test_an_ask_that_went_nowhere_stays_a_request():
    """Nobody new ever joins: still a request, still dropped by the scan."""
    t = Thread(id="t_ask", messages=[
        msg(1, ALICE, [CONNECTOR], "Intro to Ben Mercer?",
            "Any chance you could introduce me to Ben?", day=1),
        msg(2, CONNECTOR, [ALICE], "Re: Intro to Ben Mercer?",
            "Let me check with him first.", day=2),
    ])
    d = detect(t, principal=ALICE)

    assert d.kind == "request"
    assert "late_handoff" not in d.signals


def test_a_later_group_reply_does_not_count_as_a_handoff():
    """A message that adds more people than an introduction has is a group
    thread growing, not someone being introduced."""
    crowd = [f"p{i}@thirdco.com" for i in range(6)]
    t = Thread(id="t_grp", messages=[
        msg(1, CONNECTOR, [ALICE], "Planning", "Thoughts?", day=1),
        msg(2, CONNECTOR, [ALICE, *crowd], "Re: Planning", "Adding everyone.", day=2),
        msg(3, crowd[0], [ALICE, crowd[1]], "Re: Planning", "Sounds good.", day=3),
    ])
    assert "late_handoff" not in detect(t, principal=ALICE).signals


# Delegation has the same shape as an introduction: someone adds a person and
# steps back. Found in review, 2026-09-21. On its own the handoff shape must not
# make a thread an introduction; it needs a subject or wording that says so,
# and a colleague from the sender's own company is never the introduced party.

def test_an_assistant_who_takes_over_scheduling_is_not_an_introduction():
    t = Thread(id="t_asst", messages=[
        msg(1, BEN, [ALICE], "Coffee next week?", "Free Tuesday?", day=1),
        msg(2, BEN, [ALICE, "cara@otherco.io"], "Re: Coffee next week?",
            "Adding Cara, who runs my calendar.", day=1),
        msg(3, "cara@otherco.io", [ALICE], "Re: Coffee next week?",
            "Tuesday at 10 works.", day=2),
    ])
    d = detect(t, principal=ALICE)
    assert not d.is_intro


def test_a_recruiter_handing_off_to_the_hiring_manager_is_not_an_introduction():
    t = Thread(id="t_rec", messages=[
        msg(1, "recruiter@otherco.io", [ALICE], "Intro to our team",
            "Great to talk today.", day=1),
        msg(2, "recruiter@otherco.io", [ALICE, BEN], "Re: Intro to our team",
            "Looping in Ben, the hiring manager.", day=2),
        msg(3, BEN, [ALICE], "Re: Intro to our team", "Next steps?", day=3),
    ])
    assert "late_handoff" not in detect(t, principal=ALICE).signals


def test_the_principal_handing_off_to_her_own_assistant_is_not_an_intro_she_made():
    pat = "pat@examplecorp.com"
    t = Thread(id="t_own", messages=[
        msg(1, BEN, [ALICE], "Catch up", "When are you free?", day=1),
        msg(2, ALICE, [BEN, pat], "Re: Catch up", "Pat will find a time.", day=1),
        msg(3, pat, [BEN], "Re: Catch up", "How is Thursday?", day=2),
    ])
    assert not detect(t, principal=ALICE).is_intro


def test_a_handoff_with_no_intro_subject_or_wording_is_not_enough():
    t = Thread(id="t_bare", messages=[
        msg(1, CONNECTOR, [ALICE], "Planning", "Thoughts?", day=1),
        msg(2, CONNECTOR, [ALICE, BEN], "Re: Planning", "Adding Ben.", day=2),
        msg(3, BEN, [ALICE], "Re: Planning", "Hi Alice.", day=3),
    ])
    d = detect(t, principal=ALICE)
    assert "late_handoff" in d.signals
    assert not d.is_intro


def test_handoff_wording_in_the_handoff_message_counts():
    """The words that make it an intro are in message 3, not message 1."""
    t = Thread(id="t_words", messages=[
        msg(1, CONNECTOR, [ALICE], "Quick question", "OK if I connect you?", day=1),
        msg(2, ALICE, [CONNECTOR], "Re: Quick question", "Sure!", day=1),
        msg(3, CONNECTOR, [ALICE, BEN], "Re: Quick question",
            "Alice, I'd like to introduce you to Ben.", day=2),
        msg(4, BEN, [ALICE], "Re: Quick question", "Moving Dana to bcc.", day=2),
    ])
    d = detect(t, principal=ALICE)
    assert d.is_intro and d.connector == CONNECTOR


def test_a_cold_pitch_that_the_principal_passes_on_is_still_an_intro():
    """self_pitch disqualifies the pitch, not an introduction made from it."""
    founder = "founder@fourthco.dev"
    t = Thread(id="t_pitch", messages=[
        msg(1, founder, [ALICE], "Introduction to Fourthco", "We build...", day=1),
        msg(2, ALICE, [founder, CONNECTOR], "Re: Introduction to Fourthco",
            "Dana, meet the founder. I think you two should meet.", day=2),
        msg(3, CONNECTOR, [founder], "Re: Introduction to Fourthco",
            "Moving Alice to bcc.", day=3),
    ])
    d = detect(t, principal=ALICE)
    assert d.is_intro and d.connector == ALICE


# --- three-person intros nobody drops off, 2026-09-21 ----------------------
# Measured on 67 intros the CRM holds and the scan missed: about eight were a
# plain three-person intro email with an intro subject, where everyone stayed
# on reply-all or the thread ended at one message. three_party_open (0.10) +
# subject_keyword (0.20) = 0.30, under the bar. A three-person opening is real
# evidence; with an intro subject or intro wording, it is enough.

@pytest.mark.parametrize("subject", [
    "E-Intro", "Introduction - MFA program", "Intro: Nadia Okonjo // Alice Tran",
    "Introductions", "Intros", "Introductions (re: the offsite)",
])
def test_a_three_person_email_with_an_intro_subject_is_an_intro(subject):
    t = Thread(id="t_3p", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], subject, None, day=1),
        msg(2, BEN, [CONNECTOR, ALICE], f"Re: {subject}", None, day=2),
    ])
    d = detect(t, principal=ALICE, mode="metadata")
    assert d.is_intro, d
    assert d.connector == CONNECTOR


@pytest.mark.parametrize("subject", [
    "Kai, meet Alice", "Ben meet Alice", "Re: Nadia, meet Ben",
    "Please meet Alice Tran",
])
def test_a_name_meet_name_subject_is_an_intro(subject):
    t = Thread(id="t_meet", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], subject, None, day=1)])
    d = detect(t, principal=ALICE, mode="metadata")
    assert d.is_intro and "subject_meet" in d.signals


@pytest.mark.parametrize("subject", [
    "Meet the team at our booth", "Can we meet Tuesday?", "Meeting notes",
    "Let's meet", "Come meet Ben at the offsite",
    # found in review: capitalised lead words and time words
    "Let's meet Tuesday", "Re: Let's meet Thursday", "Can't meet Friday",
    "Lets meet Next Week", "Team meet Up", "Come meet Ben!", "Please meet Soon",
    # verification review: abbreviations and group greetings
    "Lunch meet Thurs", "Everyone, meet Alice", "Hi, meet Ben", "All meet Tues",
])
def test_meet_in_an_ordinary_subject_is_not_the_meet_signal(subject):
    t = Thread(id="t_nm", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], subject, None, day=1)])
    assert "subject_meet" not in detect(t, principal=ALICE).signals


def test_a_three_person_email_with_intro_wording_in_the_body_is_an_intro():
    t = Thread(id="t_3b", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Burma trip",
            "I'd like to introduce you two — Ben just got back.", day=1)])
    assert detect(t, principal=ALICE).is_intro


def test_a_three_person_email_with_nothing_else_is_not_an_intro():
    t = Thread(id="t_3n", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Q3 planning", "Agenda attached.", day=1),
        msg(2, BEN, [CONNECTOR, ALICE], "Re: Q3 planning", "Thanks.", day=2),
    ])
    assert not detect(t, principal=ALICE).is_intro


def test_a_three_person_email_with_a_separator_subject_alone_is_not_an_intro():
    """'Drinks and dinner' to two friends is not an introduction."""
    t = Thread(id="t_3s", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "drinks and dinner", None, day=1)])
    assert not detect(t, principal=ALICE, mode="metadata").is_intro


@pytest.mark.parametrize("query", [
    "subject:intros", "subject:introductions", '"please meet"',
    '"connect you with"', '"you should meet"', '"meet my"',
    '"put you two in touch"', '"introduce you two"',
    '"introduce the two of you"', '"e-intro"',
])
def test_the_net_carries_the_wording_it_was_measured_missing(query):
    """Each found introductions the old net did not, on a 1,992-thread sample
    of a real mailbox (2026-09-21). Gmail matches whole words, so
    `subject:intro` does not find "Intros", and "put you in touch" does not
    find "put you two in touch"."""
    assert query in search_queries()


def test_a_forwarded_newsletter_is_not_an_introduction():
    """"Fwd: Introducing <a product>" sent to two friends is marketing passed
    along. The only false positive in 59 new finds, 2026-09-21."""
    body = ("Worth a look!\n---------- Forwarded message ---------\n"
            "From: Lantern <news@example.com>\nSubject: Introducing")
    t = Thread(id="t_fwdnews", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Fwd: Introducing the Lantern Series", body)])
    d = detect(t, principal=ALICE)
    assert not d.is_intro and d.disqualified_by == "forwarded_bulk"


def test_a_forwarded_intro_from_a_person_still_counts():
    body = ("See below.\n---------- Forwarded message ---------\n"
            f"From: Dana Okafor <{CONNECTOR}>\nTo: {ALICE}, {BEN}\n"
            "I'd like to introduce you two.")
    t = Thread(id="t_fwdok", messages=[
        msg(1, BEN, [ALICE], "Fwd: Intro: Alice <> Ben", body)])
    assert detect(t, principal=ALICE).is_intro


def test_a_forwarded_newsletter_in_a_one_line_snippet_is_not_an_introduction():
    """The connector's snippet collapses the body onto one line, so the quoted
    From is not at the start of a line. Found in review, 2026-09-21."""
    body = ("Worth a look! - Dana ---------- Forwarded message --------- "
            "From: Lantern <news@example.com> Date: Mon")
    t = Thread(id="t_fwd1", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Fwd: Introducing the Lantern Series", body)])
    assert detect(t, principal=ALICE).disqualified_by == "forwarded_bulk"


def test_an_intro_that_quotes_a_newsletter_further_down_still_counts():
    body = ("Alice, I'd like to introduce you to Ben. Context below.\n"
            "---------- Forwarded message ---------\n"
            "From: Substack <news@example.com>\n")
    t = Thread(id="t_fwd2", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Alice <> Ben", body)])
    assert detect(t, principal=ALICE).is_intro


def test_a_person_named_in_a_quoted_display_name_is_judged_by_address():
    """"From: Kai at Calendly <kai.rivera@example.com>" is a person."""
    body = ("See below.\n---------- Forwarded message ---------\n"
            f"From: Kai at Calendly <kai.rivera@example.com>\nTo: {ALICE}, {BEN}\n"
            "I'd like to introduce you two.")
    t = Thread(id="t_fwd3", messages=[
        msg(1, BEN, [ALICE], "Fwd: Intro: Alice <> Ben", body)])
    assert detect(t, principal=ALICE).disqualified_by != "forwarded_bulk"


def test_news_at_is_a_whole_local_part():
    t = Thread(id="t_news", messages=[
        msg(1, "dana.news@example.com", [ALICE, BEN], "Alice <> Ben",
            "I'd like to introduce you two.")])
    assert detect(t, principal=ALICE).is_intro


@pytest.mark.parametrize("subject", ["Alice <> Ben", "Alice, meet Ben",
                                     "Intro: Alice / Ben"])
def test_an_intro_that_forwards_something_automated_as_context_still_counts(subject):
    """"See below" above a forwarded LinkedIn message is an intro with
    context, not a newsletter. Verification review, 2026-09-21."""
    body = ("Alice, Ben -- see below. ---------- Forwarded message --------- "
            "From: Acme <noreply@example.com>")
    t = Thread(id="t_ctx", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], subject, body, day=1),
        msg(2, BEN, [ALICE], f"Re: {subject}", "Great to meet you.", day=2),
    ])
    assert detect(t, principal=ALICE).is_intro


@pytest.mark.parametrize("subject", ["VPN connection issue", "Connection request"])
def test_connection_in_a_subject_is_not_intro_evidence(subject):
    t = Thread(id="t_conn", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], subject, None, day=1)])
    assert not detect(t, principal=ALICE, mode="metadata").is_intro




def test_a_connection_to_someone_in_a_subject_is_intro_evidence():
    """A program match titled "Acme connection to Alice Tran" was the one
    real intro lost when "connection" was dropped outright."""
    t = Thread(id="t_conn2", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Acme connection to Alice Tran", None)])
    assert detect(t, principal=ALICE, mode="metadata").is_intro


# --- release-gate review for 0.1.12 ----------------------------------------

@pytest.mark.parametrize("body", [
    "Please meet us in the lobby at 9.", "Please meet me at the Starbucks.",
    "Please meet the deadline Friday.", "Please meet with Kai before the review.",
    "Please meet Tuesday at 10 in the lobby.", "Please meet ASAP.",
    "Could you two please meet Friday to sort the budget?",
    "Please meet The Acme team at noon.",
])
def test_please_meet_for_logistics_is_not_handoff_wording(body):
    t = Thread(id="t_pml", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Tomorrow", body, day=1)])
    d = detect(t, principal=ALICE)
    assert "body_handoff" not in d.signals and not d.is_intro


_NEWS = ("See this! ---------- Forwarded message --------- "
         "From: Acme <news@example.com>")


@pytest.mark.parametrize("subject", [
    "Fwd: Intro to AI & ML webinar", "Fwd: Webinar: Introduction to AI/ML",
    "Fwd: Intro", "Fwd: Introduction",
    "[EXT] Fwd: Introducing the Lantern Series", "WG: Introducing the Lantern Series",
    "TR: Introducing the Lantern Series", "Introducing the Lantern Series",
])
def test_forwarded_newsletters_stay_out_whatever_the_prefix(subject):
    t = Thread(id="t_fn", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], subject, _NEWS, day=1)])
    assert detect(t, principal=ALICE).disqualified_by == "forwarded_bulk"


@pytest.mark.parametrize("subject", ["Everybody, meet Alice", "Guys, meet Alice",
                                     "Y'all meet Ben", "Welcome, meet Nadia"])
def test_group_greetings_are_not_the_meet_signal(subject):
    t = Thread(id="t_gg", messages=[msg(1, CONNECTOR, [ALICE, BEN], subject, None)])
    assert "subject_meet" not in detect(t, principal=ALICE).signals


def test_a_forwarded_platform_intro_with_a_pair_subject_is_a_known_trade():
    """Known trade, pinned so it is not rediscovered as a bug: "Fwd: Nadia/Alice
    intro" quoting a no-reply platform sender, with nothing above the forward,
    reads the same as "Fwd: Intro to AI & ML webinar" and is dropped. An arrow
    subject, handoff wording above the forward, or a dropout all keep it."""
    body = "---------- Forwarded message --------- From: Hub <noreply@example.com>"
    t = Thread(id="t_trade", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Fwd: Nadia/Alice intro", body)])
    assert detect(t, principal=ALICE).disqualified_by == "forwarded_bulk"
    t.messages[0].subject = "Fwd: Alice <> Ben"
    assert detect(t, principal=ALICE).is_intro


# --- the thank-you reply, 2026-09-22 ---------------------------------------
# Hand-checking 22 intros a full scan missed: in 6 of 9 the only wording a
# search or a detector could hold on to was the reply -- "Thanks for the intro
# Dana!" -- which does not depend on how the introducer phrased theirs.

def test_a_reply_thanking_for_the_intro_makes_a_three_person_thread_an_intro():
    t = Thread(id="t_ty", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Amazing people", "Alice, Ben: see below.", day=1),
        msg(2, BEN, [ALICE, CONNECTOR], "Re: Amazing people",
            "Thanks for the intro Dana! Alice, free Tuesday?", day=2),
    ])
    d = detect(t, principal=ALICE)
    assert d.is_intro and "thanked_intro" in d.signals and d.connector == CONNECTOR


@pytest.mark.parametrize("body", [
    "Thanks for the intro call today, deck attached.",
    "Thank you for the introduction to your product.",
    "Thanks for the introduction meeting yesterday.",
])
def test_thanks_for_an_intro_call_is_not_the_signal(body):
    t = Thread(id="t_tn", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Follow up", "Great to meet.", day=1),
        msg(2, BEN, [ALICE, CONNECTOR], "Re: Follow up", body, day=2),
    ])
    assert "thanked_intro" not in detect(t, principal=ALICE).signals


def test_thanks_alone_on_a_two_person_thread_is_not_an_intro():
    t = Thread(id="t_t2", messages=[
        msg(1, CONNECTOR, [ALICE], "Hello", "Hi!", day=1),
        msg(2, ALICE, [CONNECTOR], "Re: Hello", "Thanks for the intro!", day=2),
    ])
    assert not detect(t, principal=ALICE).is_intro


@pytest.mark.parametrize("body", [
    "Connecting the two of you. Ben is looking for research help.",
    "Hi both, this email is to connect you.",
    "I'd love to introduce the two of you.",
])
def test_more_handoff_wording(body):
    t = Thread(id="t_hw", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Hello", body, day=1)])
    assert "body_handoff" in detect(t, principal=ALICE).signals


@pytest.mark.parametrize("query", ['"for the intro"', '"for the introduction"',
                                   '"for introducing"', '"the two of you"'])
def test_the_net_carries_the_thank_you_wording(query):
    assert query in search_queries()


@pytest.mark.parametrize("subject", ["Nadia >< Kai", "Alice >  < Ben"])
def test_the_reversed_arrow_is_an_arrow(subject):
    """"A >< B" is as common as "A <> B" in a real mailbox (2026-09-22)."""
    t = Thread(id="t_ra", messages=[msg(1, CONNECTOR, [ALICE, BEN], subject, None)])
    assert "subject_arrow" in detect(t, principal=ALICE).signals


@pytest.mark.parametrize("body", [
    "Thank you for introducing yourself!", "Thanks for the intro to the team.",
    "Thanks for the intro-call today.", "Thanks for the intro chat.",
    "Thanks for introducing me to the product.",
])
def test_more_thanks_that_are_not_for_an_introduction(body):
    t = Thread(id="t_tn2", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Follow up", "Great to meet.", day=1),
        msg(2, BEN, [ALICE, CONNECTOR], "Re: Follow up", body, day=2)])
    assert "thanked_intro" not in detect(t, principal=ALICE).signals


@pytest.mark.parametrize("subject", ["ugh >< deadline moved",
                                     "<b>Sale</b><i>today</i>"])
def test_an_emoticon_or_markup_is_not_an_arrow(subject):
    t = Thread(id="t_em", messages=[msg(1, CONNECTOR, [ALICE, BEN], subject, None)])
    assert "subject_arrow" not in detect(t, principal=ALICE).signals


@pytest.mark.parametrize("body", [
    "Thanks for introducing this idea at standup.",
    "Thank you for the kind introduction yesterday at the panel.",
    "Thanks for introducing the new pricing model.",
    "Thanks for introducing our team to the tool.",
    "Thank you for the introduction to the course material.",
    # An artifact, not a person. These are what a lowercase-name branch let
    # back in, and none of the other guards catches them.
    "Thanks for the intro slides!",
    "Thanks for the intro doc.",
    "Thanks for the intro materials, very helpful",
    "Thanks for the intro pricing.",
])
def test_thanks_for_introducing_a_thing_is_not_an_introduction(body):
    """A thank-you names a person, or it is about work. On a three-person
    thread this scored 0.50 and became a row someone would be thanked for
    (gate review, 2026-09-22)."""
    t = Thread(id="t_ti", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Pricing deck", "Both -- see attached.", day=1),
        msg(2, BEN, [ALICE, CONNECTOR], "Re: Pricing deck", body, day=2)])
    d = detect(t, principal=ALICE)
    assert "thanked_intro" not in d.signals and not d.is_intro


@pytest.mark.parametrize("body", [
    "Thanks for the intro [bcc]!",
    "thanks for the wonderful intro - I always enjoy these.",
    "Thank you for the introduction and the kind words Dana",
])
def test_a_thank_you_in_other_shapes_still_counts(body):
    """Measured on the real corpus: the capital-letter rule alone lost nine
    genuine thank-yous (gate review, 2026-09-22)."""
    t = Thread(id="t_ts", messages=[
        msg(1, CONNECTOR, [ALICE, BEN], "Intro", "Both -- meet.", day=1),
        msg(2, BEN, [ALICE, CONNECTOR], "Re: Intro", body, day=2)])
    assert "thanked_intro" in detect(t, principal=ALICE).signals
