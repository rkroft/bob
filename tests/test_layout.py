"""Layout. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from graph_model import Edge  # noqa: E402
from layout import OTHER, assign_satellites, member_offsets, positions  # noqa: E402

DANA, MARCUS, ME = "dana@x.test", "marcus@x.test", "me@x.test"
A, B, C = "a@x.test", "b@x.test", "c@x.test"


def test_members_orbit_the_hub_that_introduced_them():
    where = assign_satellites([Edge(DANA, A), Edge(DANA, B)], [DANA])
    assert where[A] == DANA and where[B] == DANA


def test_a_hub_belongs_to_its_own_satellite():
    assert assign_satellites([Edge(DANA, A)], [DANA])[DANA] == DANA


def test_someone_introduced_by_nobody_prominent_falls_to_the_trailing_group():
    where = assign_satellites([Edge(DANA, A)], [DANA])
    assert positions([A, C], where)  # does not raise
    assert where.get(C) is None      # -> OTHER at layout time


def test_hidden_nodes_are_never_placed():
    where = assign_satellites([Edge(DANA, ME)], [DANA], hidden=frozenset({ME}))
    assert ME not in positions([DANA, ME], where, hidden=frozenset({ME}))


def test_two_satellites_do_not_overlap():
    where = assign_satellites(
        [Edge(DANA, A), Edge(DANA, B), Edge(MARCUS, C)], [DANA, MARCUS])
    pos = positions([DANA, MARCUS, A, B, C], where)
    import math
    d = math.dist(pos[DANA], pos[MARCUS])
    assert d > 400, d


def test_layout_is_deterministic():
    where = assign_satellites([Edge(DANA, A), Edge(DANA, B)], [DANA])
    assert positions([DANA, A, B], where) == positions([DANA, A, B], where)


def test_member_offsets_never_repeat_a_point():
    pts = member_offsets(60)
    assert len(set(pts)) == 60


def test_an_empty_graph_lays_out_to_nothing():
    assert positions([], {}) == {}


def test_a_single_satellite_sits_at_the_origin():
    where = assign_satellites([Edge(DANA, A)], [DANA])
    pos = positions([DANA, A], where)
    assert pos[DANA] == (0.0, 0.0)
