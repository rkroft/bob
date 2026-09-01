"""Introductions per month, as bars.

Two rules do most of the work here:

**Every calendar month appears, including the empty ones.** Rachel's data spans
191 months of which 84 have no introductions at all. Plotting only the months
with data would compress sixteen years into a dense strip and invent a rhythm
that is not there — an uneven time axis is a lie about the shape of the data.

**Inbound and outbound stack rather than sharing a bar.** They are the same
measure counted two ways, so one axis serves both, and the split is the
interesting part: a month of nine introductions made *for* you reads very
differently from nine you made.
"""

from __future__ import annotations

from typing import Sequence


def month_buckets(rows: Sequence) -> list:
    """[{month, inbound, outbound, total}] — contiguous, oldest first."""
    dated = [r for r in rows if r.date]
    if not dated:
        return []
    keys = sorted(r.date[:7] for r in dated)
    (y0, m0), (y1, m1) = _ym(keys[0]), _ym(keys[-1])

    counts: dict = {}
    for r in dated:
        b = counts.setdefault(r.date[:7], {"inbound": 0, "outbound": 0})
        b["outbound" if r.direction == "outbound" else "inbound"] += 1

    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        key = f"{y:04d}-{m:02d}"
        c = counts.get(key, {"inbound": 0, "outbound": 0})
        out.append({"month": key, "inbound": c["inbound"],
                    "outbound": c["outbound"],
                    "total": c["inbound"] + c["outbound"]})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ym(key: str) -> tuple:
    return int(key[:4]), int(key[5:7])


def year_ticks(buckets: Sequence) -> list:
    """Index of the first bucket of each year — the axis labels."""
    seen, ticks = set(), []
    for i, b in enumerate(buckets):
        year = b["month"][:4]
        if year not in seen:
            seen.add(year)
            ticks.append({"i": i, "label": year})
    return ticks


def arrivals(rows: Sequence, principal: str = "") -> list:
    """Who entered the network, and when — one entry per person, ever.

    Distinct from the introductions table, which lists *events*. A person joins
    your network once; seeing them again in a later thread is not a new
    arrival. So this keeps each person's FIRST appearance and drops the rest,
    which is what makes it answer "who came into my life in 2024" rather than
    "what happened in 2024".

    Newest first, because recent arrivals are the ones still worth acting on.
    """
    principal = (principal or "").lower()
    first: dict = {}
    for r in sorted(rows, key=lambda r: r.date or "9999"):
        if not r.date:
            continue
        for person in r.introduced:
            if not person or person == principal or person in first:
                continue
            first[person] = {
                "date": r.date,
                "month": r.date[:7],
                "person": person,
                "by": r.introducer,
                "direction": r.direction,
            }
    return sorted(first.values(), key=lambda a: a["date"], reverse=True)


def group_by_month(entries: Sequence) -> list:
    """[(month, [entry, …])] preserving the order given."""
    out: list = []
    for e in entries:
        if not out or out[-1][0] != e["month"]:
            out.append((e["month"], []))
        out[-1][1].append(e)
    return out


def arrival_columns(rows: Sequence, principal: str = "") -> list:
    """Arrivals as contiguous month columns, oldest first.

    The vertical list read as a feed; a horizontal strip reads as a life. Time
    runs left to right, each person is a mark stacked in the month they first
    appeared, and the empty months stay in place so a quiet year looks quiet
    rather than being closed up.
    """
    entries = list(reversed(arrivals(rows, principal)))   # oldest first
    if not entries:
        return []
    by: dict = {}
    for e in entries:
        by.setdefault(e["month"], []).append(e)

    y0, m0 = int(entries[0]["month"][:4]), int(entries[0]["month"][5:7])
    y1, m1 = int(entries[-1]["month"][:4]), int(entries[-1]["month"][5:7])
    out, y, m = [], y0, m0
    while (y, m) <= (y1, m1):
        key = f"{y:04d}-{m:02d}"
        out.append({"month": key, "people": by.get(key, [])})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out
