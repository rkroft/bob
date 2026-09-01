"""Where each node sits on the connector ring — numbers in, numbers out.

No HTML here on purpose. "No two nodes overlap" should be an assertion about
coordinates rather than a screenshot, and the geometry is the part most likely
to be wrong. Follows the precedent `layout.py` set for the force-directed view.

Spec: docs/superpowers/specs/2026-08-21-connector-ring-design.md §3, §4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

VIEW_W = 1000          # wider than tall: the label gutters live inside the
VIEW_H = 760           # box, so a pushed label can never leave the picture
CX = 500.0
CY = 380.0
R_OUT = 300.0          # the rim: people who introduced you to exactly one
R_IN = 62.0            # the heaviest connector
GOLDEN = 0.6180339887
DOT_PITCH = 6.5        # arc between adjacent introducee dots
DOT_R = 2.5            # an introducee dot's own radius, drawn by render_ring


@dataclass(frozen=True)
class RingEntry:
    id: str
    label: str
    count: int             # DISTINCT people introduced (Node.people_given)
    is_service: bool = False
    is_chain_starter: bool = False


@dataclass(frozen=True)
class Placed:
    id: str
    label: str
    count: int
    is_service: bool
    is_chain_starter: bool
    angle: float
    rad: float
    r: float
    band_size: int

    @property
    def x(self) -> float:
        return CX + self.rad * math.cos(self.angle)

    @property
    def y(self) -> float:
        return CY + self.rad * math.sin(self.angle)


def ring_radius(count: int, hi: int) -> float:
    """Linear in the count itself, so a gap in the distribution is drawn as a
    gap. A sqrt or log scale would buy a busier middle by understating a real
    discontinuity — see the spec's decision table."""
    if hi <= 1:
        return R_OUT
    return R_OUT - (count - 1) / (hi - 1) * (R_OUT - R_IN)


def node_radius(count: int, band_size: int) -> float:
    """The rim degrades, it does not break: a one-timer's mark shrinks to fit
    the arc it actually has, down to a 1.4px stipple, rather than piling up."""
    if count == 1:
        arc = 2 * math.pi * R_OUT / max(band_size, 1)
        return max(1.4, min(3.6, arc / 2.6))
    return 4.4 + 2.7 * math.sqrt(count)


def place_ring(entries: Sequence[RingEntry]) -> list:
    """One ring per distinct count, ascending outward."""
    if not entries:
        return []
    hi = max(e.count for e in entries)
    counts = sorted({e.count for e in entries})
    placed = []
    for band_index, k in enumerate(counts):
        band = [e for e in entries if e.count == k]
        band.sort(key=lambda e: (e.label, e.id))     # stable across runs
        m = len(band)
        rad, r = ring_radius(k, hi), node_radius(k, m)
        # Each band gets its own start angle. Without this every band of one
        # starts at the same place -- and the bands of one are exactly the
        # heaviest connectors, so they stack into a vertical column.
        phase = (band_index * GOLDEN) % 1.0
        for j, e in enumerate(band):
            angle = ((j / m) + phase) * 2 * math.pi - math.pi / 2
            placed.append(Placed(id=e.id, label=e.label, count=e.count,
                                 is_service=e.is_service,
                                 is_chain_starter=e.is_chain_starter,
                                 angle=angle, rad=rad, r=r, band_size=m))
    return placed


def fan_offsets(p: Placed) -> list:
    """The people this connector introduced, as dots along their own ring.

    They used to fan out BEHIND the node, one ring further out. That could not
    work: the rings are 18.3px apart on the real distribution and the node
    discs eat 16-29px of that, so six of the nine bands had no corridor at all
    and 47 of 182 dots were drawn on top of somebody else's node -- 21 of them
    count-2 dots landing on the rim. Inward is no better; the gap is the same
    gap. So the dots run along the connector's own ring instead, into the free
    arc either side of it, where a dot is always exactly as far from the next
    band as its own node is and cross-band collision cannot arise.

    The arc is the roomy dimension: the tightest real band is 27 nodes at
    count 2, which has ~49px of free arc per node and needs 13px.
    """
    k = p.count
    if k < 2:
        return []
    slot = 2 * math.pi / max(p.band_size, 1)
    half = 0.375 * slot                       # 0.75 of the slot, split each side
    clear = (p.r + DOT_R + 2.0) / p.rad       # the first dot clears our own disc
    per_side = (k + 1) // 2
    pitch = DOT_PITCH / p.rad
    if per_side > 1:
        # Never widen past the slot. On a band so crowded that even this is
        # negative the dots compress onto each other -- a smudge on the right
        # connector, rather than a clean dot on the wrong one.
        pitch = min(pitch, max(half - clear, 0.0) / (per_side - 1))
    out = []
    for j in range(k):
        side = -1 if j % 2 == 0 else 1
        a = p.angle + side * (clear + (j // 2) * pitch)
        out.append((CX + p.rad * math.cos(a), CY + p.rad * math.sin(a)))
    return out



LABEL_MIN = 4          # only connectors at or above this are labelled
LABEL_GAP = 15.0       # minimum vertical separation, same side
LABEL_H = 14.0         # label box height, for clearance tests
LABEL_PAD = 3.0        # breathing room around a label box
CHAR_W = 6.2           # approximate advance at 11.5px/600
MAX_SHOVES = 60        # bound on the x-clearance loop


@dataclass
class Label:
    placed: Placed
    x: float
    y: float
    left: bool
    x0: float
    y0: float
    # True when the shove loop ran out of room -- either MAX_SHOVES was
    # exhausted while the label still overlapped a node, or the label was
    # pinned against the view's edge before it cleared. A label that vanishes
    # off the box without a word is the silent-failure class this repo has
    # already been bitten by; this field makes the condition observable
    # instead. The label still renders -- it is not dropped.
    crowded: bool = False

    @property
    def moved(self) -> bool:
        return abs(self.x - self.x0) > 3 or abs(self.y - self.y0) > 3


def _clears(x0, x1, y0, y1, c: Placed) -> bool:
    """Is the box entirely outside node `c`'s disc?"""
    nx = min(max(c.x, x0), x1)
    ny = min(max(c.y, y0), y1)
    return (nx - c.x) ** 2 + (ny - c.y) ** 2 >= c.r ** 2


def place_labels(placed: Sequence[Placed], min_count: int = LABEL_MIN) -> list:
    """Anchor by side, pack in y, then clear nodes in x.

    Labels on a circle deconflict in ONE dimension. Pushing a colliding label
    outward along its own radius also moves it in y, into its next neighbour,
    and does not converge. Packing y is a one-dimensional interval problem:
    sort, push each label down to clear its predecessor, done in one pass.

    x is then free, so node clearance can run in x alone without ever
    reintroducing a y collision. The two passes compose rather than fight.
    """
    labels = []
    for p in placed:
        if p.count < min_count:
            continue
        lr = p.rad + p.r + 14 + (6 if p.is_chain_starter else 0)
        x = CX + lr * math.cos(p.angle)
        y = CY + lr * math.sin(p.angle)
        labels.append(Label(placed=p, x=x, y=y,
                            left=math.cos(p.angle) < 0, x0=x, y0=y))

    for side in (True, False):
        grp = sorted([l for l in labels if l.left is side], key=lambda l: l.y)
        if not grp:
            continue
        # centre the packed run on the run it replaces, so a crowded side does
        # not drift downward off the picture
        need = LABEL_GAP * (len(grp) - 1)
        span = grp[-1].y - grp[0].y
        if span < need:
            grp[0].y -= (need - span) / 2
        for i in range(1, len(grp)):
            grp[i].y = max(grp[i].y, grp[i - 1].y + LABEL_GAP)

    for l in labels:
        w = len(l.placed.label) * CHAR_W
        # A left label's box is [x-w-PAD, x-PAD]; a shove moves x DOWN, which
        # risks x0 < LABEL_PAD. A right label's box is [x-PAD, x+w+PAD]; a
        # shove moves x UP, which risks x1 > VIEW_W - LABEL_PAD. These are the
        # farthest each side may go and still keep the box in view.
        min_x = w + 2 * LABEL_PAD
        max_x = VIEW_W - w - 2 * LABEL_PAD
        for _ in range(MAX_SHOVES):
            x0 = l.x - w - LABEL_PAD if l.left else l.x - LABEL_PAD
            x1 = x0 + w + 2 * LABEL_PAD
            y0, y1 = l.y - LABEL_H / 2, l.y + LABEL_H / 2
            hit = next((c for c in placed
                        if c is not l.placed and not _clears(x0, x1, y0, y1, c)),
                       None)
            if hit is None:
                break
            step = (x1 - hit.x if l.left else hit.x - x0) + hit.r + LABEL_PAD
            new_x = l.x + (-step if l.left else step)
            clamped = max(min_x, new_x) if l.left else min(max_x, new_x)
            if clamped == l.x:
                # Already sitting on the wall and still overlapping: shoving
                # further would push the box out of view, so stop here rather
                # than do it. The label stays put, still touching the node.
                l.crowded = True
                break
            l.x = clamped
        else:
            # The bound ran out with the label still overlapping a node.
            l.crowded = True
    return labels


# --- the chain bracket ----------------------------------------------------
BRACKET_W = 824       # 940 less the 116px the retired "you" column held
# The connector starts where the retired "you" node used to sit. Every chain
# in a bracket begins at the principal by construction, and the bracket is
# already titled with the connector's name under a "the connector" header,
# so a drawn "you" restated that and spent a sixth of the width on it.
# Shifted left by 116 -- the width the "you" column held -- so the gaps the
# handoff drew (250 connector->introducee, 300 introducee->onward) survive
# intact and the bracket gets narrower instead of emptier.
X_CONN, X_KID, X_ON = 34.0, 284.0, 584.0
SLOT = 26.0            # the handoff's 32 makes the tallest real chain 908px
KID_LABEL_W = 7.2      # per character, for clearing a name with the elbow


@dataclass(frozen=True)
class BracketNode:
    id: str
    label: str
    kind: str          # "connector" | "introduced" | "onward"
    x: float
    y: float
    carried: bool = False
    is_service: bool = False


@dataclass(frozen=True)
class Elbow:
    kind: str          # "kid" | "onward"
    points: tuple      # (x, y) pairs joined by straight segments


@dataclass(frozen=True)
class Bracket:
    connector: str
    height: float
    nodes: tuple
    elbows: tuple
    reach: int         # distinct people the chain reaches
    carried: int       # introducees who carried it onward
    kids: int          # people this connector introduced


def bracket_layout(connector: str, connector_label: str, chains,
                   label_of: dict, is_service=frozenset()) -> Bracket:
    """connector -> who they introduced -> who those went on to introduce.

    Slot arithmetic: every onward person takes a slot, and a childless
    introducee takes one. A row is never dropped and the bracket is never
    capped -- a bracket that hid rows would repeat the silent-truncation
    failure this repo has already been bitten by.
    """
    mine = [c for c in chains if c.introducer == connector]
    # carriers first: the informative rows belong at the top
    mine.sort(key=lambda c: (not c.onward, label_of.get(c.introduced, c.introduced)))

    nodes, elbows = [], []
    slot = 0
    kid_ys = []
    for c in mine:
        onward = list(c.onward)
        if onward:
            ys = []
            for addr in onward:
                ys.append(22 + slot * SLOT)
                slot += 1
        else:
            ys = [22 + slot * SLOT]
            slot += 1
        y_kid = sum(ys) / len(ys)
        kid_ys.append(y_kid)
        kid_label = label_of.get(c.introduced, c.introduced)
        nodes.append(BracketNode(id=c.introduced, label=kid_label,
                                 kind="introduced", x=X_KID, y=y_kid,
                                 carried=bool(onward),
                                 is_service=c.introduced in is_service))
        if onward:
            # Clamp so a very long name cannot push the elbow out of the drawing.
            # Crossing the text is worse than nothing; vanishing off the edge is
            # worse than crossing.
            start = min(X_KID + len(kid_label) * KID_LABEL_W + 30, X_ON - 20)
            mid2 = max(start + 20, (start + X_ON) / 2)
            for addr, y_on in zip(onward, ys):
                nodes.append(BracketNode(id=addr,
                                         label=label_of.get(addr, addr),
                                         kind="onward", x=X_ON, y=y_on,
                                         is_service=addr in is_service))
                elbows.append(Elbow("onward", ((start, y_kid), (mid2, y_kid),
                                               (mid2, y_on), (X_ON, y_on))))

    y_conn = sum(kid_ys) / len(kid_ys) if kid_ys else 22.0
    mid = (X_CONN + X_KID) / 2
    for y_kid in kid_ys:
        elbows.append(Elbow("kid", ((X_CONN, y_conn), (mid, y_conn),
                                    (mid, y_kid), (X_KID, y_kid))))
    nodes.append(BracketNode(id=connector, label=connector_label,
                             kind="connector", x=X_CONN, y=y_conn,
                             is_service=connector in is_service))

    carried = sum(1 for c in mine if c.onward)
    reach = len({c.introduced for c in mine}
                | {a for c in mine for a in c.onward})
    return Bracket(connector=connector,
                   height=max(220.0, 44 + slot * SLOT),
                   nodes=tuple(nodes), elbows=tuple(elbows),
                   reach=reach, carried=carried, kids=len(mine))
