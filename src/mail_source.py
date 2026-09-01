"""The single mail-access interface.

All mail access sits behind one narrow contract — *give me candidate intro
threads* — so no provider's API shape leaks into detection or the object model.

Originally required by Product Definition §8.2, which is now struck: Bob has no
OAuth app, because it reads mail through the user's own Claude connector. The
seam earns its keep anyway, since there are three real sources rather than one
hypothetical: the connector, an mbox export (`mbox_source.py`), and IMAP for
harnesses with no connector to borrow. The swap happens here and nowhere else.

Nothing in this module knows about introductions.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Sequence

_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def normalize_addr(raw: str) -> str:
    """'Dana Okafor <Dana@Example.COM>' -> 'dana@example.com'.

    Returns lowercased input if no address is found, so a malformed header
    degrades to a stable key instead of vanishing. That fallback is why the
    render layer must escape its output: unparseable header text reaches the
    page verbatim.
    """
    m = _ADDR.search(raw or "")
    return (m.group(0) if m else (raw or "")).strip().lower()


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(name: str) -> str:
    """Strip quoting and control characters.

    A display name is attacker-controlled text that is printed to a terminal.
    An escape sequence in it can retitle the window or, via OSC 52, reach the
    clipboard — so the characters never leave this function.
    """
    return _CONTROL.sub("", name or "").strip().strip('"').strip()


def best_name(names: "Sequence[str]") -> str:
    """One display name for an address seen under several spellings.

    The same person arrives as "Nadia", "Nadia Okonjo", "NADIA OKONJO" and
    "Nadia Okonjo | Acme — Head of BD" across six years of mail.

    - The vote is **case-insensitive**, so casing variants are one candidate and
      cannot split it; the winner is rendered in its most common casing.
    - Most frequent wins. One oddly-formatted header must not outvote a hundred
      normal ones.
    - A **fuller form of the same name** is preferred — "Marcus Leyva Lee"
      contains every token of "Marcus Leyva" — but only when it is itself
      well-attested. Without that floor a lone signature block or a
      "(via Acme Scheduling)" suffix wins, which is the failure the frequency
      rule exists to prevent.
    """
    cleaned = [c for c in (_clean(n) for n in names) if c]
    if not cleaned:
        return ""

    by_key: dict = {}
    for n in cleaned:
        by_key.setdefault(n.casefold(), []).append(n)
    counts = {k: len(v) for k, v in by_key.items()}
    top = max(counts.values())

    def render(key: str) -> str:
        return Counter(by_key[key]).most_common(1)[0][0]

    winner = next(n.casefold() for n in reversed(cleaned)
                  if counts[n.casefold()] == top)

    # PROPER superset only: an equal token set is a casing or punctuation
    # variant, already merged by the case-insensitive vote.
    floor = max(2, top // 4)
    wt = set(winner.split())
    fuller = [k for k in counts
              if wt and wt < set(k.split()) and counts[k] >= floor]
    if fuller:
        return render(max(fuller, key=lambda k: counts[k]))
    return render(winner)


@dataclass
class Message:
    id: str
    from_addr: str
    to_addrs: list[str] = field(default_factory=list)
    cc_addrs: list[str] = field(default_factory=list)
    from_name: str = ""                   # display name, "" when the header had none
    to_names: list[str] = field(default_factory=list)
    cc_names: list[str] = field(default_factory=list)
    subject: str = ""
    date: datetime | None = None
    body_text: str | None = None          # None in metadata-only mode
    is_calendar_invite: bool = False
    is_bulk: bool = False                 # List-Unsubscribe / Precedence: bulk

    def __post_init__(self) -> None:
        self.from_addr = normalize_addr(self.from_addr)
        self.from_name = (self.from_name or "").strip()
        # Addresses and names are positional partners. Dropping an empty address
        # has to drop its name too, or every later name is attributed to the
        # wrong person — a silent, plausible-looking corruption.
        self.to_addrs, self.to_names = _pair(self.to_addrs, self.to_names)
        self.cc_addrs, self.cc_names = _pair(self.cc_addrs, self.cc_names)


def _pair(addrs: "Sequence[str]", names: "Sequence[str]") -> tuple:
    """Normalize addresses and keep names aligned, dropping empty pairs."""
    padded = list(names) + [""] * max(0, len(addrs) - len(names))
    kept = [(normalize_addr(a), (n or "").strip())
            for a, n in zip(addrs, padded) if a]
    return [a for a, _ in kept], [n for _, n in kept]


@dataclass
class Thread:
    id: str
    messages: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Chronological order is load-bearing: the structural signal depends on
        # knowing which message came first. Undated messages sort last, keeping
        # their relative order.
        self.messages.sort(key=lambda m: (m.date is None, m.date or datetime.min))


def participants(msg: Message) -> set[str]:
    """Everyone visible on a message. BCC is invisible by definition — which is
    exactly why the connector appears to *vanish* in the structural signal."""
    return {msg.from_addr, *msg.to_addrs, *msg.cc_addrs} - {""}


class MailSource(Protocol):
    """What Bob needs from a mailbox. Nothing more."""

    def principal(self) -> str:
        """The mailbox owner's primary address."""
        ...

    def search(self, query: str, limit: int = 200) -> Sequence[str]:
        """Provider-native query -> thread ids."""
        ...

    def fetch(self, thread_ids: Sequence[str], include_bodies: bool = True) -> Sequence[Thread]:
        """Thread ids -> normalized threads.

        `include_bodies=False` skips message bodies. Detection itself reads
        subject *and* body (Plugin MVP §4.1) — the metadata-only mode was
        dropped once the OAuth-scope argument for it disappeared. What remains
        is a cheap pass for work that only needs headers, such as counting
        thread activity during triage.
        """
        ...
