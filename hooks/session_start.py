#!/usr/bin/env python3
"""Bob's ambient line at session start.

Three rules, and they are the whole design (Plugin MVP §3.6):

1. Speak only when there is something new. A hook that reports "all clear"
   becomes wallpaper.
2. At most once a week. Even real news becomes noise at daily cadence.
3. Exit silently outside a Bob folder. Plugin hooks fire in *every* project.

It reports **aging, never arrival**. The user was on the intro email, so "new
intro" is worth nothing to them; "you haven't emailed Priya in two years" is not.
No mail is read here — this is a local pass over people.csv.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

STAMP = ".bob-last-spoke"
QUIET_DAYS = 7
STALE_YEARS = 1


def _parse(d: str) -> date | None:
    try:
        return datetime.strptime(d.strip()[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def main() -> int:
    cwd = Path.cwd()
    intros, people = cwd / "intros.csv", cwd / "people.csv"

    # Rule 3 — not a Bob folder, not our business.
    if not intros.exists() or not people.exists():
        return 0

    # Rule 2 — at most weekly.
    stamp = cwd / STAMP
    today = date.today()
    if stamp.exists():
        last = _parse(stamp.read_text(encoding="utf-8"))
        if last and today - last < timedelta(days=QUIET_DAYS):
            return 0

    cutoff = today - timedelta(days=365 * STALE_YEARS)
    stale = []
    with people.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("is_service") or "").strip().lower() in {"1", "true", "yes"}:
                continue
            when = _parse(row.get("last_contact") or "")
            if when and when < cutoff:
                stale.append((when, row.get("name") or row.get("address") or ""))

    # Rule 1 — nothing to say, say nothing.
    if not stale:
        return 0

    stale.sort()
    oldest = stale[0]
    years = (today - oldest[0]).days // 365
    n = len(stale)
    who = "person" if n == 1 else "people"
    msg = (
        f"{n} {who} in your network you haven't emailed in over a year"
        f" — longest is {oldest[1]}, {years or 1}+ years. `/bob-graph` sorts them."
    )

    stamp.write_text(today.isoformat(), encoding="utf-8")
    print(json.dumps({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "The user's Bob network folder is the working directory. " + msg
            ),
        },
    }))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # A hook that errors in every project the user opens is the worst
        # version of this feature. Fail silent, always.
        raise SystemExit(0)
