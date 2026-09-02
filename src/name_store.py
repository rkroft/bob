"""Who an address belongs to, and how strongly Bob knows it.

The connector returns bare addresses — `dwhitfield@hey.com`, never
`"Dana Whitfield" <dwhitfield@hey.com>` — in every format including RAW (verified
2026-09-02). So on that path `scan(names_out=...)` collects nothing and the
roster labels everyone by email. A graph of local-parts is not a graph anyone
recognises, and §5.3 is explicit that recognition is the whole moment.

Names therefore have to come from somewhere else, and every source is weaker
than a header. That makes provenance the point of this module rather than a
nicety: a name Bob read off a signature and a name Bob assembled from an
address are different claims and must not be stored as if they were the same.

**Precedence, strongest first.** A stronger source always wins, and an equal
one never overwrites — first writer holds, so a re-run cannot reshuffle labels
between scans and quietly change the graph.

| Evidence | Where it comes from | Trust |
|---|---|---|
| `header` | a real `From`/`To` display name (mbox path only) | the person's own spelling |
| `quoted_header` | the attribution a mail client writes when quoting a reply — *"On Tue… Dana Whitfield <dwhitfield@hey.com> wrote:"* | a header one hop removed: the client copied it, name and address already paired |
| `signature` | a sign-off in an intro body — *"Cheers, Josh Brewer"* | strong; they wrote it |
| `greeting` | an opener — *"Hi Karina and Rachel"* | first names only, and the pairing to an address is inferred |
| `local_part` | `josh.brewer@` -> Josh Brewer | a guess, and wrong for handles |

`local_part` is deliberately the weakest and is **not** written to this file.
It stays where it already lives, as a render-time fallback, so that "Bob knows
this person's name" and "Bob can make something readable out of the address"
never become the same claim in storage.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from mail_source import normalize_addr

COLUMNS = ("address", "name", "evidence", "thread_id")

# Strongest first. Membership is also the validity check: an unknown evidence
# string is dropped rather than ranked last, because a typo'd source would
# otherwise silently outrank nothing and win by arriving first.
PRECEDENCE: Sequence[str] = ("header", "quoted_header", "signature", "greeting")

# "Dana Whitfield <dwhitfield@hey.com>" inside a quoted attribution. The name group is
# greedy on purpose -- it swallows the whole "On Tue, Feb 6, 2024 at 11:42 AM"
# prefix, which `_trim_to_name` then cuts back. Trying to anchor the start in
# the pattern fails on the many date formats clients emit; trimming from the
# right is stable because the name is always the part touching the bracket.
_QUOTED = re.compile(
    r"([^<>\n@]{2,120}?)\s*<\s*(?!mailto:)([^<>@\s]+@[^<>\s]+?)\s*>")

# The `<mailto:...>` duplicate some clients add after an address. Removing it
# is not cosmetic: it is emitted as "<addr\n<mailto:addr>>", which leaves the
# real address with no reachable closing bracket until the duplicate is gone.
_MAILTO = re.compile(r"<\s*mailto:[^<>]*>")

# Leading quote markers, per line. A reply nested three deep wraps its
# attribution across lines as ">>> Eve Blossom <\n>>> eve@example.com>", so the
# address is unreachable until these are gone.
_QUOTE_LINE = re.compile(r"^[ \t]*(?:>[ \t]*)+", re.M)

# Words that end a name walk. These sit between the date and the name in the
# attribution shapes clients emit ("On Tue ... wrote:", "Sent from"), and are
# short and capitalised enough to look like name parts otherwise. Weekday and
# month abbreviations are here for the same reason -- "On Mon Ben Mercer" would
# otherwise yield "On Mon Ben Mercer".
_STOP_WORDS = frozenset("""
on at from sent wrote cc bcc to by re fwd via utc gmt
mon tue tues wed thu thur thurs fri sat sun
monday tuesday wednesday thursday friday saturday sunday
jan feb mar apr may jun jul aug sep sept oct nov dec
january february march april june july august september october
november december
""".split())


def _is_name_word(w: str) -> bool:
    """Could this token be part of a person's name?

    Written out rather than as one regex because the first attempt was a regex
    and it silently rejected every capitalised word — `[A-Z]{1,4}.*` matches
    "Kroft" as readily as "AM". Four plain rules are checkable by eye; that
    pattern was not.
    """
    if not w[:1].isalpha():
        return False
    if any(c.isdigit() for c in w):
        return False
    if any(c in ",;:" for c in w):
        return False
    if w.lower().strip(".") in _STOP_WORDS:
        return False
    # AM, PM, PST, UTC sit directly before the name in "at 11:42 AM Dana Whitfield"
    # and would otherwise be absorbed into it. A real name part is rarely a
    # short all-caps token.
    return not (w.isupper() and len(w) <= 4)


@dataclass(frozen=True)
class Name:
    address: str
    name: str
    evidence: str
    thread_id: str = ""

    @property
    def rank(self) -> int:
        return PRECEDENCE.index(self.evidence)


def _clean(name: str) -> str:
    """Trim quoting and stray punctuation from a name lifted out of prose.

    A sign-off arrives as "Josh Brewer," or "-- Josh Brewer" far more often than
    it arrives clean, and the comma would otherwise become part of the label on
    the graph.
    """
    return (name or "").strip().strip('"\'').strip(" ,-–—:;").strip()


def is_plausible(name: str) -> bool:
    """Reject the things that are obviously not a person's name.

    Not a spelling check — Bob cannot know how someone spells their own name,
    and second-guessing it would throw away good data. This only catches the
    shapes that are certainly wrong: empty, an address, absurdly long (a
    signature block that swallowed a job title and a phone number), or numeric.

    A wrong name is worse than an address (§4.5), so the bar is "could this be
    a person" rather than "is this the right person".
    """
    n = _clean(name)
    if not n or "@" in n or len(n) > 60:
        return False
    if not any(c.isalpha() for c in n):
        return False
    return len(n.split()) <= 5


def _trim_to_name(raw: str) -> str:
    """"On Tue, Feb 6, 2024 at 11:42 AM Dana Whitfield" -> "Dana Whitfield".

    Walks back from the bracket, keeping words that could be part of a name and
    stopping at the first that could not. That direction matters: the name is
    always adjacent to the address, while everything before it is a date format
    that varies by client and locale and is not worth trying to enumerate.
    """
    words = raw.replace("\n", " ").split()
    kept: list = []
    for w in reversed(words):
        if len(kept) >= 4 or not _is_name_word(w):
            break
        kept.append(w)
    name = " ".join(reversed(kept))
    # A display name starts with a capital. Without this, prose that happens to
    # precede an address — "please cc <addr>" — trims to a lowercase fragment
    # that is otherwise shaped exactly like a name.
    return name if name[:1].isupper() else ""


def extract_quoted_names(body: str) -> list:
    """Names paired with addresses, lifted from quoted reply attributions.

    *"On Tue, Feb 6, 2024 at 11:42 AM Dana Whitfield <dwhitfield@hey.com> wrote:"* is
    written by the replying client from the real `From` header, so it carries
    the two halves already paired. That makes it the best evidence available on
    the connector path, which strips display names everywhere (HAP-318) — and
    it is deterministic, so no judgment is spent on it.

    Anything that does not trim to a plausible name is dropped rather than
    guessed at. A wrong name is worse than an address (§4.5), and the shapes
    this sees — dates, quote markers, `<mailto:>` duplicates — are exactly the
    ones that would produce a confident-looking wrong answer.
    """
    # Order matters. Quote markers first, so a wrapped attribution becomes one
    # readable line; then the mailto duplicate, which is what frees the closing
    # bracket on the address it shadows.
    text = _MAILTO.sub("", _QUOTE_LINE.sub("", body or ""))
    out: list = []
    for raw_name, addr in _QUOTED.findall(text):
        name = _trim_to_name(raw_name)
        if is_plausible(name):
            out.append(Name(addr, name, "quoted_header"))
    return out


def merge(existing: Mapping[str, Name], incoming: Iterable[Name]) -> dict:
    """Fold new observations into what is already known.

    Stronger evidence replaces weaker. **Equal evidence does not replace** —
    the first observation holds. Without that rule two signatures spelling a
    name differently would flip the label depending on which thread the scan
    happened to read last, and the graph would change between runs for no
    reason the user could see.
    """
    out = dict(existing)
    for n in incoming:
        if n.evidence not in PRECEDENCE or not is_plausible(n.name):
            continue
        n = Name(normalize_addr(n.address), _clean(n.name), n.evidence, n.thread_id)
        if not n.address:
            continue
        prior = out.get(n.address)
        if prior is None or n.rank < prior.rank:
            out[n.address] = n
    return out


def read_names(path: Path) -> dict:
    """Read the names file. A missing file is empty, not an error.

    Names are enrichment: a scan that has never had a name pass run against it
    is a normal state, not a broken one.
    """
    if not path.exists():
        return {}
    rows: list[Name] = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(Name(
                address=r.get("address", ""),
                name=r.get("name", ""),
                evidence=(r.get("evidence") or "").strip(),
                thread_id=r.get("thread_id", ""),
            ))
    return merge({}, rows)


def write_names(names: Mapping[str, Name], path: Path) -> None:
    """Write the file, sorted by address so a diff between runs is readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for addr in sorted(names):
            n = names[addr]
            w.writerow([n.address, n.name, n.evidence, n.thread_id])


def as_lookup(names: Mapping[str, Name]) -> dict:
    """`{address: name}` — the shape `build_people` already takes."""
    return {a: n.name for a, n in names.items()}


def worklist(addresses: Iterable[str], known: Mapping[str, Name],
             rows: Sequence, exclude: Iterable[str] = ()) -> list:
    """Which addresses still need a name, and which threads to look in.

    Returns `[(address, [thread_id, ...]), ...]`, most-evidence-first so a
    capped pass spends its calls where they are most likely to pay.

    `exclude` is for addresses that need no lookup at all — the principal above
    all, who appears on every row by design (the connector→principal edge is
    the fact this product exists to surface) and whose own name Bob never has
    to discover.

    Only threads the address actually appears on are offered, because the name
    has to be found in mail that person was party to — and only introductions
    are considered, which is what keeps this pass narrow enough to afford
    (§3.2: the connector is right for narrow, low-volume jobs).
    """
    want = {normalize_addr(a) for a in addresses} - set(known)
    want -= {normalize_addr(a) for a in exclude}
    want.discard("")
    by_addr: dict[str, list[str]] = {a: [] for a in want}
    for r in rows:
        people = {normalize_addr(r.introducer), *(normalize_addr(p) for p in r.introduced)}
        for a in people & want:
            by_addr[a].append(r.thread_id)
    return sorted(
        ((a, t) for a, t in by_addr.items() if t),
        key=lambda kv: (-len(kv[1]), kv[0]),
    )
