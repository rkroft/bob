"""Ring geometry. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ring_layout import (  # noqa: E402
    CX as CENTRE_X, CY as CENTRE_Y, DOT_R, R_IN, R_OUT, RingEntry, fan_offsets,
    node_radius, place_ring, ring_radius, LABEL_GAP, LABEL_MIN, place_labels,
    BRACKET_W, SLOT, X_CONN, X_KID, X_ON, bracket_layout,
)


def entries(spec):
    """spec is {count: how_many}. Names are generated, never real."""
    out, n = [], 0
    for count, many in sorted(spec.items(), reverse=True):
        for _ in range(many):
            n += 1
            out.append(RingEntry(id="p%d@example.com" % n, label="Person %d" % n,
                                 count=count, is_service=False,
                                 is_chain_starter=False))
    return out


REAL = {14: 1, 13: 1, 10: 1, 6: 1, 5: 4, 4: 8, 3: 11, 2: 27, 1: 115}


def test_radius_is_monotone_non_increasing_in_count():
    hi = 14
    radii = [ring_radius(k, hi) for k in range(1, 15)]
    assert radii == sorted(radii, reverse=True)
    assert radii[0] == R_OUT      # count == 1 sits on the rim
    assert radii[-1] == R_IN      # the heaviest connector sits innermost


def test_every_introducer_is_placed():
    e = entries(REAL)
    placed = place_ring(e)
    assert len(placed) == len(e) == 169


def test_no_two_nodes_overlap_on_the_real_distribution():
    placed = place_ring(entries(REAL))
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            d = math.hypot(a.x - b.x, a.y - b.y)
            assert d >= a.r + b.r, "%s and %s overlap" % (a.label, b.label)


def test_no_two_nodes_overlap_with_four_hundred_one_timers():
    """The rim degrades to a stipple rather than piling up."""
    placed = place_ring(entries({400: 0, 3: 2, 1: 400}))
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            assert math.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r


def test_bands_of_one_do_not_share_an_angle():
    """DO NOT 'simplify' the golden-ratio phase away. Without it every band of
    one member starts at the same angle -- and the bands of one are exactly the
    heaviest connectors, so the four most important nodes stack into a vertical
    column with their labels on top of each other. Observed, not predicted."""
    placed = place_ring(entries({14: 1, 13: 1, 10: 1, 6: 1, 2: 4}))
    singles = [p.angle for p in placed if p.count in (14, 13, 10, 6)]
    assert len(set(round(a, 6) for a in singles)) == 4


def test_a_flat_mailbox_places_everyone_on_the_rim():
    """hi == 1 makes the radius interpolation divide by zero."""
    placed = place_ring(entries({1: 12}))
    assert all(p.rad == R_OUT for p in placed)


def test_no_introducers_returns_an_empty_layout():
    assert place_ring([]) == []


def test_a_single_introducer_does_not_raise():
    placed = place_ring(entries({5: 1}))
    assert len(placed) == 1


def test_service_and_chain_starter_survive_placement():
    e = [RingEntry("svc@example.com", "A Service", 3, True, True)]
    p = place_ring(e)[0]
    assert p.is_service and p.is_chain_starter


def test_the_rim_gets_no_fan():
    placed = place_ring(entries({3: 2, 1: 40}))
    rim = [p for p in placed if p.count == 1]
    assert all(fan_offsets(p) == [] for p in rim)


def test_one_dot_per_person_introduced():
    p = place_ring(entries({5: 1}))[0]
    assert len(fan_offsets(p)) == 5


def test_no_introducee_dot_lands_on_another_connector():
    """The fan used to sit BEHIND the node, one ring further out. It could not:
    the rings are 18.3px apart on the real distribution and the node discs eat
    16-29px of that, so six of nine bands had no corridor at all and 47 of 182
    dots were drawn on top of somebody else's node -- 21 of them count-2 dots
    landing on the rim. The fan now runs along the connector's own ring, in the
    free arc beside it, where cross-band collision cannot happen at all."""
    placed = place_ring(entries(REAL))
    for p in placed:
        for dx, dy in fan_offsets(p):
            for c in placed:
                if c.id == p.id:
                    continue
                d = math.hypot(dx - c.x, dy - c.y)
                assert d >= c.r + DOT_R, (
                    "a dot of %s sits on %s (%.2f < %.2f)"
                    % (p.label, c.label, d, c.r + DOT_R))


def test_a_dot_never_sits_on_its_own_node():
    for p in place_ring(entries(REAL)):
        for dx, dy in fan_offsets(p):
            assert math.hypot(dx - p.x, dy - p.y) >= p.r + DOT_R


def test_the_fan_does_not_collapse_into_a_striped_bar():
    """The handoff's fixed 0.30 spread cap assumed a node at radius 120-200; at
    R_IN there are about 28px of arc for fourteen dots. Every dot is now
    separately legible, so the check is over every pair rather than over
    alternating ones."""
    dots = fan_offsets(place_ring(entries({14: 1}))[0])
    gaps = [math.hypot(a[0] - b[0], a[1] - b[1])
            for i, a in enumerate(dots) for b in dots[i + 1:]]
    assert min(gaps) >= 5.0, "fan collapsed: %.2f" % min(gaps)


def test_the_fan_stays_inside_the_nodes_own_slot():
    """A wide fan on a crowded band would reach into its neighbours.

    The fixture was {4: 20}, which puts twenty discs on the innermost ring
    where they overlap each other by 0.2px: no fan can satisfy a bound the
    NODES already breach, so the test was asserting about a state place_ring
    cannot validly produce. This band is crowded and valid -- 26 nodes with
    9.8px discs in a 0.24 rad slot.
    """
    placed = place_ring(entries({20: 1, 4: 26}))
    p = [q for q in placed if q.count == 4][0]
    slot = 2 * math.pi / p.band_size
    spans = [math.atan2(y - CENTRE_Y, x - CENTRE_X) for x, y in fan_offsets(p)]
    width = max(spans) - min(spans)
    assert width <= 0.75 * slot + 1e-9


def boxes(labels):
    from ring_layout import CHAR_W, LABEL_H, LABEL_PAD
    for l in labels:
        w = len(l.placed.label) * CHAR_W
        x0 = l.x - w - LABEL_PAD if l.left else l.x - LABEL_PAD
        yield l, x0, x0 + w + 2 * LABEL_PAD, l.y - LABEL_H / 2, l.y + LABEL_H / 2


def test_only_the_heavier_connectors_are_labelled():
    placed = place_ring(entries(REAL))
    labels = place_labels(placed)
    assert {l.placed.count for l in labels} == {14, 13, 10, 6, 5, 4}
    assert len(labels) == 16


def test_no_two_labels_on_a_side_overlap():
    labels = place_labels(place_ring(entries(REAL)))
    for side in (True, False):
        ys = sorted(l.y for l in labels if l.left is side)
        for a, b in zip(ys, ys[1:]):
            assert b - a >= LABEL_GAP - 1e-9


def test_no_label_sits_on_a_node():
    placed = place_ring(entries(REAL))
    labels = place_labels(placed)
    for l, x0, x1, y0, y1 in boxes(labels):
        for c in placed:
            if c is l.placed:
                continue
            nx, ny = min(max(c.x, x0), x1), min(max(c.y, y0), y1)
            assert (nx - c.x) ** 2 + (ny - c.y) ** 2 >= c.r ** 2, \
                "%s sits on %s" % (l.placed.label, c.label)


def test_packing_in_y_is_one_pass_and_deterministic():
    """An earlier design pushed colliding labels outward along their own
    radius. It does not converge: moving a label outward also moves it in y,
    into its next neighbour. Twelve passes ended with MORE overlaps than the
    single pass it replaced. Do not reintroduce a radial sweep."""
    placed = place_ring(entries(REAL))
    a = [(l.placed.id, round(l.x, 6), round(l.y, 6)) for l in place_labels(placed)]
    b = [(l.placed.id, round(l.x, 6), round(l.y, 6)) for l in place_labels(placed)]
    assert a == b


def test_a_label_that_moved_is_marked_so_it_can_get_a_leader():
    labels = place_labels(place_ring(entries(REAL)))
    assert any(l.moved for l in labels)


def test_no_labels_when_nobody_clears_the_threshold():
    assert place_labels(place_ring(entries({2: 9, 1: 5}))) == []


def test_the_slot_bound_binds_when_the_arc_would_overrun_it():
    """The dots want more arc than the slot allows, so the slot term must be
    the one that binds. The neighbouring test uses an input where the arc term
    is already under the bound, so it would pass even if the cap were deleted.

    The fixture was {8: 40} -- forty 12px discs on the innermost ring, at 2.5x
    the angular width of their own slot. Like its neighbour it asserted about
    a layout place_ring cannot validly produce. Twenty nodes at count 6 crowd
    the cap for real: the arc wants 0.0274 rad per dot and the slot allows
    0.0262."""
    placed = place_ring(entries({20: 1, 6: 20}))
    p = [q for q in placed if q.count == 6][0]
    slot = 2 * math.pi / p.band_size
    spans = [math.atan2(y - CENTRE_Y, x - CENTRE_X) for x, y in fan_offsets(p)]
    width = max(spans) - min(spans)
    assert width <= 0.75 * slot + 1e-9
    assert abs(width - 0.75 * slot) < 1e-6, "the slot cap is not the binding term"


class FakeChain:
    """Stands in for graph_model.Chain so the geometry tests need no graph."""

    def __init__(self, introducer, introduced, onward=()):
        self.introducer = introducer
        self.introduced = introduced
        self.onward = tuple(onward)


NAMES = {"d@example.com": "Dana", "m@example.com": "Marcus",
         "c@example.com": "Cara", "n@example.com": "Nils",
         "z@example.com": "Zoe"}


def a_bracket():
    chains = [FakeChain("d@example.com", "m@example.com",
                        ["c@example.com", "n@example.com"]),
              FakeChain("d@example.com", "z@example.com")]
    return bracket_layout("d@example.com", "Dana", chains, NAMES)


def test_each_onward_person_takes_a_slot_and_a_childless_introducee_takes_one():
    b = a_bracket()
    # marcus contributes 2 (cara, nils); zoe contributes 1
    assert b.height == max(220, 44 + 3 * SLOT)


def test_a_connector_sits_at_the_mean_of_its_introducees():
    b = a_bracket()
    conn = [n for n in b.nodes if n.kind == "connector"][0]
    kids = [n for n in b.nodes if n.kind == "introduced"]
    assert abs(conn.y - sum(k.y for k in kids) / len(kids)) < 1e-9


def test_chain_carriers_come_first():
    b = a_bracket()
    kids = [n for n in b.nodes if n.kind == "introduced"]
    assert [k.label for k in kids] == ["Marcus", "Zoe"]
    assert kids[0].carried and not kids[1].carried


def test_every_onward_person_is_a_node():
    b = a_bracket()
    onward = sorted(n.label for n in b.nodes if n.kind == "onward")
    assert onward == ["Cara", "Nils"]


def test_the_bracket_does_not_draw_a_you_node():
    """Every bracket is one person's, opened from their own row, titled with
    their name, under a column header reading "the connector" -- and every
    chain in it starts from the principal by construction. A "you" node
    restated that four times over and spent a sixth of the bracket's width
    doing it. The connector is the leftmost thing now."""
    b = a_bracket()
    assert [n for n in b.nodes if n.kind == "you"] == []
    assert [e for e in b.elbows if e.kind == "you"] == []
    conn = [n for n in b.nodes if n.kind == "connector"][0]
    assert conn.x == min(n.x for n in b.nodes)


def test_the_columns_close_up_when_the_you_column_goes():
    """Moving the connector left without moving the columns to its right just
    widens the gutter -- which is what the first attempt did, and it looked
    worse than the node it removed. The whole bracket shifts by the width the
    "you" column used to hold, so every gap keeps the spacing it was drawn
    with and the picture gets narrower rather than emptier."""
    b = a_bracket()
    conn = [n for n in b.nodes if n.kind == "connector"][0]
    assert conn.x == X_CONN
    assert X_CONN < 60, "the connector should sit where you used to"
    # the three gaps the handoff drew: 250 connector->introducee,
    # 300 introducee->onward. Both survive the shift.
    assert X_KID - X_CONN == 250
    assert X_ON - X_KID == 300
    # and the canvas narrows by the retired column rather than keeping its width
    assert BRACKET_W == 824


def test_the_stat_strip_numbers_come_from_the_layout():
    b = a_bracket()
    assert b.kids == 2          # people this connector introduced
    assert b.carried == 1       # of those, how many carried the chain
    assert b.reach == 4         # 2 introducees + 2 onward, no double counting


def test_a_connector_with_no_chains_still_lays_out():
    b = bracket_layout("d@example.com", "Dana",
                       [FakeChain("d@example.com", "z@example.com")], NAMES)
    assert b.height == max(220, 44 + 1 * SLOT)
    assert b.carried == 0


def test_the_onward_elbow_starts_clear_of_the_introducees_label():
    """start = X_KID + len(name)*7.2 + 30, so the line never crosses the name."""
    b = a_bracket()
    onward_elbows = [e for e in b.elbows if e.kind == "onward"]
    assert onward_elbows
    for e in onward_elbows:
        assert e.points[0][0] > X_KID
        assert e.points[-1][0] == X_ON


def test_the_bracket_never_exceeds_its_own_width():
    b = a_bracket()
    assert all(n.x <= BRACKET_W for n in b.nodes)


def test_carriers_are_ordered_by_label_among_themselves():
    """Two carriers agree on the primary key, so only the label tie-break
    can order them. Without it the order would be input order."""
    chains = [FakeChain("d@example.com", "z@example.com", ["c@example.com"]),
              FakeChain("d@example.com", "m@example.com", ["n@example.com"])]
    b = bracket_layout("d@example.com", "Dana", chains, NAMES)
    kids = [n for n in b.nodes if n.kind == "introduced"]
    assert [k.label for k in kids] == ["Marcus", "Zoe"]


def test_a_connector_with_no_introducees_at_all_does_not_divide_by_zero():
    """`mine` is empty when no chain names this connector. The neighbouring
    test passes one chain, so it never reaches this path."""
    b = bracket_layout("d@example.com", "Dana", [], NAMES)
    assert b.height == 220.0
    assert b.kids == 0 and b.carried == 0 and b.reach == 0
    conn = [n for n in b.nodes if n.kind == "connector"][0]
    assert conn.y == 22.0


def test_a_long_name_cannot_push_an_elbow_out_of_the_drawing():
    """Node x's are constants and cannot catch this; the elbow start grows
    with the name. An unclamped start passes BRACKET_W at ~75 characters."""
    names = dict(NAMES)
    names["m@example.com"] = "M" * 90
    b = bracket_layout("d@example.com", "Dana",
                       [FakeChain("d@example.com", "m@example.com",
                                  ["c@example.com"])], names)
    xs = [x for e in b.elbows for x, _ in e.points]
    assert max(xs) <= BRACKET_W


def test_no_label_is_pushed_outside_the_view():
    """A label shoved past the box is invisible, which is a silent failure."""
    from ring_layout import CHAR_W, LABEL_PAD, VIEW_W
    labels = place_labels(place_ring(entries(REAL)))
    for l in labels:
        w = len(l.placed.label) * CHAR_W
        x0 = l.x - w - LABEL_PAD if l.left else l.x - LABEL_PAD
        assert x0 >= 0
        assert x0 + w + 2 * LABEL_PAD <= VIEW_W


def test_a_label_that_could_not_be_placed_clear_is_flagged():
    """`crowded` exists so the condition is observable. On the real
    distribution nothing should be crowded; the field must still be present
    and False rather than missing."""
    labels = place_labels(place_ring(entries(REAL)))
    assert all(hasattr(l, "crowded") for l in labels)
    assert not any(l.crowded for l in labels)


def _crowd_it():
    """One long-labelled count=10 node ringed tightly by ten short-labelled
    count=4 nodes -- close enough, with a label wide enough, that the shove
    loop genuinely cannot clear it. Unlike the REAL-distribution test above
    (where nothing is ever crowded, so a mutation deleting either safety
    mechanism leaves that test just as green), this input actually exercises
    both `crowded = True` writes and the in-view clamp: verified by mutation
    -- deleting both `crowded = True` assignments made the corresponding
    assertion below pass 0 crowded labels instead of >=1, and replacing the
    clamp with the raw unclamped shove pushed the box to x0 ~= -39, outside
    the view."""
    entries_ = [RingEntry(id="p1@example.com", label="X" * 50, count=10,
                          is_service=False, is_chain_starter=False)]
    entries_ += [RingEntry(id="p%d@example.com" % i, label="Person %d" % i,
                           count=4, is_service=False, is_chain_starter=False)
                for i in range(2, 12)]
    return place_labels(place_ring(entries_))


def test_a_label_that_genuinely_cannot_be_placed_clear_gets_flagged():
    """The REAL-distribution test never exercises `crowded = True` -- nothing
    on that corpus is actually crowded, so a mutation deleting both
    assignments still leaves it green. This input is constructed so the
    shove loop cannot clear the long label."""
    labels = _crowd_it()
    crowded = [l for l in labels if l.crowded]
    assert crowded, "expected at least one label to be flagged crowded"
    assert crowded[0].placed.id == "p1@example.com"


def test_the_crowded_label_still_stays_inside_the_view():
    """The in-view clamp (`ring_layout.py`'s `max(min_x, new_x)` /
    `min(max_x, new_x)`) is what stops the shove loop from pushing a
    genuinely crowded label's box past the edge of the picture. Without it,
    on this same input, the box's left edge lands at x0 ~= -39 -- off the
    1000-wide view and invisible."""
    from ring_layout import CHAR_W, LABEL_PAD, VIEW_W
    labels = _crowd_it()
    mine = [l for l in labels if l.placed.id == "p1@example.com"][0]
    assert mine.crowded
    w = len(mine.placed.label) * CHAR_W
    x0 = mine.x - w - LABEL_PAD if mine.left else mine.x - LABEL_PAD
    x1 = x0 + w + 2 * LABEL_PAD
    assert x0 >= 0
    assert x1 <= VIEW_W
