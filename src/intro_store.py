"""intros.csv — the table the scan writes and the graph reads.

Plain CSV on purpose (Plugin MVP §5.1): at tens-to-hundreds of rows a database
buys nothing and costs portability. If Bob is abandoned the user still has a
spreadsheet of every introduction anyone ever made for them, and the export
needs no feature because the CSV *is* the export.

One row per introduction, not per edge. "34 introductions, 51 people" is 34
rows; the graph explodes `introduced` into edges at render time.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

COLUMNS = (
    "thread_id", "date", "direction", "introducer",
    "introduced", "subject", "thread_link", "confidence",
    # What became of it (Plugin MVP §4.6). Booleans and dates only -- no
    # message count, so a tally cannot leak into copy. Empty on every row
    # written before the scan captured after-signal, which `triage()` reads
    # as "can't tell" rather than "never landed".
    "observed", "replied", "they_replied", "met", "first_reply", "last_exchange",
)

# Addresses cannot contain ";", so it is safe as a list separator and keeps the
# file readable in Excel, which a JSON blob in a cell would not.
SEP = ";"


@dataclass(frozen=True)
class IntroRow:
    thread_id: str
    date: str                      # ISO date, or "" when the mail had none
    direction: str                 # "inbound" | "outbound"
    introducer: str
    introduced: tuple[str, ...]
    subject: str
    thread_link: str
    confidence: float
    # `observed` is the whole reason the rest can be trusted. Without it a row
    # from a scan that never captured after-signal is indistinguishable from a
    # scanned thread nobody replied to -- and reading the first as the second
    # is how Bob would draft a late-reply email about an introduction that went
    # perfectly well. Not observed is not the same as did not happen.
    observed: bool = False
    replied: bool = False
    they_replied: bool = False
    met: bool = False
    first_reply: str = ""
    last_exchange: str = ""


def write_intros(rows: Sequence[IntroRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([
                r.thread_id, r.date, r.direction, r.introducer,
                SEP.join(r.introduced), r.subject, r.thread_link,
                f"{r.confidence:.2f}",
                "1" if r.observed else "",
                "1" if r.replied else "", "1" if r.they_replied else "",
                "1" if r.met else "", r.first_reply, r.last_exchange,
            ])


def read_intros(path: Path) -> list[IntroRow]:
    if not path.exists():
        return []
    out: list[IntroRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            out.append(IntroRow(
                thread_id=d["thread_id"],
                date=d["date"],
                direction=d["direction"],
                introducer=d["introducer"],
                introduced=tuple(x for x in d["introduced"].split(SEP) if x),
                subject=d["subject"],
                thread_link=d["thread_link"],
                confidence=float(d["confidence"] or 0),
                # .get(), not [] -- a CSV written before these columns existed
                # must still load. Its rows come back with no after-signal,
                # which is exactly the "can't tell" the buckets need.
                observed=bool(d.get("observed")),
                replied=bool(d.get("replied")),
                they_replied=bool(d.get("they_replied")),
                met=bool(d.get("met")),
                first_reply=d.get("first_reply") or "",
                last_exchange=d.get("last_exchange") or "",
            ))
    return out


def after_of(row: IntroRow):
    """The row's after-signal, or `None` when the scan never looked.

    The bridge between the stored row and `after.triage()`. `None` is the
    honest answer for a row written before after-signal existed: `triage()`
    turns it into "can't tell", which is the one bucket that produces no email
    and no claim.
    """
    from after import After
    if not row.observed:
        return None
    return After(principal_replied=row.replied, other_replied=row.they_replied,
                 meeting_invited=row.met, first_reply=row.first_reply,
                 last_exchange=row.last_exchange)
