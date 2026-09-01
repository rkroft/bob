"""Reading the chain backwards — where a person came from.

Invented placeholder people only (repo rule).

Forward, a chain measures an introducer's reach. Backward, it answers the
question a user actually asks about a specific person: *how do I know them?*

Two disciplines carry over from `Chain`, and they are what these tests are
mostly about: every hop must **pre-date** the introduction it caused, and a hop
with an unknown date ends the walk rather than guessing an order.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graph_model import build_graph, provenance  # noqa: E402
from intro_store import IntroRow  # noqa: E402

ME = "alice.tran@examplecorp.com"
JUNE = "june.hale@example.com"          # the root: introduced by nobody
LEO = "leo.vance@secondco.io"           # June introduced Alice to Leo
EVA = "eva.bloom@thirdco.dev"           # Leo introduced Alice to Eva
TERRY = "terry.cho@fourthco.net"        # Eva introduced Alice to Terry
TODAY = date(2026, 8, 20)


def row(tid, introducer, introduced, d, direction="inbound"):
    return IntroRow(thread_id=tid, date=d, direction=direction,
                    introducer=introducer, introduced=tuple(introduced),
                    subject="Intro", thread_link="", confidence=0.9)


def ladder(*, terry_date="2024-08-01"):
    """June -> Leo -> Eva -> Terry, each introduction after the one before."""
    return [
        row("1", JUNE, [ME, LEO], "2024-01-10"),
        row("2", LEO, [ME, EVA], "2024-02-20"),
        row("3", EVA, [ME, TERRY], terry_date),
    ]


def path(g, person):
    return [(h.who, h.date) for h in provenance(g, person)]


def test_a_person_nobody_introduced_has_no_origin():
    g = build_graph(ladder(), ME, today=TODAY)
    assert provenance(g, JUNE) == ()


def test_one_hop_is_the_common_case():
    g = build_graph(ladder(), ME, today=TODAY)
    assert path(g, LEO) == [(JUNE, "2024-01-10")]


def test_two_hops_back():
    g = build_graph(ladder(), ME, today=TODAY)
    assert path(g, EVA) == [(LEO, "2024-02-20"), (JUNE, "2024-01-10")]


def test_three_hops_back():
    g = build_graph(ladder(), ME, today=TODAY)
    assert path(g, TERRY) == [
        (EVA, "2024-08-01"), (LEO, "2024-02-20"), (JUNE, "2024-01-10")]


def test_the_walk_stops_where_a_hop_did_not_pre_date_the_one_it_caused():
    """Eva introduced Terry in February, but Leo only introduced Eva in June.
    Eva cannot have reached Terry *because of* Leo, so the walk stops at Eva."""
    rows = [
        row("1", JUNE, [ME, LEO], "2024-01-10"),
        row("2", LEO, [ME, EVA], "2024-06-01"),
        row("3", EVA, [ME, TERRY], "2024-02-01"),
    ]
    g = build_graph(rows, ME, today=TODAY)
    assert path(g, TERRY) == [(EVA, "2024-02-01")]


def test_an_unknown_date_ends_the_walk_rather_than_guessing():
    rows = [
        row("1", JUNE, [ME, LEO], "2024-01-10"),
        row("2", LEO, [ME, EVA], ""),
        row("3", EVA, [ME, TERRY], "2024-08-01"),
    ]
    g = build_graph(rows, ME, today=TODAY)
    assert path(g, TERRY) == [(EVA, "2024-08-01")]


def test_the_earliest_introduction_is_the_origin():
    """Introduced twice — the first one is how you came to know them."""
    rows = ladder() + [row("4", EVA, [ME, LEO], "2025-03-03")]
    g = build_graph(rows, ME, today=TODAY)
    assert path(g, LEO)[0] == (JUNE, "2024-01-10")


def test_an_outbound_row_never_creates_provenance():
    """On an outbound row `introduced` holds two people connected to each
    other, not people the principal met. Folding those in would invent an
    origin that never happened."""
    g = build_graph([row("1", ME, [LEO, EVA], "2024-01-10", "outbound")],
                    ME, today=TODAY)
    assert provenance(g, EVA) == ()


def test_the_principal_never_appears_in_a_path():
    g = build_graph(ladder(), ME, today=TODAY)
    for person in (LEO, EVA, TERRY):
        assert ME not in [h.who for h in provenance(g, person)]


def test_a_cycle_terminates():
    """Two people who each introduced the other. Whatever the answer is, it
    must not loop."""
    rows = [
        row("1", LEO, [ME, EVA], "2024-01-10"),
        row("2", EVA, [ME, LEO], "2024-02-20"),
    ]
    g = build_graph(rows, ME, today=TODAY)
    assert len(provenance(g, EVA)) <= 2
    assert len(provenance(g, LEO)) <= 2


def test_an_unknown_person_has_no_origin():
    g = build_graph(ladder(), ME, today=TODAY)
    assert provenance(g, "nobody@example.invalid") == ()


# --------------------------------------------------------------------------
# The rules above are only as good as the tests defending them. A mutation
# pass on 2026-08-31 found 7 of 15 mutants surviving, concentrated in the
# origins reduction and the cycle guard. These close that gap: each one fails
# if the specific rule it names is removed.
# --------------------------------------------------------------------------

def test_a_same_day_cycle_terminates():
    """Two people who introduced you to each other on the SAME day.

    Equal dates satisfy the on-or-before rule forever, so only the visited set
    ends this walk. Without the cycle guard this hangs rather than fails —
    which is why the older two-date cycle test could not defend it.
    """
    rows = [
        row("1", LEO, [ME, EVA], "2024-01-10"),
        row("2", EVA, [ME, LEO], "2024-01-10"),
    ]
    g = build_graph(rows, ME, today=TODAY)
    assert len(provenance(g, EVA)) == 1
    assert len(provenance(g, LEO)) == 1


def test_a_same_day_hop_is_allowed_because_the_forward_chain_allows_it():
    """`Chain` treats onward as "on or after"; backward mirrors it. A shared
    date is not evidence against causation, so the walk continues."""
    rows = [
        row("1", JUNE, [ME, LEO], "2024-03-01"),
        row("2", LEO, [ME, EVA], "2024-03-01"),
        row("3", EVA, [ME, TERRY], "2024-03-01"),
    ]
    g = build_graph(rows, ME, today=TODAY)
    assert len(provenance(g, TERRY)) == 3


def test_a_dated_introduction_beats_an_undated_one_whatever_the_row_order():
    dated = row("d", LEO, [ME, EVA], "2024-02-20")
    undated = row("u", JUNE, [ME, EVA], "")
    for rows in ([undated, dated], [dated, undated]):
        g = build_graph(rows, ME, today=TODAY)
        assert g.origins[EVA] == (LEO, "2024-02-20")


def test_an_undated_origin_is_still_an_origin():
    """"Dana introduced you" is true whether or not the date survived. The
    first hop is a fact; only what lies BEYOND it needs an ordering."""
    g = build_graph([row("1", JUNE, [ME, EVA], "")], ME, today=TODAY)
    assert g.origins[EVA] == (JUNE, "")
    assert path(g, EVA) == [(JUNE, "")]


def test_an_undated_second_hop_is_dropped_rather_than_asserted():
    """Leo introduced you to Eva at an unknown time. Eva introduced you to
    Terry in August. Leo cannot be placed before that, so he is not part of
    how you came to know Terry — even though he IS Eva's own origin."""
    rows = [
        row("1", JUNE, [ME, LEO], "2024-01-10"),
        row("2", LEO, [ME, EVA], ""),
        row("3", EVA, [ME, TERRY], "2024-08-01"),
    ]
    g = build_graph(rows, ME, today=TODAY)
    assert path(g, TERRY) == [(EVA, "2024-08-01")]
    assert path(g, EVA) == [(LEO, "")]


def test_same_day_introductions_break_the_tie_the_same_way_each_time():
    a = row("a", JUNE, [ME, EVA], "2024-01-10")
    b = row("b", LEO, [ME, EVA], "2024-01-10")
    assert (build_graph([a, b], ME, today=TODAY).origins[EVA]
            == build_graph([b, a], ME, today=TODAY).origins[EVA])


def test_two_undated_introductions_break_the_tie_the_same_way_each_time():
    """The undated case had no tie-break at all: whichever row arrived first
    won. Row order is not data."""
    a = row("a", JUNE, [ME, EVA], "")
    b = row("b", LEO, [ME, EVA], "")
    assert (build_graph([a, b], ME, today=TODAY).origins[EVA]
            == build_graph([b, a], ME, today=TODAY).origins[EVA])
