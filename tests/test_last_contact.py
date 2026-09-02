"""Last direct contact per address. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from last_contact import DIRECT_MAX_RECIPIENTS, last_direct_contact  # noqa: E402
from mail_source import Message, Thread  # noqa: E402

ME = "alice.tran@examplecorp.com"
DANA = "dana.okafor@example.com"
BEN = "ben@otherco.io"


def msg(day, frm, to, is_bulk=False, cc=(), calendar=False):
    return Message(id="m%d" % day, from_addr=frm, to_addrs=list(to),
                   cc_addrs=list(cc), subject="hi",
                   date=datetime(2026, 1, day), is_bulk=is_bulk,
                   is_calendar_invite=calendar)


class FakeSource:
    def __init__(self, threads, principal=ME):
        self._threads = {t.id: t for t in threads}
        self._principal = principal

    def principal(self):
        return self._principal

    def search(self, query, limit=200):
        return list(self._threads)[:limit]

    def fetch(self, thread_ids, include_bodies=True):
        return [self._threads[i] for i in thread_ids]


def src(*messages):
    return FakeSource([Thread(id="t%d" % i, messages=[m])
                       for i, m in enumerate(messages)])


def test_the_most_recent_direct_message_wins_in_either_direction():
    seen = last_direct_contact(src(msg(3, ME, [DANA]), msg(9, DANA, [ME])), ME)
    assert seen[DANA].date == "2026-01-09"


def test_the_principal_is_not_their_own_contact():
    assert ME not in last_direct_contact(src(msg(3, ME, [DANA])), ME)


def test_a_bulk_message_is_not_contact():
    """List-Unsubscribe / Precedence: bulk. Replying to a newsletter is not
    having spoken to its author."""
    seen = last_direct_contact(src(msg(3, ME, [DANA]), msg(9, DANA, [ME], is_bulk=True)), ME)
    assert seen[DANA].date == "2026-01-03"


def test_a_blast_is_not_contact_even_when_it_carries_no_unsubscribe_header():
    """An investor update or a life-update blast reaches twenty people and
    carries no List-Unsubscribe. Counting it produces a roster full of people
    the user has not actually spoken to in years -- which is the exact failure
    the roster exists to avoid."""
    crowd = ["p%d@example.com" % i for i in range(DIRECT_MAX_RECIPIENTS + 1)]
    seen = last_direct_contact(
        src(msg(3, ME, [DANA]), msg(9, DANA, [ME] + crowd)), ME)
    assert seen[DANA].date == "2026-01-03"


def test_a_small_group_thread_still_counts_as_contact():
    seen = last_direct_contact(src(msg(9, DANA, [ME, BEN])), ME)
    assert seen[DANA].date == "2026-01-09"
    assert seen[BEN].date == "2026-01-09"


def test_a_calendar_invite_is_not_a_conversation():
    seen = last_direct_contact(src(msg(9, DANA, [ME], calendar=True)), ME)
    assert DANA not in seen


def test_it_records_which_address_was_seen_and_when():
    """The domain is where they emailed from, not where they work -- so the
    roster shows the address it actually saw and the date it saw it, and never
    says "works at"."""
    seen = last_direct_contact(src(msg(9, DANA, [ME])), ME)
    assert seen[DANA].address == DANA
    assert seen[DANA].date == "2026-01-09"


def test_mail_that_never_involves_the_principal_is_ignored():
    seen = last_direct_contact(src(msg(9, DANA, [BEN])), ME)
    assert seen == {}


def test_an_undated_message_cannot_become_the_latest_contact():
    m = msg(9, DANA, [ME])
    m.date = None
    assert last_direct_contact(src(m), ME) == {}


def test_only_addresses_asked_for_are_returned_when_a_filter_is_given():
    """The roster only ever needs the people already on it; scanning for
    everyone would return the whole mailbox."""
    seen = last_direct_contact(src(msg(3, ME, [DANA]), msg(4, ME, [BEN])),
                               ME, addresses={DANA})
    assert set(seen) == {DANA}


# --------------------------------------------------------------------------
# Progress and checkpointing
#
# A real roster run took over two hours against a 325k-thread mailbox and
# printed one line at the start. Nothing was written until the last statement,
# so killing it at any point returned the roster exactly as it started. And it
# announced the number of PEOPLE while the unit of work was threads, which made
# a long run look like a hang rather than a long run.
# --------------------------------------------------------------------------

def test_the_thread_count_is_announced_before_the_work_starts():
    """The roster size is not the work. `on_start` fires with what will
    actually be read."""
    seen = []
    s = src(msg(3, ME, [DANA]), msg(9, DANA, [ME]))
    last_direct_contact(s, ME, on_start=seen.append)
    assert seen == [2]


def test_progress_reports_and_hands_over_the_live_results():
    """A caller has to be able to persist mid-run, so the callback receives the
    partial dict rather than only a count."""
    from last_contact import CHUNK
    msgs = [msg(i % 28 + 1, "p%03d@example.com" % i, [ME]) for i in range(CHUNK + 5)]
    ticks = []
    last_direct_contact(src(*msgs), ME,
                        on_progress=lambda d, t, live: ticks.append(
                            (d, t, len(live), isinstance(live, dict))))
    assert len(ticks) >= 2, "one chunk means no progress was ever reported"
    done, total, _, is_dict = ticks[-1]
    assert done == total and is_dict
    assert ticks[0][2] > 0, "the first tick already carries results to save"
    assert ticks[-1][2] >= ticks[0][2], "results only accumulate"


def test_progress_is_optional():
    """Every existing caller passes neither hook."""
    seen = last_direct_contact(src(msg(9, DANA, [ME])), ME)
    assert DANA in seen
