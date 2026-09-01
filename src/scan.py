"""Mailbox -> intros.csv rows.

Three steps, and the middle one is the only one with judgment in it:

  1. the retrieval net (`search_queries`) casts a wide, cheap net
  2. `detect` adjudicates every candidate
  3. surviving detections become rows

Detection is the adjudicator, not the retriever — it cannot be run over a whole
mailbox, which is why the net exists.

Only completed introductions are written. A *request* ("could you introduce me
to Nadia?") is a real thing the detector recognises, but no introduction has
happened yet and there is no edge to draw, so v1 counts them and drops them.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from after import after_signal
from intro_detect import detect, search_queries
from intro_store import IntroRow
from mail_source import Thread

# principal_role -> direction. "requester" is deliberately absent.
_DIRECTION = {"party": "inbound", "connector": "outbound"}


def _subject_of(thread: Thread) -> str:
    for m in thread.messages:
        if m.subject:
            return m.subject
    return ""


def _date_of(thread: Thread) -> str:
    for m in thread.messages:
        if m.date:
            return m.date.date().isoformat()
    return ""


def scan(
    source,
    limit_per_query: Optional[int] = None,
    link_for: Optional[Callable[[str], str]] = None,
    names_out: Optional[dict] = None,
    capped_out: Optional[list] = None,
    contacted_out: Optional[set] = None,
    automated_out: Optional[set] = None,
    progress=None,
) -> list[IntroRow]:
    """Detect introductions, and optionally harvest display names.

    `names_out` is filled with {address: [every name seen for it]} — the caller
    reduces that with `best_name`. Names are collected from every thread the
    retrieval net returned, not only the ones that turn out to be introductions:
    a person's name is worth keeping wherever it appears, and the net has
    already paid to fetch the thread.

    **`limit_per_query` is None by default, meaning exhaustive.** A cap is a
    silent lie about coverage: Gmail returns newest first, so a truncated search
    is indistinguishable from a mailbox with fewer introductions in it. Rachel's
    first real scan capped five of sixteen queries and reported 322
    introductions; uncapped it found 338, the difference being mail from 2011 to
    2016 that was simply never looked at. Capping is now something you opt into
    for a quick pass, and `capped_out` names every query it truncates so the
    result is never mistaken for the whole picture.

    `contacted_out` and `automated_out` gather the two pieces of evidence that
    decide whether there is a person behind an address (`people_store.
    is_service`): who the principal has written to, and whose mail is machine
    generated. Both are collected here because the scan is the only place that
    sees raw messages.
    """
    principal = source.principal()

    ids: list[str] = []
    seen: set[str] = set()
    for q in search_queries():
        found = source.search(q, limit=limit_per_query)
        if (capped_out is not None and limit_per_query is not None
                and len(found) >= limit_per_query):
            capped_out.append(q)
        for tid in found:
            if tid not in seen:
                seen.add(tid)
                ids.append(tid)

    if progress:
        # Say how much work is coming BEFORE it starts. The search is cheap;
        # the fetch is one call per thread and is where the minutes go.
        progress(len(ids))

    rows: list[IntroRow] = []
    for thread in source.fetch(ids, include_bodies=True):
        for m in thread.messages:
            if contacted_out is not None and m.from_addr == principal:
                # Written TO by the principal. Being a recipient of their own
                # mail proves nothing; sending to someone proves a lot.
                contacted_out.update(a for a in (*m.to_addrs, *m.cc_addrs) if a)
            if (automated_out is not None and m.from_addr
                    and (m.is_bulk or m.is_calendar_invite)):
                automated_out.add(m.from_addr)

        if names_out is not None:
            for m in thread.messages:
                # Skip machine-generated mail. Calendar RSVPs and bulk sends
                # carry whatever name the *system* holds and repeat it dozens of
                # times, which lets an automated form outvote the name someone
                # actually signs their mail with.
                if m.is_calendar_invite or m.is_bulk:
                    continue
                for addr, name in [(m.from_addr, m.from_name),
                                   *zip(m.to_addrs, m.to_names),
                                   *zip(m.cc_addrs, m.cc_names)]:
                    if addr and name:
                        names_out.setdefault(addr, []).append(name)
        d = detect(thread, principal=principal)
        if not d.is_intro:
            continue
        # A request is not a completed introduction in either seat: when the
        # principal asks for one, principal_role is "requester" (absent from
        # _DIRECTION, so it's already dropped below) — but when someone else
        # asks THE PRINCIPAL for an intro, _assign_roles hands the principal
        # the "connector" role, which _DIRECTION maps to "outbound". That
        # would record a request-for-an-intro as an intro the principal made,
        # naming the requester as the person introduced — self-contradictory,
        # since nothing has actually happened yet. Drop both shapes here,
        # keyed on kind rather than role, before the direction lookup.
        if d.kind == "request":
            continue
        direction = _DIRECTION.get(d.principal_role or "")
        if direction is None:
            continue
        # Principal is deliberately retained: the connector→principal edge is the fact
        # this product exists to surface. For inbound intros, that edge is essential.
        introduced = tuple(p for p in d.parties if p and p != d.connector)
        if not introduced:
            continue
        # What became of it, read from the same thread while it is in hand
        # (§4.6). The scan is the only place that sees raw messages, so if the
        # evidence is not taken here it cannot be recovered without re-reading
        # the whole mailbox. `observed=True` records that we looked -- which is
        # what keeps a silent thread distinguishable from an unscanned one.
        a = after_signal(thread, principal)
        rows.append(IntroRow(
            thread_id=thread.id,
            date=_date_of(thread),
            direction=direction,
            introducer=d.connector or "",
            introduced=introduced,
            subject=_subject_of(thread),
            thread_link=link_for(thread.id) if link_for else "",
            confidence=d.confidence,
            observed=True,
            replied=a.principal_replied,
            they_replied=a.other_replied,
            met=a.meeting_invited,
            first_reply=a.first_reply,
            last_exchange=a.last_exchange,
        ))
    rows.sort(key=lambda r: (r.date, r.thread_id))
    return rows


def scan_to_rows(source, **kw) -> Sequence[IntroRow]:   # readable alias
    return scan(source, **kw)
