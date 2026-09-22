"""people.csv — who these people are, and what they did for you.

The roster's first increment (Plugin MVP §4.4). The graph shows the shape; this
answers "who". Two columns of the eventual roster are here — name and intro
counts — with last-contact and company-from-domain still to come.

Kept separate from `intros.csv` on purpose: that file has one row per
introduction, this one one row per person, derived from those rows. Both are
rewritten by every scan, so neither holds anything a scan cannot reproduce.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from intro_store import IntroRow
from mail_source import REPLY_WORDS

PEOPLE_COLUMNS = (
    "address", "name", "intros_for_you", "intros_you_made", "introduced_you_to",
    "is_service", "last_contact", "kind", "program",
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
    # What sort of introducer this is: "person", "platform" (a matching
    # service writing from a role address), "ai_connector", or "program"
    # (one person sending templated matches for a program, named in
    # `program`). Everyone stays in the ranking; the kind says what they are.
    kind: str = "person"
    program: str = ""


def name_from_address(addr: str) -> str:
    """A readable fallback when no header ever carried a display name.

    "dana.okafor@example.com" -> "Dana Okafor". Wrong for initials and for
    anyone whose local part is a handle, which is why it is only ever a
    fallback — a real display name always wins.

    **A role address is returned unchanged.** Capitalising `hello@` produces a
    person called "Hello", who then appears on the leaderboard having made
    introductions. That is not a cosmetic slip: the leaderboard is the reveal,
    and a name Bob invented is a wrong answer stated confidently, which §4.5
    says costs more than no answer at all. Showing the address is the honest
    output — it says "someone at this address" instead of naming a person who
    does not exist.

    This guard is separate from `is_service`, deliberately. That decides
    whether the roster believes there is a person behind an address, and it can
    be overridden by evidence (having written to them). This decides only
    whether Bob is willing to make a name up, and nothing overrides it.
    """
    local = addr.partition("@")[0]
    if local.lower() in _ROLE_LOCAL:
        return addr
    words = local.replace(".", " ").replace("_", " ").replace("-", " ").split()
    return " ".join(w.capitalize() for w in words) or addr


# AI connectors that write the introduction themselves. A named list: there is
# nothing in the mail that tells a matching bot from a person with a template.
AI_CONNECTOR_DOMAINS = frozenset({"boardy.ai"})

# A program's intros share a subject prefix before a separator, e.g.
# "Founders Lab 2025 - <startup> connection to <you>".
_PREFIX_SEP = re.compile(r"\s+[-–—|:]\s+|:\s+")
# Intro wording anywhere in the prefix: "Warm intro - X" and "Double opt-in:
# X" are a connector's habit, not a program.
_INTRO_WORDS = re.compile(
    r"\b(?:intro\w*|connect\w*|opt-?in|meet\w*|request)\b", re.I)
# "[EXT] ", "AW: ", "Re: " ahead of the subject a program actually uses.
_LEAD = re.compile(
    rf"^\s*(?:\[[^\]]{{1,20}}\]\s*|(?:{REPLY_WORDS})\s*:\s*)+", re.I)
PROGRAM_MIN = 3


def _program_of(subjects: Sequence[str]) -> str:
    """The prefix most of someone's intro subjects share, if it names something.

    "Intro - X" does not: a connector with a habit is still a person. Nor do a
    few event forwards among many intros -- the prefix must cover most of them.
    """
    counts: dict = defaultdict(int)
    for subj in subjects:
        head = _PREFIX_SEP.split(_LEAD.sub("", subj or ""), 1)
        if len(head) < 2:
            continue
        prefix = head[0].strip()
        if len(prefix) >= 8 and not _INTRO_WORDS.search(prefix):
            counts[prefix] += 1
    best = max(counts.items(), key=lambda kv: kv[1], default=("", 0))
    if best[1] >= PROGRAM_MIN and best[1] * 2 >= len(subjects):
        return best[0]
    return ""


def introducer_kind(address: str, subjects: Sequence[str],
                    automated: bool = False) -> tuple:
    """(kind, program) for someone who introduced the principal to people."""
    domain = address.partition("@")[2].lower()
    if domain in AI_CONNECTOR_DOMAINS:
        return "ai_connector", ""
    local = address.partition("@")[0].lower()
    # Two or more: a founder at hello@ who made one introduction is a person.
    if subjects and (automated or (local in _ROLE_LOCAL and len(subjects) >= 2)):
        return "platform", ""
    program = _program_of(subjects)
    if program:
        return "program", program
    return "person", ""


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
    subjects: dict = defaultdict(list)
    seen: set = set()

    for r in rows:
        if r.introducer:
            seen.add(r.introducer)
            if r.direction == "inbound":
                for_you[r.introducer] += 1
                subjects[r.introducer].append(r.subject)
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
            kind=kind,
            program=program,
        )
        for a in sorted(seen)
        for kind, program in [introducer_kind(a, subjects[a], a in automated)]
    ]
    people.sort(key=lambda p: (-p.intros_for_you, -p.intros_you_made, p.address))
    return people


_KIND_TAG = {"platform": "platform", "ai_connector": "AI connector",
             "program": "program"}


def display_label(addr: str, label: str, person) -> str:
    """A ranked name, with what kind of introducer it is when it is not
    a person. A program is named for the program, and the person who sent
    its introductions is named after it."""
    kind = getattr(person, "kind", "person")
    if kind == "program" and person.program:
        return f"{person.program} · program (via {label})"
    if kind == "platform":
        # The address, not a name: "talent@" capitalised is a person called
        # "Talent", which is the invented-name failure people_store guards.
        return f"{addr} · platform"
    if kind in _KIND_TAG:
        return f"{label} · {_KIND_TAG[kind]}"
    return label


def write_people(people: Sequence[Person], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(PEOPLE_COLUMNS)
        for p in people:
            w.writerow([p.address, _safe_cell(p.name),
                        p.intros_for_you, p.intros_you_made,
                        SEP.join(p.introduced_you_to),
                        "1" if p.is_service else "", p.last_contact,
                        p.kind, _safe_cell(p.program)])


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
                # .get again: files written before 0.1.13 have no kind.
                kind=(d.get("kind") or "person"),
                program=(d.get("program") or ""),
            ))
    return out
