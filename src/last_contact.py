"""When the principal last actually spoke to each person.

The roster's whole point is "who have I lost touch with", and that question is
worthless if the answer counts mail nobody wrote to anybody. Plugin MVP §4.4:
the most recent *direct* message either way, bulk excluded, because "replying
to an investor update, a newsletter, or a life-update blast is not contact, and
counting it produces a warm set full of people you have not actually spoken to
in years."

This is the one part of the roster that has to look past intro threads, so it
is its own pass: headers only (`include_bodies=False`), one sweep, no bodies
read and no body text retained.

Errs toward saying LESS contact than there was. Understating means Bob says
"you haven't spoken in a year" about someone you emailed last week -- annoying,
and the user corrects it. Overstating means Bob calls someone warm because they
are on a mailing list, which is the failure this whole pass exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

# A message addressed to more than this many people is an announcement, not a
# conversation. Investor updates and life-update blasts routinely carry no
# List-Unsubscribe header, so `is_bulk` alone does not catch them.
DIRECT_MAX_RECIPIENTS = 4


@dataclass(frozen=True)
class LastSeen:
    date: str          # ISO, the day of the most recent direct message
    address: str       # the address it was seen at -- NOT "where they work"


def _counterparts(m, principal: str) -> list:
    """Everyone on this message who is not the principal.

    Returns [] when the principal is not on the message at all: other people's
    mail says nothing about when the principal last spoke to them.
    """
    everyone = [m.from_addr] + list(m.to_addrs) + list(m.cc_addrs)
    if principal not in everyone:
        return []
    return [a for a in everyone if a and a != principal]


# Threads per fetch call. Small enough that progress moves visibly and a
# checkpoint is never far behind; large enough that the bookkeeping is noise
# against the network round-trips it wraps.
CHUNK = 200

# Newest threads to look at per person on the targeted path, and the wider
# second look when none of them turn out to be a real exchange.
PROBE, PROBE_WIDE = 6, 30


def _targeted(source, principal, addresses, query, on_start, on_progress) -> dict:
    """Ask the mailbox about each person, instead of reading the whole mailbox.

    The walk below is exhaustive and unusable: five years of a real mailbox is
    100,000 threads at one request each, about ten hours, and it silently stops
    at the cap. Nobody runs that, so `last_contact` stayed empty forever -- a
    performance problem severe enough to be a missing feature.

    A mailbox that can search answers this directly. Results come back
    newest-first, so the first qualifying thread IS the last contact.

    **The escalation is the important part.** The most recent mail involving
    someone is often a newsletter or a calendar invite, which is not the two of
    you talking. If none of the first `PROBE` threads carry a direct message,
    the honest conclusion is not "never" -- it is "not in the newest few". So
    look wider once before giving up. Cost is bounded: only the people whose
    recent mail is all machine-sent pay for it.
    """
    people = sorted({a.lower() for a in addresses
                     if a and a.lower() != principal})
    if on_start:
        on_start(len(people), "people")

    out: dict = {}
    for i, addr in enumerate(people, 1):
        base = f"from:{addr} OR to:{addr}"
        scoped = f"({query}) ({base})" if query else base
        for width in (PROBE, PROBE_WIDE):
            try:
                ids = source.search(scoped, limit=width)
            except Exception:
                # One unsearchable address must not end the run. A person with
                # no date is already a state Bob knows how to report.
                break
            for thread in source.fetch(ids, include_bodies=False):
                _absorb(thread, principal, {addr}, out)
            if addr in out or len(ids) < width:
                break          # found it, or the mailbox has nothing more
        if on_progress and (i % 25 == 0 or i == len(people)):
            on_progress(i, len(people), out)
    return out


def last_direct_contact(source, principal: str,
                        addresses: Optional[Iterable[str]] = None,
                        query: str = "", limit: int = 100000,
                        on_start=None, on_progress=None) -> dict:
    """address -> LastSeen, for the most recent direct message either way.

    `addresses`, when given, restricts the result to people already on the
    roster -- the only ones it can display -- rather than returning every
    address the mailbox has ever touched.

    This walks the mailbox, not the roster. That is the expensive shape and it
    was invisible: `source.fetch` returns only once every thread is in memory,
    so the caller could not report progress even in principle, and a run that
    took two hours printed one line at the start and nothing after. Fetching in
    chunks costs nothing and makes both progress and checkpointing possible.

    `on_start(n, unit)` fires once the work is actually known -- the unit is
    "threads" when walking and "people" when asking per person, because the
    two paths do genuinely different amounts of work and saying "people"
    over a mailbox walk is what made a ten-hour run look nearly done. `on_progress(done, total, found)` fires per chunk and is
    handed the live results, so a caller that persists there turns a kill from
    total loss into a partial answer.
    """
    principal = (principal or "").lower()

    # A searchable mailbox is asked about each person; a local file is walked,
    # because it has no index and reading it is cheap anyway.
    if addresses is not None and getattr(source, "cheap_search", False):
        return _targeted(source, principal, addresses, query,
                         on_start, on_progress)

    wanted = {a.lower() for a in addresses} if addresses is not None else None

    ids = list(source.search(query, limit=limit))
    if on_start:
        on_start(len(ids), "threads")

    out: dict = {}
    for i in range(0, len(ids), CHUNK):
        for thread in source.fetch(ids[i:i + CHUNK], include_bodies=False):
            _absorb(thread, principal, wanted, out)
        if on_progress:
            on_progress(min(i + CHUNK, len(ids)), len(ids), out)
    return out


def _absorb(thread, principal, wanted, out) -> None:
    """Fold one thread's direct messages into `out`, newest date winning."""
    for m in thread.messages:
        if m.date is None or m.is_bulk or m.is_calendar_invite:
            continue
        others = _counterparts(m, principal)
        if not others or len(others) > DIRECT_MAX_RECIPIENTS:
            continue
        day = m.date.date().isoformat()
        for addr in others:
            if wanted is not None and addr not in wanted:
                continue
            prev = out.get(addr)
            if prev is None or day > prev.date:
                out[addr] = LastSeen(date=day, address=addr)
