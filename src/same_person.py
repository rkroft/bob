"""One person, two addresses.

People introduce from a work address one year and a personal one the next, and
Bob ranked each address as its own introducer with a smaller count (measured
2026-09-21). The connector returns no display names, and names read from mail
text connected almost none of these pairs, so Bob cannot decide this alone.
It proposes pairs whose addresses look like one person, the user answers once,
and the answer is kept in `same-person.csv` in their folder.

`intros.csv` is never rewritten with a merge: it keeps what the mail said. The
merge is applied in memory wherever the ranking is built.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from intro_store import IntroRow
from people_store import _ROLE_LOCAL

FILE = "same-person.csv"
COLUMNS = ("address", "other", "same")
MIN_TOKEN = 6        # "dana" matches too many people; "okafor" does not
MAX_ASK = 10         # per scan; the rest wait for the next one


def _tokens(local: str) -> list:
    return [t for t in re.split(r"[._+\-\d]+", local.lower()) if t]


def _looks_same(a: str, b: str) -> str:
    """Why two addresses look like one person, or "" if they don't."""
    la, _, da = a.lower().partition("@")
    lb, _, db = b.lower().partition("@")
    if da == db or la in _ROLE_LOCAL or lb in _ROLE_LOCAL:
        return ""
    ta, tb = _tokens(la), _tokens(lb)
    if len(ta) >= 2 and ta == tb:
        return "same name"
    for x, y in ((la, lb), (lb, la)):
        # "dokafor" / "okafor": an initial in front of the surname.
        if len(y) >= MIN_TOKEN and len(x) == len(y) + 1 and x.endswith(y):
            return "initial and surname"
    # "okafor" / "dana.okafor": the one name is the other's surname. Not the
    # first name -- rachel@ and rachel.trobman@ were different people.
    short, full = sorted((ta, tb), key=len)
    if (len(short) == 1 and len(full) >= 2 and short[0] == full[-1]
            and len(short[0]) >= MIN_TOKEN):
        return "surname of a fuller name"
    return ""


def candidates(addresses: Iterable[str]) -> list:
    """(a, b, reason) for every pair that looks like one person."""
    addrs = sorted({x.lower() for x in addresses if x and "@" in x})
    out = []
    for i, a in enumerate(addrs):
        for b in addrs[i + 1:]:
            why = _looks_same(a, b)
            if why:
                out.append((a, b, why))
    return out


def read_answers(path: Path) -> dict:
    """frozenset({a, b}) -> True (same person) or False. Last answer wins."""
    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            a, b = (d.get("address") or "").lower(), (d.get("other") or "").lower()
            if a and b:
                out[frozenset((a, b))] = (d.get("same") or "").strip() == "yes"
    return out


def record(path: Path, a: str, b: str, same: bool) -> None:
    """Append one answer. Append, not rewrite: the file is the user's record."""
    path = Path(path)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(COLUMNS)
        w.writerow([a.lower(), b.lower(), "yes" if same else "no"])


def _intro_counts(rows: Sequence[IntroRow]) -> Counter:
    return Counter(r.introducer for r in rows
                   if r.introducer and r.direction == "inbound")


def pending(rows: Sequence[IntroRow], answers: Mapping, principal: str = "",
            limit: int = MAX_ASK) -> list:
    """Pairs to ask about: unanswered, touching someone who introduced the
    principal to people, most introductions first. (a, b, reason, n_a, n_b)."""
    counts = _intro_counts(rows)
    everyone = {r.introducer for r in rows} | {p for r in rows for p in r.introduced}
    everyone.discard((principal or "").lower())
    todo = []
    merged = canonical(rows, answers)
    for a, b, why in candidates(everyone):
        if frozenset((a, b)) in answers:
            continue
        if merged.get(a, a) == merged.get(b, b):
            continue            # already one person through another answer
        if counts[a] or counts[b]:
            todo.append((a, b, why, counts[a], counts[b]))
    todo.sort(key=lambda p: (-(p[3] + p[4]), p[0]))
    return todo[:limit]


def canonical(rows: Sequence[IntroRow], answers: Mapping) -> dict:
    """address -> the address it is ranked under. Union of every "yes"; each
    group is named by its busiest address, ties alphabetical."""
    parent: dict = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    for pair, same in answers.items():
        if same and len(pair) == 2:
            a, b = sorted(pair)
            parent[find(a)] = find(b)
    groups: dict = {}
    for x in list(parent):
        groups.setdefault(find(x), set()).add(x)
    for root in list(groups):
        groups[root].add(root)
    # A "no" between two members of one group wins: the user said those two
    # differ, so nothing in that group is merged behind their back.
    noes = [p for p, same in answers.items() if not same]
    groups = {r: m for r, m in groups.items()
              if not any(p <= m for p in noes)}
    counts = _intro_counts(rows)
    out = {}
    for members in groups.values():
        head = sorted(members, key=lambda m: (-counts[m], m))[0]
        out.update({m: head for m in members if m != head})
    return out


def apply(rows: Sequence[IntroRow], answers: Mapping) -> list:
    """The rows with every "yes" pair folded under one address."""
    to = canonical(rows, answers)
    if not to:
        return list(rows)
    out = []
    for r in rows:
        introducer = to.get(r.introducer, r.introducer)
        # Never introduced by themselves: the other address may have been on
        # the thread as a party.
        introduced = tuple(dict.fromkeys(
            q for q in (to.get(p, p) for p in r.introduced) if q != introducer))
        if introducer == r.introducer and introduced == r.introduced:
            out.append(r)
            continue
        out.append(IntroRow(**{**r.__dict__, "introducer": introducer,
                               "introduced": introduced}))
    return out


def write_to(rows: Sequence[IntroRow], merged: Mapping) -> dict:
    """head -> the group's most recently seen address, where that differs.

    A merged person is ranked under their busiest address but emailed at the
    newest: one last used years ago may be a former employer's mailbox. The
    same rule the CRM uses for a conflict -- the most recent address wins.
    """
    last: dict = {}
    for r in rows:
        for a in (r.introducer, *r.introduced):
            if a and r.date > last.get(a, ""):
                last[a] = r.date
    groups: dict = {}
    for a, head in merged.items():
        groups.setdefault(head, {head}).add(a)
    out = {}
    for head, members in groups.items():
        newest = max(members, key=lambda m: (last.get(m, ""), m == head))
        if newest != head:
            out[head] = newest
    return out
