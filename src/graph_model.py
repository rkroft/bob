"""intros.csv -> the things a picture and a summary need.

Reads the CSV and nothing else. No mailbox, no network. That separation is what
lets the graph be redrawn without a rescan.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

from intro_store import IntroRow


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    given: int         # introductions this person made for the principal
    received: int      # times this person was introduced
    # Distinct people they introduced the principal to, inbound only. `given`
    # counts rows; one thread introducing two people is one row and two people.
    # The ring is drawn from this one, because a node labelled "13" sits beside
    # a sentence reading "introduced you to 13 people". Defaults to 0 so every
    # existing positional Node(...) keeps working.
    people_given: int = 0


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    # "inbound" (someone introduced the principal to dst) or "outbound" (the
    # principal made this introduction). The picture colours by it; without it
    # every edge looked alike and the graph said less than the data knew.
    direction: str = ""


@dataclass(frozen=True)
class Stats:
    intros: int
    people: int
    introducers: int
    introduced_to: int
    made_by_you: int
    first_date: str
    last_date: str
    last_12mo: int


@dataclass(frozen=True)
class Chain:
    """One introducer -> one person they introduced -> who that person then
    introduced the principal to.

    Inbound rows only, at BOTH degrees. On an outbound row the principal is the
    introducer and `introduced` holds two people connected to each other, not
    people the principal met -- folding those in at the second degree would
    invent a chain that never happened.

    `onward` is also ordered in time: it holds only introductions that
    happened on or after the introduction that supposedly led to them, and
    drops any link where either date is unknown rather than assume an order
    that was never observed.
    """
    introducer: str
    introduced: str
    onward: tuple = ()


@dataclass(frozen=True)
class Hop:
    """One step back: `who` introduced the principal to the person being walked
    from, on `date`."""
    who: str
    date: str


@dataclass
class GraphData:
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    stats: Optional[Stats] = None
    super_connectors: list = field(default_factory=list)
    # Every introducer, most intros first. `super_connectors` answers "how
    # concentrated is this network"; this answers "who introduced you to the
    # most people". Related, but not the same question — and the second is the
    # one worth printing.
    top_connectors: list = field(default_factory=list)
    chains: list = field(default_factory=list)
    # person -> (the introducer who brought them in, that introduction's date).
    # The *earliest* introduction, because that is how the principal came to
    # know them; a later re-introduction is not an origin. Walked by
    # `provenance()`.
    origins: dict = field(default_factory=dict)


def _label(addr: str) -> str:
    """A readable name from an address. Nothing clever — the roster will carry
    real names later; this only has to be legible on a node."""
    local = addr.partition("@")[0]
    return " ".join(w.capitalize() for w in local.replace(".", " ").replace("_", " ").split())


SUPER_CONNECTOR_CAP = 8


def _super_connectors(inbound_counts: Counter) -> list:
    """The smallest set of INTRODUCERS accounting for half or more of the
    inbound introductions (Plugin MVP §4.5). Relative on purpose: a fixed
    threshold is empty for a normal mailbox and useless for a dense one.

    Introducers, not people. A recruiting inbox and an intro bot both earn a
    place here on real data, and they are real conduits — the introductions
    happened. What Bob cannot do is tell them from a founder using `hello@`,
    because the header that would settle it is stripped by the connector. So
    the set is honest about what it contains rather than filtered on a guess
    (HAP-319).

    Capped at SUPER_CONNECTOR_CAP regardless of whether half has been reached:
    on a flat distribution "smallest set reaching half" degenerates toward
    "everyone", which is not a super-connector list any more — a real mailbox
    produced 45 names, printed inline in both the terminal summary and the
    HTML header."""
    total = sum(inbound_counts.values())
    if not total:
        return []
    running, out = 0, []
    for addr, n in inbound_counts.most_common():
        out.append((addr, n))
        running += n
        if running * 2 >= total or len(out) >= SUPER_CONNECTOR_CAP:
            break
    return out


def build_graph(
    rows: Sequence[IntroRow],
    principal: str,
    today: Optional[date] = None,
    names: Optional[dict] = None,
) -> GraphData:
    today = today or date.today()
    names = names or {}
    principal = (principal or "").lower()

    given: Counter = Counter()
    received: Counter = Counter()
    inbound_by_introducer: Counter = Counter()
    # Who the principal was introduced TO, i.e. "introduced_to" in Stats.
    # Scoped to inbound rows only: on an outbound row the principal is the
    # introducer and `introduced` holds the two people they connected to each
    # other, not people the principal was introduced to. Folding those in
    # would mislabel them under a sentence that reads "people you were
    # introduced to" — a false statement, not just an inflated count.
    inbound_introduced_to: set = set()
    # addr -> the distinct people they introduced the principal to
    introduced_by: dict = {}
    # (introducer, person) -> the earliest ISO date any detected row put that
    # introduction on, or "" if every row that produced it was dateless. The
    # onward step below needs this: "later" only means something if both ends
    # of the comparison have a real date.
    introduced_by_date: dict = {}
    people: set = set()
    edges: list = []

    for r in rows:
        if r.introducer:
            people.add(r.introducer)
            given[r.introducer] += 1
            if r.direction == "inbound":
                inbound_by_introducer[r.introducer] += 1
        for p in r.introduced:
            people.add(p)
            received[p] += 1
            if r.introducer:
                edges.append(Edge(src=r.introducer, dst=p,
                                  direction=r.direction))
            if r.direction == "inbound":
                inbound_introduced_to.add(p)
            if r.direction == "inbound" and r.introducer \
                    and r.introducer != principal \
                    and p != principal and p != r.introducer:
                introduced_by.setdefault(r.introducer, set()).add(p)
                key = (r.introducer, p)
                if r.date:
                    cur = introduced_by_date.get(key, "")
                    if not cur or r.date < cur:
                        introduced_by_date[key] = r.date
                else:
                    introduced_by_date.setdefault(key, "")

    # A real display name from the headers always beats one derived from the
    # local part: "Marcus Lee" rather than "Mlee".
    nodes = [Node(id=a, label=(names.get(a) or "").strip() or _label(a),
                  given=given[a], received=received[a],
                  people_given=len(introduced_by.get(a, ())))
             for a in sorted(people)]

    dates = sorted(r.date for r in rows if r.date)
    cutoff = (today - timedelta(days=365)).isoformat()
    stats = Stats(
        intros=len(rows),
        people=len(people),
        introducers=len([a for a in inbound_by_introducer if a != principal]),
        introduced_to=len([a for a in inbound_introduced_to if a != principal]),
        made_by_you=sum(1 for r in rows if r.direction == "outbound"),
        first_date=dates[0] if dates else "",
        last_date=dates[-1] if dates else "",
        last_12mo=sum(1 for r in rows if r.date and r.date >= cutoff),
    )

    # The onward step. Drawn only where a detected row supports it: no
    # transitive closure, no "probably" -- and, as important, no "sequence"
    # without evidence of sequence. An onward link from B to C only belongs on
    # A->B's chain if B->C happened on or after A->B: the page says "went on
    # to introduce you onward", and that word is a claim about time, not just
    # about which rows exist. If either introduction's date is unknown the
    # ordering is unverifiable, and an unverifiable ordering is dropped rather
    # than guessed -- never present an inference as a verified fact.
    chains = []
    for introducer in sorted(introduced_by):
        for person in sorted(introduced_by[introducer]):
            a_date = introduced_by_date.get((introducer, person), "")
            onward = tuple(
                c for c in sorted(introduced_by.get(person, ()))
                if a_date and introduced_by_date.get((person, c), "")
                and introduced_by_date[(person, c)] >= a_date
            )
            chains.append(Chain(introducer=introducer, introduced=person,
                                onward=onward))

    # The same edges read backwards. `introduced_by_date` holds the earliest
    # date per (introducer, person); this reduces it to one origin per person,
    # preferring the earliest *dated* introduction. An undated one is kept only
    # when there is nothing dated, so it can be reported as an origin whose
    # ordering `provenance()` will refuse to walk past.
    origins: dict = {}

    def _rank(introducer: str, when: str) -> tuple:
        # Earliest first, then the introducer for a stable tie-break. An
        # undated candidate sorts last via the sentinel, which is why a dated
        # introduction always wins -- no date is a real one. Ranking every
        # candidate the same way, including the undated ones (which previously
        # kept whichever row arrived first), makes the result independent of
        # the order rows were read in.
        return (when or "9999-99-99", introducer)

    for (introducer, person), when in introduced_by_date.items():
        held = origins.get(person)
        if held is None or _rank(introducer, when) < _rank(*held):
            origins[person] = (introducer, when)

    return GraphData(
        nodes=nodes, edges=edges, stats=stats,
        super_connectors=_super_connectors(inbound_by_introducer),
        top_connectors=inbound_by_introducer.most_common(),
        chains=chains,
        origins=origins,
    )


def chain_starters(graph) -> list:
    """Introducers with at least one introducee who carried the chain onward,
    most onward first.

    Counted over EVERY introducer, not only repeat connectors: the ring draws
    the one-time introducers too, and five of them start chains on the corpus
    this was measured against.
    """
    reach = {}
    for c in graph.chains:
        if not c.onward:
            continue
        agg = reach.setdefault(c.introducer, [0, 0])
        agg[0] += 1                 # introducees who carried it
        agg[1] += len(c.onward)     # people the onward step added
    return [a for a, _ in sorted(reach.items(),
                                 key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))]


def provenance(graph, person: str) -> tuple:
    """Where a person came from — the chain walked backwards, most recent hop
    first.

    `chain_starters` asks what an introducer's introduction *reached*. This
    asks the question a user actually asks about a specific person: *how do I
    know them?* Same edges, opposite direction.

    Two rules, inherited from `Chain` and for the same reason — an origin is a
    claim about cause, and cause is a claim about time:

    **Every hop must have happened on or before the introduction it caused.**
    If Eva introduced you to Terry in February but Leo only introduced you to
    Eva in June, then Leo is not why you know Terry, whatever the rows say --
    the walk stops. Same day is allowed, mirroring `Chain`'s forward "on or
    after": a shared date is not evidence against causation.

    **The first hop is a fact; every hop after it is a causal claim.** "Dana
    introduced you" is true whether or not the date survived, so an undated
    first hop is still reported. But an undated hop cannot be ordered against
    the one before it, so the walk stops there rather than asserting an
    ancestry it cannot verify. This is also why `origins` and this function
    agree on *whether* a person has a known origin, and differ only on how far
    back the chain can honestly be traced.

    One hop is the common case and a complete answer on its own — *"Dana
    introduced you, March 2019."* The deep path is the surprise, not the format.
    """
    path: list = []
    seen = {person}
    current, caused_on = person, ""
    while True:
        origin = graph.origins.get(current)
        if origin is None:
            return tuple(path)
        who, when = origin
        # A loop, or an introducer who arrived after the introduction they
        # supposedly caused: stop rather than assert. The cycle guard is not
        # redundant with the date rule -- equal dates satisfy the date rule
        # forever, so a same-day mutual introduction loops without it.
        # `caused_on` is empty only on the first hop, which is a plain fact and
        # needs no ordering. Every hop after it is a causal claim, so it must be
        # dated AND fall on or before the introduction it caused -- an undated
        # one is dropped rather than asserted.
        if who in seen or (caused_on and (not when or when > caused_on)):
            return tuple(path)
        path.append(Hop(who=who, date=when))
        # An undated first hop is reportable but not orderable: nothing before
        # it can be placed in time, so the walk ends here.
        if not when:
            return tuple(path)
        seen.add(who)
        current, caused_on = who, when
