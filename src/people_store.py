"""people.csv — who these people are, and what they did for you.

The roster's first increment (Plugin MVP §4.4). The graph shows the shape; this
answers "who". Two columns of the eventual roster are here — name and intro
counts — with last-contact and company-from-domain still to come.

Kept separate from `intros.csv` on purpose. That file is a record of *events*
and never changes once written; this one is *derived* and is rebuilt from
scratch on every scan. Mixing them would mean rewriting event history whenever
someone's display name changed.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from intro_store import IntroRow

PEOPLE_COLUMNS = (
    "address", "name", "intros_for_you", "intros_you_made", "introduced_you_to",
    "is_service", "last_contact",
)

SEP = ";"

# Excel and Sheets execute a cell beginning with any of these. A display name
# is attacker-controlled text, so `=HYPERLINK("http://evil…")` in a From header
# would run when the user opens their own roster.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: str) -> str:
    return "'" + value if value.startswith(_FORMULA_LEAD) else value


# Local parts that name a function rather than a person. Necessary evidence for
# calling something a service, never sufficient — plenty of founders answer at
# hello@ and team@.
_ROLE_LOCAL = frozenset({
    "talent", "jobs", "careers", "hiring", "recruiting", "noreply", "no-reply",
    "donotreply", "notifications", "notification", "alerts", "team", "hello",
    "info", "support", "help", "contact", "admin", "mail", "mailer", "news",
    "newsletter", "updates", "digest", "bot", "automated", "system",
})


def is_service(address: str, contacted, automated: bool = False) -> bool:
    """Is there a person behind this address?

    Two pieces of evidence, and BOTH are required:

    - the address names a function, or every message from it was bulk or
      machine-generated; and
    - the user has never written to it.

    The second is what makes the rule safe. Address shape alone misclassifies
    real people — `hello@theirstartup.com` is usually a founder — and never
    replying alone misclassifies real people too, since plenty of genuine
    introductions simply go unanswered. Only together do they mean much: you
    reply to humans, and you do not reply to a mailer.

    Discovered from a talent-matching product that sent five real
    introductions from an automated address, each signed with the product's
    own name rather than a person's. The introductions were genuine; there
    was nobody to thank for them.
    """
    # `None` means the evidence was never gathered, which is NOT the same as
    # gathering it and finding nothing. Without it, calling anything a service
    # would rest on address shape alone — the half of the rule that is known to
    # misclassify real people.
    if contacted is None:
        return False
    if address in contacted:
        return False
    local = address.partition("@")[0].lower()
    return bool(automated or local in _ROLE_LOCAL)


@dataclass(frozen=True)
class Person:
    address: str
    name: str
    intros_for_you: int = 0          # introductions this person made FOR the principal
    intros_you_made: int = 0         # introductions the principal made, if this is them
    introduced_you_to: tuple = field(default_factory=tuple)
    is_service: bool = False
    # ISO day of the most recent DIRECT message either way (last_contact.py),
    # or "" when no direct exchange was found. Empty means "not known", never
    # "never" -- Bob sees one channel and cannot assert absence (§4.6).
    last_contact: str = ""


def name_from_address(addr: str) -> str:
    """A readable fallback when no header ever carried a display name.

    "dana.okafor@example.com" -> "Dana Okafor". Wrong for initials and for
    anyone whose local part is a handle, which is why it is only ever a
    fallback — a real display name always wins.
    """
    local = addr.partition("@")[0]
    words = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return " ".join(w.capitalize() for w in words) or addr


def build_people(
    rows: Sequence[IntroRow], principal: str, names: Mapping[str, str],
    contacted=None, automated=None,
) -> list:
    """Rows + a name lookup -> the roster, ordered by intros made for you."""
    principal = (principal or "").lower()
    automated = automated or set()

    for_you: dict = defaultdict(int)
    you_made: dict = defaultdict(int)
    introduced: dict = defaultdict(set)
    seen: set = set()

    for r in rows:
        if r.introducer:
            seen.add(r.introducer)
            if r.direction == "inbound":
                for_you[r.introducer] += 1
                # Who this person put in front of you — the principal is an
                # endpoint of that edge but is not someone they introduced you to.
                introduced[r.introducer].update(
                    p for p in r.introduced if p and p != principal)
            else:
                you_made[r.introducer] += 1
        seen.update(p for p in r.introduced if p)

    people = [
        Person(
            address=a,
            name=(names.get(a) or "").strip() or name_from_address(a),
            intros_for_you=for_you[a],
            intros_you_made=you_made[a],
            introduced_you_to=tuple(sorted(introduced[a])),
            is_service=is_service(a, contacted, a in automated),
        )
        for a in sorted(seen)
    ]
    people.sort(key=lambda p: (-p.intros_for_you, -p.intros_you_made, p.address))
    return people


def write_people(people: Sequence[Person], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PEOPLE_COLUMNS)
        for p in people:
            w.writerow([p.address, _safe_cell(p.name),
                        p.intros_for_you, p.intros_you_made,
                        SEP.join(p.introduced_you_to),
                        "1" if p.is_service else "", p.last_contact])


def read_people(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            out.append(Person(
                address=d["address"],
                name=d["name"],
                intros_for_you=int(d["intros_for_you"] or 0),
                intros_you_made=int(d["intros_you_made"] or 0),
                introduced_you_to=tuple(
                    x for x in d["introduced_you_to"].split(SEP) if x),
                is_service=bool(d.get("is_service")),
                # .get, not [] -- 522 rows predate this column.
                last_contact=(d.get("last_contact") or ""),
            ))
    return out
