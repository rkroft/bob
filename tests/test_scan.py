"""Scan pipeline. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mail_source import Message, Thread  # noqa: E402
from scan import scan  # noqa: E402

CONNECTOR = "dana.okafor@example.com"
ALICE = "alice.tran@examplecorp.com"
BEN = "ben.mercer@otherco.io"


def msg(i, frm, to, subject, body, day=1):
    return Message(id=f"m{i}", from_addr=frm, to_addrs=to, subject=subject,
                   body_text=body, date=datetime(2026, 3, day))


class FakeSource:
    """Minimal MailSource. Returns the same threads for any query, which is
    fine — dedup by thread id is part of what we are testing."""

    def __init__(self, threads, principal):
        self._threads = {t.id: t for t in threads}
        self._principal = principal

    def principal(self):
        return self._principal

    def search(self, query, limit=200):
        return list(self._threads)[:limit]

    def fetch(self, thread_ids, include_bodies=True):
        return [self._threads[i] for i in thread_ids]


INBOUND = Thread(id="in1", messages=[msg(
    1, CONNECTOR, [ALICE, BEN], "Intro: Alice <> Ben",
    "I'd like to introduce you two. Moving myself to bcc.")])

OUTBOUND = Thread(id="out1", messages=[msg(
    2, ALICE, [BEN, "cara.silva@thirdco.com"], "Intro: Ben <> Cara",
    "Connecting you two. Ben, Cara is who I mentioned.")])

NOISE = Thread(id="n1", messages=[msg(
    3, "news@example.com", [ALICE], "Lunch", "nothing to see here")])

# Someone ELSE asking the principal for an intro — the shape every other
# fixture in this file misses, because every other fixture is a three-party
# handoff. Two visible participants: BEN (sender) and ALICE (the principal).
# _assign_roles hands ALICE the "connector" seat here (she's the one being
# asked), which _DIRECTION would map to "outbound" if scan() didn't check
# d.kind first — recording BEN's request as an intro ALICE made, with BEN as
# the person "introduced". No introduction has happened; there's nothing to
# record in either seat.
REQUEST_TO_PRINCIPAL = Thread(id="req1", messages=[msg(
    4, BEN, [ALICE], "Intro to Nadia Okonjo?",
    "Any chance you could introduce me to Nadia Okonjo? I think she'd be great to meet.")])


def test_detects_an_inbound_intro_and_labels_it():
    rows = scan(FakeSource([INBOUND], ALICE))
    assert len(rows) == 1
    assert rows[0].direction == "inbound"
    assert rows[0].introducer == CONNECTOR
    assert BEN in rows[0].introduced


def test_labels_an_intro_the_principal_made_as_outbound():
    rows = scan(FakeSource([OUTBOUND], ALICE))
    assert len(rows) == 1
    assert rows[0].direction == "outbound"
    assert rows[0].introducer == ALICE


def test_non_intros_produce_no_rows():
    assert scan(FakeSource([NOISE], ALICE)) == []


def test_a_thread_matched_by_several_queries_yields_one_row():
    rows = scan(FakeSource([INBOUND], ALICE))
    assert len({r.thread_id for r in rows}) == len(rows) == 1


def test_date_comes_from_the_opening_message_as_iso():
    rows = scan(FakeSource([INBOUND], ALICE))
    assert rows[0].date == "2026-03-01"


def test_link_callback_is_used_when_supplied():
    rows = scan(FakeSource([INBOUND], ALICE),
                link_for=lambda tid: f"https://example.test/{tid}")
    assert rows[0].thread_link == "https://example.test/in1"


def test_no_link_callback_leaves_the_link_empty():
    assert scan(FakeSource([INBOUND], ALICE))[0].thread_link == ""


def test_someone_asking_the_principal_for_an_intro_yields_no_rows():
    """Regression for the critical fix: a request for an introduction is not
    a completed introduction, no matter which seat the principal occupies. On
    a real 362-row mailbox, 40 of 114 rows scan() had labeled "intros you
    made" were actually this shape — someone else asking the principal to
    make an introduction, with scan() recording it backwards (principal as
    introducer, requester as the person "introduced"). Six prior reviews
    missed this because every fixture in this file is a three-party handoff;
    this is the two-party request shape."""
    assert scan(FakeSource([REQUEST_TO_PRINCIPAL], ALICE)) == []


def test_principal_is_retained_in_introduced_on_an_inbound_intro():
    """The edge connector -> principal is the fact this product exists to
    surface: "Dana introduced you to Ben". Excluding the principal here would
    remove the user from their own graph. Do not "fix" this."""
    rows = scan(FakeSource([INBOUND], ALICE))
    assert ALICE in rows[0].introduced
    assert BEN in rows[0].introduced


# --------------------------------------------------------------------------
# Display-name collection. The scan is the only place that sees raw messages,
# so it is the only place names can be harvested.
# --------------------------------------------------------------------------


def test_scan_collects_display_names_when_asked():
    thread = Thread(id="in1", messages=[Message(
        id="m1", from_addr=CONNECTOR, from_name="Dana Okafor",
        to_addrs=[ALICE, BEN], to_names=["Alice Tran", "Ben Mercer"],
        subject="Intro: Alice <> Ben",
        body_text="I'd like to introduce you two. Moving myself to bcc.",
        date=datetime(2026, 3, 1),
    )])
    names = {}
    scan(FakeSource([thread], ALICE), names_out=names)
    assert "Dana Okafor" in names[CONNECTOR]
    assert "Ben Mercer" in names[BEN]


def test_names_are_collected_even_from_threads_that_are_not_intros():
    """A person's name is worth keeping wherever it appears — the thread it
    came from does not have to be an introduction."""
    thread = Thread(id="n1", messages=[Message(
        id="m1", from_addr="someone@example.com", from_name="Some One",
        to_addrs=[ALICE], to_names=["Alice Tran"], subject="Lunch",
        body_text="nothing to see", date=datetime(2026, 3, 1),
    )])
    names = {}
    scan(FakeSource([thread], ALICE), names_out=names)
    assert names.get("someone@example.com") == ["Some One"]


def test_scan_without_names_out_behaves_exactly_as_before():
    assert len(scan(FakeSource([INBOUND], ALICE))) == 1


def test_names_are_not_harvested_from_calendar_or_bulk_mail():
    """Calendar RSVPs carry whatever name the *system* holds for someone and
    repeat it once per event, which let an automated form outvote the name a
    person signs their own mail with. Real case: a contact whose calendar
    account said "Marcus Leyva" while his correspondence said "Marcus Lee", with
    the RSVPs outnumbering the letters."""
    cal = Thread(id="c1", messages=[Message(
        id="m1", from_addr=CONNECTOR, from_name="Machine Form",
        to_addrs=[ALICE], to_names=["Alice Tran"], subject="RSVP (Yes): Party",
        body_text="has accepted your invitation", date=datetime(2026, 3, 1),
        is_calendar_invite=True,
    )])
    blast = Thread(id="b1", messages=[Message(
        id="m2", from_addr=CONNECTOR, from_name="Newsletter Form",
        to_addrs=[ALICE], to_names=["Alice Tran"], subject="Update",
        body_text="hello all", date=datetime(2026, 3, 2), is_bulk=True,
    )])
    human = Thread(id="h1", messages=[Message(
        id="m3", from_addr=CONNECTOR, from_name="Dana Okafor",
        to_addrs=[ALICE], to_names=["Alice Tran"], subject="Hi",
        body_text="a real note", date=datetime(2026, 3, 3),
    )])
    names = {}
    scan(FakeSource([cal, blast, human], ALICE), names_out=names)
    assert names[CONNECTOR] == ["Dana Okafor"]


def test_a_query_that_fills_its_limit_is_reported_not_swallowed():
    """Gmail returns newest first, so a query that fills its cap means older
    mail was silently dropped. Rachel's real mailbox capped five of sixteen
    queries and nothing said so — the scan looked complete and was not."""
    class Capped(FakeSource):
        def search(self, query, limit=200):
            # Fills the cap with ids, only one of which resolves — which is
            # also how the real Gmail source behaves: it skips a thread it
            # cannot fetch rather than raising.
            return ["in1"] + [f"gone{i}" for i in range(limit - 1)]

        def fetch(self, thread_ids, include_bodies=True):
            return [self._threads[i] for i in thread_ids if i in self._threads]

    capped = []
    scan(Capped([INBOUND], ALICE), limit_per_query=3, capped_out=capped)
    assert capped, "a saturated query must be reported"
    assert all(isinstance(q, str) for q in capped)


def test_no_report_when_nothing_was_truncated():
    capped = []
    scan(FakeSource([INBOUND], ALICE), capped_out=capped)
    assert capped == []


def test_scan_records_who_the_principal_wrote_to():
    """Replying is the evidence that there is a person on the other end. It
    only counts when the principal is the SENDER — being a recipient of your
    own newsletter says nothing."""
    t = Thread(id="x", messages=[
        Message(id="m1", from_addr=CONNECTOR, to_addrs=[ALICE],
                subject="Hi", body_text="hello", date=datetime(2026, 3, 1)),
        Message(id="m2", from_addr=ALICE, to_addrs=[CONNECTOR], subject="Re: Hi",
                body_text="hello back", date=datetime(2026, 3, 2)),
    ])
    contacted, automated = set(), set()
    scan(FakeSource([t], ALICE), contacted_out=contacted, automated_out=automated)
    assert CONNECTOR in contacted


def test_scan_records_senders_whose_mail_is_machine_generated():
    t = Thread(id="y", messages=[Message(
        id="m1", from_addr="talent@angel.co", to_addrs=[ALICE], subject="Match",
        body_text="New match", date=datetime(2026, 3, 1), is_bulk=True)])
    contacted, automated = set(), set()
    scan(FakeSource([t], ALICE), contacted_out=contacted, automated_out=automated)
    assert "talent@angel.co" in automated
    assert "talent@angel.co" not in contacted


def test_no_limit_means_exhaustive_and_nothing_is_reported_as_capped():
    """A cap is a silent lie about coverage: Gmail returns newest first, so a
    truncated search looks exactly like a mailbox with fewer introductions in
    it. Exhaustive is the default; a cap is now something you opt into."""
    class Counting(FakeSource):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.limits = []

        def search(self, query, limit=None):
            self.limits.append(limit)
            return list(self._threads)

    src = Counting([INBOUND], ALICE)
    capped = []
    scan(src, limit_per_query=None, capped_out=capped)
    assert capped == []
    assert all(l is None for l in src.limits), src.limits


def test_the_scan_records_what_became_of_each_introduction():
    """§4.6's evidence is only available while the thread is in hand — the scan
    is the one place that sees raw messages."""
    from datetime import datetime
    from mail_source import Message, Thread
    from after import triage
    from intro_store import after_of

    me, dana, ben = "alice@examplecorp.com", "dana@example.com", "ben@otherco.io"

    def m(frm, day):
        return Message(id=f"m{day}", from_addr=frm, to_addrs=[me, dana, ben],
                       subject="Intro: Alice <> Ben", date=datetime(2026, 3, day),
                       body_text="I'd like to introduce you two. Alice, meet Ben.")

    class Src:
        def principal(self): return me
        def search(self, query, limit=None): return ["t1"]
        def fetch(self, thread_ids, include_bodies=True):
            return [Thread(id="t1", messages=[m(dana, 1), m(me, 2)])]

    rows = scan(Src())
    assert rows, "the fixture must detect as an introduction"
    r = rows[0]
    assert r.observed is True
    assert r.replied is True
    assert r.first_reply == "2026-03-02"
    assert triage(after_of(r)) == "took_hold"
