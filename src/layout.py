"""Where each node sits, computed here rather than left to physics.

A force simulation over five hundred nodes settles into a hairball: everything
is equidistant from everything, and the one structure worth seeing — who
introduced whom — is the first thing lost. The CRM's own renderer solved this
years ago by computing positions in Python, and this is that approach ported.

The arrangement: every major connector becomes a **satellite** with the people
they introduced orbiting them, and the satellites are spread around a ring so
they do not overlap. Someone introduced by nobody prominent falls into a
trailing group. The result reads as "these are the worlds you were let into,
and who let you in", which a free layout cannot express.

Within a satellite, members are placed on a golden-angle spiral — the
phyllotaxis arrangement leaves no gaps and no spokes at any member count, which
a naive circle does as soon as two satellites differ in size.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

GOLDEN = 2.399963229728653      # golden angle in radians
STEP = 34                       # spacing between orbiting members
MIN_RING = 520.0                # keeps small graphs from collapsing inward
OTHER = "—"                # the trailing group's key


def member_offsets(count: int) -> list:
    """Golden-angle spiral offsets for `count` members around a centre."""
    return [(STEP * math.sqrt(k) * math.cos(k * GOLDEN),
             STEP * math.sqrt(k) * math.sin(k * GOLDEN))
            for k in range(count)]


def assign_satellites(
    edges: Sequence, hubs: Sequence, hidden: frozenset = frozenset()
) -> dict:
    """node id -> satellite key.

    A person belongs to the hub that introduced them. Introduced by two hubs,
    they belong to the earlier edge — arbitrary but stable, and stability is
    what stops the picture rearranging itself between runs. Everyone else,
    hubs included when they were never introduced by another hub, is placed in
    their own satellite or the trailing group.
    """
    hub_set = {h for h in hubs if h not in hidden}
    where: dict = {h: h for h in hub_set}
    for e in edges:
        if e.src in hidden or e.dst in hidden:
            continue
        if e.src in hub_set and e.dst not in where:
            where[e.dst] = e.src
    return where


def positions(
    node_ids: Sequence, where: Mapping, hidden: frozenset = frozenset()
) -> dict:
    """node id -> (x, y). Deterministic: same input, same picture."""
    members: dict = {}
    for nid in node_ids:
        if nid in hidden:
            continue
        members.setdefault(where.get(nid, OTHER), []).append(nid)
    if not members:
        return {}

    # Hub satellites in descending size, then the trailing group last, so the
    # ring order does not shuffle when one satellite gains a member.
    keys = sorted((k for k in members if k != OTHER),
                  key=lambda k: (-len(members[k]), str(k)))
    if OTHER in members:
        keys.append(OTHER)

    radius = {k: STEP * math.sqrt(max(len(members[k]) - 1, 0)) for k in keys}
    n = len(keys)
    if n == 1:
        ring = 0.0
    else:
        # Wide enough that neighbouring satellites cannot overlap.
        widest = max(radius.values()) if radius else 0.0
        ring = max(MIN_RING, (2.4 * widest) / (2 * math.sin(math.pi / n)))

    out: dict = {}
    for i, k in enumerate(keys):
        ang = 2 * math.pi * i / n - math.pi / 2
        cx, cy = ring * math.cos(ang), ring * math.sin(ang)
        ordered = sorted(members[k], key=lambda x: (x != k, str(x)))
        for nid, (ox, oy) in zip(ordered, member_offsets(len(ordered))):
            out[nid] = (cx + ox, cy + oy)
    return out
