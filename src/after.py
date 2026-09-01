"""What happened after the introduction.

Plugin MVP §4.6 sorts every introduction into three buckets — **took hold**,
**never landed**, **can't tell** — and the tests it names are about the thread:
did the principal reply, did the other party, was a meeting scheduled. All of
that is already in the `Thread` the scan reads. It was simply never kept, which
is why `/bob-thanks` had no signal to sort on.

**No message count is stored, deliberately.** §4.6 requires evidence to be shown
as events and spans, never tallies — *"a message count reads as surveillance
wherever it appears, including in the prompt."* A number that is never computed
cannot leak into copy, so the rule is enforced by the shape of this dataclass
rather than by a note asking people to be careful.

Nothing here decides a bucket. This module reports what it saw; `triage()`
turns that into a bucket, and only where the evidence supports one.
"""

from __future__ import annotations

from dataclasses import dataclass

from mail_source import Thread, normalize_addr


@dataclass(frozen=True)
class After:
    """Evidence about one introduction, from its own thread.

    Every field is a fact or a date. `""` means *not observed* — never *did not
    happen*: Bob reads one channel and cannot assert absence (§4.6).
    """
    principal_replied: bool = False
    other_replied: bool = False
    meeting_invited: bool = False
    first_reply: str = ""        # when the principal first answered
    last_exchange: str = ""      # the end of the span, whoever wrote last


def _day(m) -> str:
    return m.date.date().isoformat() if m.date else ""


def after_signal(thread: Thread, principal: str, intro_index: int = 0) -> After:
    """Read one thread for what became of the introduction in it.

    `intro_index` is where the introduction sits; everything at or before it is
    setup, and only what follows is evidence about it. It defaults to the first
    message because that is where an intro almost always is, and because a
    caller that does not know should not be forced to guess.

    **Bulk mail is not an exchange**, in either direction. A newsletter landing
    in the thread is not the introduction taking hold, and the principal's own
    blast is not them replying — the same rule the roster applies to last
    contact, for the same reason.
    """
    me = normalize_addr(principal or "")
    replied = other = meeting = False
    first_reply = last_exchange = ""

    for m in thread.messages[intro_index + 1:]:
        if m.is_calendar_invite:
            # A meeting got scheduled in the thread. §4.6 wants a meeting to
            # upgrade "never landed" from a guess to a finding, and this is
            # that evidence without needing the Calendar connector at all.
            meeting = True
            continue
        if m.is_bulk:
            continue
        when = _day(m)
        if when:
            last_exchange = when
        if m.from_addr == me:
            if not replied:
                replied, first_reply = True, when
        else:
            other = True

    return After(principal_replied=replied, other_replied=other,
                 meeting_invited=meeting, first_reply=first_reply,
                 last_exchange=last_exchange)


#: The three buckets of Plugin MVP §4.6. Two are actionable; the third is the
#: instruction to say nothing at all.
TOOK_HOLD, NEVER_LANDED, CANT_TELL = "took_hold", "never_landed", "cant_tell"


def triage(after: After | None) -> str:
    """Which bucket one introduction falls in.

    `None` means **no evidence was captured** — a row from a scan that predates
    after-signal, or a thread that could not be read. That is `cant_tell`, and
    it is emphatically not `never_landed`: reading "we have no data" as "you
    ignored them" is the absence-assertion §4.6 forbids, and it would draft a
    late-reply email about an introduction that may have gone perfectly well.

    Everything else follows §4.6's table. A meeting counts on its own, because
    the introduction plainly landed whether or not anyone wrote back in-thread.
    """
    if after is None:
        return CANT_TELL
    if after.principal_replied or after.meeting_invited:
        return TOOK_HOLD
    return NEVER_LANDED
