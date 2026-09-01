"""Graph model. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graph_model import build_graph, chain_starters  # noqa: E402
from intro_store import IntroRow  # noqa: E402

ME = "alice.tran@examplecorp.com"
DANA = "dana.okafor@example.com"
MARCUS = "marcus.lee@thirdco.com"
CARA = "cara@thirdco.com"
NILS = "nils@fourthco.dev"
TODAY = date(2026, 8, 20)


def row(tid, introducer, introduced, d="2026-01-01", direction="inbound"):
    return IntroRow(thread_id=tid, date=d, direction=direction,
                    introducer=introducer, introduced=tuple(introduced),
                    subject="Intro", thread_link="", confidence=0.9)


def test_every_person_becomes_exactly_one_node():
    g = build_graph([row("1", DANA, [ME, "ben@otherco.io"])], ME, today=TODAY)
    assert sorted(n.id for n in g.nodes) == sorted([DANA, ME, "ben@otherco.io"])


def test_one_edge_per_introduced_person():
    g = build_graph([row("1", DANA, [ME, "ben@otherco.io"])], ME, today=TODAY)
    assert sorted((e.src, e.dst) for e in g.edges) == sorted(
        [(DANA, ME), (DANA, "ben@otherco.io")])


def test_stats_count_intros_and_distinct_people():
    rows = [row("1", DANA, [ME]), row("2", DANA, ["ben@otherco.io"])]
    g = build_graph(rows, ME, today=TODAY)
    assert g.stats.intros == 2
    assert g.stats.people == 3


def test_last_12_months_uses_the_supplied_today():
    rows = [row("1", DANA, [ME], d="2020-01-01"),
            row("2", DANA, [ME], d="2026-06-01")]
    g = build_graph(rows, ME, today=TODAY)
    assert g.stats.last_12mo == 1


def test_super_connectors_are_the_smallest_set_reaching_half():
    rows = ([row(str(i), DANA, [f"p{i}@x.test"]) for i in range(6)]
            + [row("9", MARCUS, ["q@x.test"])])
    g = build_graph(rows, ME, today=TODAY)
    assert [a for a, _ in g.super_connectors] == [DANA]


def test_super_connectors_can_be_more_than_one_person():
    # Dana 3, Marcus 2, two singletons = 7 inbound. Dana alone is 3 of 7, short
    # of half, so Marcus is required to reach it. (With only one singleton Dana
    # would be 3 of 6 — already half — and the set would correctly be [DANA].)
    rows = ([row(str(i), DANA, [f"p{i}@x.test"]) for i in range(3)]
            + [row("a", MARCUS, ["q1@x.test"]), row("b", MARCUS, ["q2@x.test"])]
            + [row("c", "solo1@x.test", ["r1@x.test"]),
               row("d", "solo2@x.test", ["r2@x.test"])])
    g = build_graph(rows, ME, today=TODAY)
    assert [a for a, _ in g.super_connectors] == [DANA, MARCUS]


def test_outbound_intros_do_not_count_toward_super_connectors():
    rows = [row(str(i), ME, [f"p{i}@x.test"], direction="outbound")
            for i in range(5)]
    g = build_graph(rows, ME, today=TODAY)
    assert g.super_connectors == []


def test_super_connectors_are_capped_at_eight_on_a_flat_distribution():
    """On a flat distribution "smallest set reaching half" degenerates toward
    "everyone" — a real 362-row mailbox produced 45 super-connectors this way,
    which is not a usable list. 20 people each introducing exactly one person
    never reaches half no matter how many are named, so without a cap this
    would keep going past 20; the cap must stop it at 8."""
    rows = [row(str(i), f"introducer{i}@x.test", [f"p{i}@x.test"])
            for i in range(20)]
    g = build_graph(rows, ME, today=TODAY)
    assert len(g.super_connectors) == 8


def test_super_connectors_below_the_cap_are_unchanged():
    """The cap must not shrink a set that already naturally reaches half in
    fewer than 8 names — this is the existing small-set behaviour and must
    survive the cap untouched."""
    rows = ([row(str(i), DANA, [f"p{i}@x.test"]) for i in range(6)]
            + [row("9", MARCUS, ["q@x.test"])])
    g = build_graph(rows, ME, today=TODAY)
    assert len(g.super_connectors) < 8
    assert [a for a, _ in g.super_connectors] == [DANA]


def test_no_rows_is_an_empty_graph_not_a_crash():
    g = build_graph([], ME, today=TODAY)
    assert g.nodes == [] and g.edges == [] and g.stats.intros == 0
    assert g.super_connectors == []


def test_introduced_to_excludes_people_from_outbound_rows():
    """On an outbound row the principal is the introducer, and `introduced`
    holds the two people they connected to each other — not people the
    principal was introduced to. If those addresses leaked into
    `introduced_to`, the summary sentence "N people you were introduced to"
    would name people who never introduced the principal to anyone. Only the
    inbound row's non-principal recipient (frank) should count; ben, who only
    appears on the outbound row, must not."""
    rows = [row("1", DANA, [ME, "frank@place.io"], direction="inbound"),
            row("2", ME, ["ben@otherco.io"], direction="outbound")]
    g = build_graph(rows, ME, today=TODAY)
    assert g.stats.introduced_to == 1


def test_leap_year_does_not_crash_on_feb_29():
    """Regression test: today.replace(year=...) crashes on 2028-02-29 (no
    Feb 29 in 2027). The fix uses timedelta(days=365) instead, which is
    approximate but safe."""
    rows = [row("1", DANA, [ME], d="2026-01-01")]
    # Call with today = 2028-02-29, a leap day with no equivalent last year
    g = build_graph(rows, ME, today=date(2028, 2, 29))
    assert g.stats.last_12mo == 0  # 2026-01-01 is > 365 days before 2028-02-29


def test_node_labels_use_supplied_names():
    g = build_graph([row("1", DANA, [ME])], ME, today=TODAY,
                    names={DANA: "Dana Okafor", ME: "Alice Tran"})
    labels = {n.id: n.label for n in g.nodes}
    assert labels[DANA] == "Dana Okafor"


def test_node_labels_fall_back_to_the_local_part_without_a_name():
    g = build_graph([row("1", DANA, [ME])], ME, today=TODAY)
    labels = {n.id: n.label for n in g.nodes}
    assert labels[DANA] == "Dana Okafor"        # derived from dana.okafor


def test_a_supplied_name_beats_the_derived_one():
    """mlee@… derives to "Mlee"; the header said "Marcus Lee"."""
    g = build_graph([row("1", "mlee@x.test", [ME])], ME, today=TODAY,
                    names={"mlee@x.test": "Marcus Lee"})
    assert {n.label for n in g.nodes} >= {"Marcus Lee"}


def test_people_given_counts_distinct_people_not_rows():
    """One thread introducing two people is one row and two people. The ring
    labels a node with this number and the sentence beside it says 'people',
    so the two must be the same claim."""
    g = build_graph([row("1", DANA, [ME, "ben@otherco.io", "cara@thirdco.com"])],
                    ME, today=TODAY)
    dana = [n for n in g.nodes if n.id == DANA][0]
    assert dana.given == 1            # one row
    assert dana.people_given == 2     # ben and cara; the principal never counts


def test_people_given_deduplicates_across_rows():
    rows = [row("1", DANA, [ME, "ben@otherco.io"]),
            row("2", DANA, [ME, "ben@otherco.io"]),
            row("3", DANA, [ME, "cara@thirdco.com"])]
    g = build_graph(rows, ME, today=TODAY)
    dana = [n for n in g.nodes if n.id == DANA][0]
    assert dana.given == 3
    assert dana.people_given == 2


def test_people_given_ignores_outbound_rows():
    """On an outbound row the principal is the introducer and `introduced`
    holds two people connected to each other, not people the principal met."""
    rows = [row("1", ME, [DANA, MARCUS], direction="outbound")]
    g = build_graph(rows, ME, today=TODAY)
    me = [n for n in g.nodes if n.id == ME][0]
    assert me.people_given == 0


def test_given_is_unchanged_by_this_work():
    """Regression pin. `given` counts rows and other views read it; this change
    adds a number beside it rather than redefining it."""
    rows = [row("1", DANA, [ME, "ben@otherco.io"]),
            row("2", DANA, [ME, "cara@thirdco.com"])]
    g = build_graph(rows, ME, today=TODAY)
    dana = [n for n in g.nodes if n.id == DANA][0]
    assert dana.given == 2


def test_an_introducer_never_counts_themselves():
    """A row where the introducer also appears in `introduced` must not credit
    them with introducing themselves."""
    g = build_graph([row("1", DANA, [ME, DANA, MARCUS])], ME, today=TODAY)
    dana = [n for n in g.nodes if n.id == DANA][0]
    assert dana.people_given == 1


def test_the_same_person_twice_in_one_row_counts_once():
    g = build_graph([row("1", DANA, [ME, MARCUS, MARCUS])], ME, today=TODAY)
    dana = [n for n in g.nodes if n.id == DANA][0]
    assert dana.people_given == 1


def test_a_chain_records_who_the_introducee_went_on_to_introduce():
    rows = [row("1", DANA, [ME, MARCUS]),
            row("2", MARCUS, [ME, CARA], d="2026-02-01")]
    g = build_graph(rows, ME, today=TODAY)
    link = [c for c in g.chains if c.introducer == DANA and c.introduced == MARCUS]
    assert len(link) == 1
    assert link[0].onward == (CARA,)


def test_an_introducee_who_introduced_nobody_has_an_empty_onward():
    g = build_graph([row("1", DANA, [ME, MARCUS])], ME, today=TODAY)
    link = [c for c in g.chains if c.introduced == MARCUS][0]
    assert link.onward == ()


def test_no_onward_link_without_a_detected_row_supporting_it():
    """Never present an inference as a verified fact. Dana -> Marcus and
    Cara -> Nils are two unconnected facts; nothing joins them."""
    rows = [row("1", DANA, [ME, MARCUS]), row("2", CARA, [ME, NILS])]
    g = build_graph(rows, ME, today=TODAY)
    assert all(c.onward == () for c in g.chains)


def test_outbound_rows_never_produce_a_chain():
    rows = [row("1", ME, [DANA, MARCUS], direction="outbound"),
            row("2", MARCUS, [DANA, CARA], direction="outbound")]
    g = build_graph(rows, ME, today=TODAY)
    assert g.chains == []


def test_the_principal_appears_in_no_chain():
    rows = [row("1", DANA, [ME, MARCUS]), row("2", MARCUS, [ME, CARA])]
    g = build_graph(rows, ME, today=TODAY)
    for c in g.chains:
        assert ME not in (c.introducer, c.introduced)
        assert ME not in c.onward


def test_a_connector_never_chains_to_themselves():
    rows = [row("1", DANA, [ME, MARCUS]), row("2", MARCUS, [ME, DANA])]
    g = build_graph(rows, ME, today=TODAY)
    assert all(c.introducer != c.introduced for c in g.chains)


def test_chain_starters_are_ordered_by_how_far_the_chain_carried():
    rows = [row("1", DANA, [ME, MARCUS]),
            row("2", MARCUS, [ME, CARA]), row("3", MARCUS, [ME, NILS]),
            row("4", CARA, [ME, "z@fifthco.io"])]
    g = build_graph(rows, ME, today=TODAY)
    assert chain_starters(g)[0] == DANA


def test_someone_with_no_carrying_introducee_is_not_a_chain_starter():
    g = build_graph([row("1", DANA, [ME, MARCUS])], ME, today=TODAY)
    assert chain_starters(g) == []


def test_an_onward_link_must_come_after_the_introduction_that_caused_it():
    """The page says "went on to introduce you onward". A third of the links
    on the real corpus ran backwards in time because nothing checked."""
    rows = [row("1", DANA, [ME, MARCUS], d="2026-05-01"),
            row("2", MARCUS, [ME, CARA], d="2026-02-01")]   # earlier
    g = build_graph(rows, ME, today=TODAY)
    link = [c for c in g.chains if c.introducer == DANA and c.introduced == MARCUS][0]
    assert link.onward == ()


def test_an_onward_link_on_the_same_day_is_kept():
    rows = [row("1", DANA, [ME, MARCUS], d="2026-05-01"),
            row("2", MARCUS, [ME, CARA], d="2026-05-01")]
    g = build_graph(rows, ME, today=TODAY)
    link = [c for c in g.chains if c.introducer == DANA and c.introduced == MARCUS][0]
    assert link.onward == (CARA,)


def test_an_onward_link_with_no_date_is_dropped_not_guessed():
    rows = [row("1", DANA, [ME, MARCUS], d="2026-05-01"),
            row("2", MARCUS, [ME, CARA], d="")]
    g = build_graph(rows, ME, today=TODAY)
    link = [c for c in g.chains if c.introducer == DANA and c.introduced == MARCUS][0]
    assert link.onward == ()


def test_a_spurious_chain_starter_disappears_once_time_is_checked():
    """Three real chain starters were entirely spurious."""
    rows = [row("1", DANA, [ME, MARCUS], d="2026-05-01"),
            row("2", MARCUS, [ME, CARA], d="2026-02-01")]
    g = build_graph(rows, ME, today=TODAY)
    assert chain_starters(g) == []


def test_a_row_naming_the_principal_as_introducer_produces_no_chain():
    """Detection can misfire. If a row claims the principal introduced
    someone to themselves, that must not become 'you introduced you to N
    people' in the chain panel."""
    rows = [row("1", ME, [MARCUS, CARA]),
            row("2", MARCUS, [ME, NILS])]
    g = build_graph(rows, ME, today=TODAY)
    assert all(c.introducer != ME for c in g.chains)
    assert all(ME not in c.onward for c in g.chains)
    assert ME not in chain_starters(g)


def test_the_earliest_date_for_a_pair_is_the_one_that_counts():
    """Two rows introduce the same pair on different dates. The earliest is
    when the chain could first have started; using the latest would spuriously
    drop valid onward links. Flipping the comparison leaves the rest of the
    suite green, which is why this test exists."""
    rows = [row("1", DANA, [ME, MARCUS], d="2026-05-01"),
            row("2", DANA, [ME, MARCUS], d="2026-01-01"),
            row("3", MARCUS, [ME, CARA], d="2026-03-01")]
    g = build_graph(rows, ME, today=TODAY)
    link = [c for c in g.chains
            if c.introducer == DANA and c.introduced == MARCUS][0]
    assert link.onward == (CARA,)
