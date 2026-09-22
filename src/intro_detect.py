"""Introduction detection — principal-agnostic.

Decides whether an email thread is an introduction, and who occupies which seat.
There is no Rachel in this file: no hardcoded address, no personal rubric, no
Airtable. The caller supplies the principal.

Deliberately stdlib-only and free of any mail-provider types. It operates on the
normalized `Thread` / `Message` shapes in `mail_source.py`, which is the single
mail-access interface required by Product Definition §8.2 — so swapping Gmail for
a forwarding address or IMAP never reaches this module.

Two modes:
  - full        : headers + subject + body
  - metadata    : headers + subject only (no bodies)

The metadata mode exists to answer a real product question — whether Bob can ask
users for a much narrower Gmail scope. Score both and compare recall.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

from mail_source import Message, Thread, participants

Mode = Literal["full", "metadata"]

# --------------------------------------------------------------------------
# Signal weights.
#
# Tuned by hand against the patterns in the CRM's bob_intro_discovery.py plus
# the structural signal that catalog lacks. These are a starting point to be
# re-fit once scored against real ground truth — see tools/score.py.
# --------------------------------------------------------------------------

WEIGHTS: dict[str, float] = {
    "structural_dropout": 0.55,   # strongest, and language-independent
    # The same shape starting mid-thread, but weaker: delegation (an assistant,
    # a hiring manager) looks identical, so it needs a subject or wording too.
    "late_handoff": 0.35,
    "bcc_handoff": 0.45,          # "moving you to bcc" — almost unique to intros
    "subject_arrow": 0.40,        # "A <> B" is effectively dedicated intro syntax
    "subject_intro_only": 0.35,   # subject IS the word: "Intro", "Quick intro"
    "subject_pair_intro": 0.45,   # "Nadia/Alice intro" — two names + the word
    "subject_keyword": 0.20,
    "subject_separator": 0.15,    # "A / B", "A x B" — weaker, collides with normal subjects
    "body_handoff": 0.25,
    # Not enough alone, but enough with an intro subject or intro wording:
    # a three-person email titled "E-Intro" where nobody drops off was scored
    # 0.30 at 0.10 and missed (measured 2026-09-21).
    "three_party_open": 0.25,
    "subject_meet": 0.35,         # "Kai, meet Alice"
    # A later reply thanking someone for the introduction: independent of how
    # the introducer worded theirs. With three people it clears the bar.
    "thanked_intro": 0.25,
    # two-party shapes — see _shape_of()
    "request_subject": 0.45,      # "Intro to Nadia Okonjo?"
    "request_body": 0.40,         # "any chance you could introduce me to..."
    "forward_recovered": 0.35,    # 3-party shape recovered from quoted headers
}

# Disqualifiers. Any hit forces is_intro False regardless of score — precision
# matters more than recall for onboarding (product-definition 5.1).
HARD_NEGATIVE_SENDERS = re.compile(
    r"(no-?reply|do-?not-?reply|notifications?@|mailer-daemon|postmaster|"
    r"bounce|automated|alerts?@|digest@|newsletter|(?:^|[<\s])news@|"
    # meeting-notetaker bots: they mail *about* a meeting that already
    # happened, and their subjects carry the "A <> B" title verbatim.
    r"fireflies|otter\.ai|fathom\.video|read\.ai|avoma|sembly|grain\.co|"
    # scheduling tools: a booking notification names the meeting with the same
    # "A <> B" syntax an introduction uses, so it scores like a perfect intro.
    # Someone using your booking link is not an introduction, and the tool that
    # told you about it did not make one.
    r"vimcal|calendly|savvycal|cal\.com|hubspot|chilipiper|calendar-notification|"
    r"acuityscheduling|youcanbook|scheduleonce|meetings@)",
    re.I,
)

# Subject patterns that look like intros but aren't.
HARD_NEGATIVE_SUBJECT = re.compile(
    r"(unsubscribe|out of office|automatic reply|delivery status|"
    r"invitation:|accepted:|declined:|canceled:|cancelled:|updated invitation|"
    # "A <> B" is meeting-title syntax wherever a scheduling tool is in use.
    # Six of twelve candidates in the reference run were calendar artifacts, and a
    # meeting recap still scored 0.50 on the arrow alone.
    r"\bmeeting (?:recap|notes|transcript|summary)\b|"
    r"\b(?:recap|notes|transcript|recording) (?:of|from) your\b)",
    re.I,
)

# "Introduction to <the sender's own company>" is a cold pitch, not an
# introduction between two people. It scored 0.80 in the reference run — above the
# display bar — and in an investor's mailbox it is one of the commonest subject
# lines there is. The tell is computable: the thing named in the subject is the
# sender's own domain.
SELF_PITCH_SUBJECT = re.compile(r"\bintro(?:duction)?\s+(?:to|of)\s+(.{2,60})$", re.I)


def _is_self_pitch(first: Message) -> bool:
    m = SELF_PITCH_SUBJECT.search((first.subject or "").strip())
    if not m:
        return False
    named = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
    domain = first.from_addr.partition("@")[2].lower()
    # Every label but the TLD, so mail.fourthco.dev still matches. Short
    # labels are skipped — "mail", "x", "co" would collide with anything.
    for label in (re.sub(r"[^a-z0-9]", "", l) for l in domain.split(".")[:-1]):
        if len(label) >= 4 and named and (label in named or named in label):
            return True
    return False

MAX_PARTICIPANTS = 6  # above this it's a group thread, not an introduction

# Consumer mail providers. Two people sharing one of these share nothing else,
# so a shared domain there says nothing about being colleagues.
FREEMAIL = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "msn.com", "yahoo.com", "icloud.com", "me.com", "mac.com", "aol.com",
    "proton.me", "protonmail.com", "hey.com", "fastmail.com",
})


def _domain(addr: str) -> str:
    return addr.rpartition("@")[2].lower()

# "A <> B", and "A >< B" between capitalised names -- not "ugh >< deadline"
# or "</b><i>".
SUBJECT_ARROW = re.compile(r"<\s*>|[A-Z][\w'.&)-]*\s*>\s*<\s*[A-Z(]")
SUBJECT_KEYWORD = re.compile(
    # "connection" only as "a connection to/with someone": "VPN connection
    # issue" to two people is not an intro, "Acme connection to Alice" is.
    r"\b(intros?|introductions?|introducing|introduce|connecting|"
    r"connection\s+(?:to|with|between))\b",
    re.I,
)

# "Kai, meet Alice" / "Ben meet Alice Tran". Capitalised names around "meet"
# and nothing after them but punctuation. Scheduling uses the same words --
# "Let's meet Tuesday", "Team meet Up" -- so the lead word must not be a verb
# or pronoun and the second must not be a time word.
_MEET_LEAD_STOP = (r"(?!(?i:let['’]?s|let|can['’]?t|cant|can|could|come|team|we|"
                   r"should|will|would|must|to|i|you|re|everyone|folks|all|hi|"
                   r"hey|hello|lunch|coffee|dinner|everybody|guys|y['’]?all|"
                   r"welcome)\b)")
_MEET_TAIL_STOP = (r"(?!(?i:monday|tuesday|wednesday|thursday|friday|saturday|"
                   r"sunday|today|tomorrow|tonight|soon|up|next|later|again|this|"
                   r"the|january|february|march|april|may|june|july|august|"
                   r"september|october|november|december|mon|tue|tues|wed|weds|"
                   r"thu|thur|thurs|fri|sat|sun|tmrw|noon|now|asap|weekly|zoom|"
                   r"here)\b)")
SUBJECT_MEET = re.compile(
    r"^\s*(?:(?i:re|fwd?)\s*:\s*)*" + _MEET_LEAD_STOP + r"[A-Z][\w'-]+,?\s+"
    r"meet\s+" + _MEET_TAIL_STOP + r"[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?"
    r"\s*(?:[!.:(|\-–—].*)?$")

# " / " and " x " between two name-ish tokens. Requires spaces so it doesn't
# fire on dates, URLs, or "A/B test".
SUBJECT_SEPARATOR = re.compile(
    r"[A-Za-z]{2,}\s*(?:/|\+|&)\s*[A-Za-z]{2,}|"      # "Nadia/Alice", "A & B"
    r"[A-Za-z]{2,}\s+(?:x|and|to)\s+[A-Za-z]{2,}"      # "A x B", "Nadia to Alice"
)

BCC_HANDOFF = re.compile(
    r"\b(mov(?:ing|ed)\s+\w+\s+to\s+bcc|"
    r"\w+\s+to\s+bcc|"
    r"bcc'?(?:ing|d)\s+\w+|"
    r"mov(?:ing|ed)\s+you\s+to\s+bcc|"
    r"to\s+bcc\b)",
    re.I,
)

# --- two-party shapes -----------------------------------------------------
#
# The first scoring run against 100 hand-labeled threads showed the "3+
# participants" precondition was the single biggest recall killer: it
# disqualified 27 threads before scoring, and two of the shapes it threw away
# are real introductions.
#
#   request  — "Intro to Nadia Okonjo?"  (the principal ASKING for an intro;
#              the requester seat, and the C3 job. The third party is named in
#              the text and is not on the thread at all.)
#   forward  — "Fwd: Nadia to Alice"  (the 3-party shape is present, but in
#              the quoted headers rather than the visible ones.)

# "Intro to X?", "Introduction to X", "intro request", "Re: intro to X"
REQUEST_SUBJECT = re.compile(
    r"^\s*(?:re:|fwd?:)*\s*"
    r"(?:quick\s+|possible\s+|potential\s+)?"
    r"intro(?:duction)?\s+(?:to|w(?:ith)?/?)\s+[A-Z]",
    re.I,
)

REQUEST_BODY = re.compile(
    r"("
    r"(?:any\s+chance|would\s+you\s+be\s+(?:open|willing)|could\s+you|can\s+you|would\s+love)"
    r"[^.?!]{0,60}?(?:introduc|connect|intro)\s?[^.?!]{0,40}?\bme\b|"
    r"\b(?:an?|the)\s+intro(?:duction)?\s+to\b|"
    r"\bintro\s+me\s+to\b|"
    r"\bopen\s+to\s+(?:an?\s+)?intro"
    r")",
    re.I,
)

# "Intro", "Quick intro", "Intro!" — the subject IS the word, nothing else.
SUBJECT_INTRO_ONLY = re.compile(
    r"^\s*(?:re:|fwd?:)*\s*(?:\w+\s+)?intro(?:duction)?s?\s*[!.?]*\s*$", re.I
)

# Two names joined by a separator AND an intro word: "Nadia/Alice intro",
# "Fourthco/Alice Intro" — a company on one side is as common as a person.
# Very high precision: a subject in this shape is essentially never anything
# else.
SUBJECT_PAIR_INTRO = re.compile(
    r"[A-Za-z]{2,}\s*(?:/|\+|&|\bx\b|\band\b|\bto\b)\s*[A-Za-z]{2,}[^\\n]{0,40}?"
    r"\bintro(?:duction)?\b|"
    r"\bintro(?:duction)?\b[^\\n]{0,40}?[A-Za-z]{2,}\s*(?:/|\+|&)\s*[A-Za-z]{2,}",
    re.I,
)

FORWARD_MARKER = re.compile(
    r"(-+\s*forwarded message\s*-+|^\s*begin forwarded message|^\s*fwd?:)", re.I | re.M
)
QUOTED_HEADER = re.compile(r"^\s*(?:from|to|cc)\s*:\s*(.+)$", re.I | re.M)
_QUOTED_FROM = re.compile(r"\bfrom\s*:\s*[^<\n@]*?<?([\w.+-]+@[\w-]+\.[\w.-]+)", re.I)
_ADDR_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

BODY_HANDOFF = re.compile(
    r"("
    r"want(?:ed)?\s+to\s+introduce\s+you|"
    r"(?:would\s+)?like\s+to\s+introduce\s+you|"
    r"happy\s+to\s+introduce|glad\s+to\s+introduce|"
    r"introduce\s+you\s+(?:to|both)|intro\s+you\s+to|"
    r"want(?:ed)?\s+to\s+connect\s+you|connecting\s+you(?:\s+two|\s+both)?|"
    r"putting\s+you\s+(?:two\s+)?in\s+touch|put\s+you\s+in\s+touch|"
    r"you\s+two\s+should\s+(?:connect|meet|talk)|"
    r"thought\s+you\s+two|think\s+you\s+two|"
    r"you\s+(?:should|ought\s+to)\s+meet|"
    r"you\s+(?:two\s+)?(?:would|will|d)\s+hit\s+it\s+off|"
    r"meet\s+my\s+(?:friend|colleague|former\s+colleague)|"
    r"(?:connect(?:ing)?|introduce|introducing)\s+the\s+two\s+of\s+you|"
    r"this\s+email\s+is\s+to\s+connect\s+you"
    # Not "please meet": tried 2026-09-21 and dropped. Logistics uses it as
    # often as introductions do ("please meet us in the lobby", "please meet
    # Tuesday at 10"), and it found one intro in a 1,992-thread sample. The
    # "please meet" search stays; those threads count on other evidence.
    r")",
    re.I,
)


# "Thanks for the intro Dana!", "Thank you for the generous introduction",
# "thanks for introducing us". Not "thanks for the intro call", nor "the
# introduction to your product" -- those are a meeting and a pitch.
THANKED_INTRO = re.compile(
    r"\b(?:thanks|thank\s+you|thx)\b[^.!?\n]{0,25}?\bfor\s+"
    r"(?:(?:the|this|your|making\s+the)\s+)?(?:\w+\s+)?"
    r"(?:"
    # "...for the intro!", "...for the introduction, Dana", "...intro to Dana"
    r"(?:intro(?:duction)?|connecting\s+us)"
    # Ends there, or a name follows, or the sentence carries on past it --
    # but never into a meeting, a deck or a product.
    # No lowercase-name branch: measured on 4,522 real threads it matched
    # nothing at all, while re-admitting "thanks for the intro slides/doc".
    r"(?=\s*[.!?,;:)\]([-]|\s*$|\s+(?:to\s+)?(?-i:[A-Z])|\s+and\b)"
    r"(?!\s*-?\s*(?:call|meeting|session|deck|chat|video|course|offer)\b"
    r"|\s+(?:to\s+)?(?:the|this|that|our|your|a|an)\s+\w)"
    r"|"
    # "...for introducing us", "...for introducing me to Dana". A thing, not
    # a person, means it is about work: "for introducing this idea".
    r"introducing\s+(?:us\b|me\s+to\s+(?-i:[A-Z]))"
    r")",
    re.I)


@dataclass
class Detection:
    """One verdict about one thread."""

    thread_id: str
    is_intro: bool
    confidence: float
    signals: list[str] = field(default_factory=list)
    connector: str | None = None
    parties: tuple[str, ...] = ()
    principal_role: str | None = None      # "connector" | "party" | "requester" | None
    kind: str | None = None                # "handoff" | "request" | "forward"
    disqualified_by: str | None = None

    @property
    def is_confident(self) -> bool:
        """Onboarding only shows these. See product-definition 5.1."""
        return self.is_intro and self.confidence >= CONFIDENT_THRESHOLD


INTRO_THRESHOLD = 0.45
CONFIDENT_THRESHOLD = 0.70

# A thread with none of the three shapes (two visible participants, not a
# request, no recoverable forward) can still be a real introduction — but the
# evidence has to be near-unambiguous subject syntax, not prose. Generic handoff
# language in a 1:1 thread is usually about a *thing*: "wanted to introduce you
# to a book I'm reading". Shape doesn't gate scoring; it sets what counts.
SHAPELESS_ADMITS = frozenset({
    "subject_pair_intro", "subject_arrow",
    "request_subject", "request_body", "forward_recovered",
})


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------

def _structural_dropout(thread: Thread) -> bool:
    """The shape of an introduction, independent of language.

    Message 1 has three or more participants. In a later message the *sender of
    message 1* is gone while at least two of the others remain — the connector
    stepping back after making the handoff.

    This fires on intros written in any language, and on intros whose wording we
    have no pattern for. It is the signal bob_intro_discovery.py never had.
    """
    if len(thread.messages) < 2:
        return False

    first = thread.messages[0]
    opening = participants(first)
    if not (3 <= len(opening) <= MAX_PARTICIPANTS):
        return False

    sender = first.from_addr.lower()
    others = opening - {sender}

    for later in thread.messages[1:]:
        present = participants(later)
        if sender not in present and len(others & present) >= 2:
            return True
    return False


def _late_handoff(thread: Thread) -> int | None:
    """Index of a mid-thread handoff message, or None.

    A double opt-in often opens with two people ("OK if I introduce you to
    Ben?") and adds the third person in a later message. `_structural_dropout`
    reads only message 1, so that thread scored as a request and the scan
    dropped a completed introduction.

    This is the same shape measured from a later message: someone already on
    the thread sends a message that adds at least one new person, and in a
    later message that sender is gone while the new person and one other
    remain.

    Delegation has exactly this shape: an assistant, a hiring manager or an
    account exec is added and takes over. Two things keep it out. People added
    from the sender's own company are colleagues, not introductions, so that
    handoff is skipped. And the signal is weighted below the threshold, so a
    thread also needs an intro subject or intro wording to count.
    """
    seen: set[str] = set()
    for k, m in enumerate(thread.messages):
        present = participants(m)
        sender = m.from_addr.lower()
        new = present - seen
        home = _domain(sender)
        colleagues = home not in FREEMAIL and all(
            _domain(a) == home for a in new)
        if (k and new and sender in seen and not colleagues
                and 3 <= len(present) <= MAX_PARTICIPANTS):
            others = present - {sender}
            for later in thread.messages[k + 1:]:
                after = participants(later)
                if (sender not in after and new & after
                        and len(others & after) >= 2):
                    return k
        seen |= present
    return None


def _three_party_open(thread: Thread) -> bool:
    if not thread.messages:
        return False
    n = len(participants(thread.messages[0]))
    return 3 <= n <= MAX_PARTICIPANTS


def _subject_of(thread: Thread) -> str:
    return thread.messages[0].subject if thread.messages else ""


def _first_body(thread: Thread) -> str:
    for m in thread.messages:
        if m.body_text:
            return m.body_text
    return ""


def _disqualify(thread: Thread) -> str | None:
    """Hard negatives. Cheap, and they buy most of the precision."""
    if not thread.messages:
        return "empty_thread"

    first = thread.messages[0]

    if HARD_NEGATIVE_SENDERS.search(first.from_addr):
        return "automated_sender"
    if HARD_NEGATIVE_SUBJECT.search(first.subject or ""):
        return "automated_subject"
    if first.is_calendar_invite:
        return "calendar_invite"
    if first.is_bulk:                      # List-Unsubscribe / Precedence: bulk
        return "bulk_mail"
    if _forwarded_from_automated(thread):
        return "forwarded_bulk"
    if len(participants(first)) > MAX_PARTICIPANTS:
        return "group_thread"
    # Only where a handoff is impossible anyway. A genuine three-party intro
    # whose subject happens to name the sender's company stays scoreable.
    if (len(participants(first)) < 3 and _is_self_pitch(first)
            and _late_handoff(thread) is None):
        return "self_pitch"
    return None


# Forward prefixes in several mail clients and languages, after an optional
# "[EXT]" tag that company gateways add.
_FWD_SUBJECT = re.compile(
    r"^\s*(?:\[[^\]]{1,20}\]\s*)?(?:(?:re|aw|sv)\s*:\s*)*"
    r"(?:fwd?|fw|wg|tr|rv|enc)\s*:", re.I)


def _forwarded_from_automated(thread: Thread) -> bool:
    """A forward whose quoted sender is a mailing list or a no-reply address.

    "Fwd: Introducing <a product>" sent to two friends scores like an intro on
    its subject and its three people. The quoted From line gives it away.

    Only for a thread that is itself a forward, and never when the subject or
    the shape already says introduction: "Alice <> Ben -- see below" above a
    forwarded LinkedIn message is an intro with context.
    """
    first = thread.messages[0]
    subject = first.subject or ""
    body = first.body_text or ""
    # A forward by its subject, or by a forward marker right at the top of the
    # body when the prefix was deleted.
    if not (_FWD_SUBJECT.search(subject) or FORWARD_MARKER.search(body[:200])):
        return False
    # Only syntax nobody uses for a product name. "Intro to AI & ML" reads as
    # a pair intro, and "Intro" alone as an intro-only subject, so neither is
    # enough here.
    if (SUBJECT_ARROW.search(subject) or SUBJECT_MEET.search(subject)
            or _structural_dropout(thread)):
        return False
    marker = FORWARD_MARKER.search(body)
    if not marker:
        return False
    # Someone introducing people above the forward is an intro that happens
    # to quote something automated as context.
    above = body[:marker.start()]
    if BODY_HANDOFF.search(above) or BCC_HANDOFF.search(above):
        return False
    # The first quoted sender after the marker, by address. Not anchored to a
    # line start: the connector's snippet collapses the body onto one line.
    m = _QUOTED_FROM.search(body, marker.end(), marker.end() + 2000)
    return bool(m) and bool(HARD_NEGATIVE_SENDERS.search(m.group(1).lower()))


def _recovered_participants(thread: Thread) -> set[str]:
    """Addresses hiding in quoted/forwarded headers inside the body.

    A forwarded introduction is a two-party thread on the surface — but the
    original three-party shape is sitting in the quoted `From:` / `To:` block.
    Recovering it turns a thread the old precondition threw away into a normal
    handoff. Same mechanism helps when the principal was BCC'd and therefore
    doesn't appear in any visible header.
    """
    found: set[str] = set()
    for m in thread.messages:
        if not m.body_text:
            continue
        if not FORWARD_MARKER.search(m.body_text):
            continue
        # Only scan the top of the body — deep quote chains pull in unrelated
        # people from months of forwarding and wreck precision.
        head = m.body_text[:2000]
        for line in QUOTED_HEADER.findall(head):
            found.update(a.lower() for a in _ADDR_IN_TEXT.findall(line))
    return found


def _shape_of(thread: Thread, mode: Mode) -> tuple[str | None, list[str]]:
    """Which of the three introduction shapes this thread is, if any.

    Returns (kind, signals). kind None means it isn't one.
    """
    first = thread.messages[0]
    visible = participants(first)
    subject = first.subject or ""
    body = _first_body(thread) if mode == "full" else ""
    signals: list[str] = []

    # --- handoff: the classic three-party introduction --------------------
    if 3 <= len(visible) <= MAX_PARTICIPANTS:
        signals.append("three_party_open")
        if _structural_dropout(thread):
            signals.append("structural_dropout")
        return "handoff", signals

    # --- late handoff: an ask that turned into the introduction ----------
    # Checked before request: once the third person has been added and taken
    # over, the ask in message 1 is history, not the thread's outcome.
    if _late_handoff(thread) is not None:
        signals.append("late_handoff")
        return "handoff", signals

    # --- forward: three-party shape recovered from quoted headers ---------
    recovered = _recovered_participants(thread) if mode == "full" else set()
    if len(visible | recovered) >= 3:
        signals.append("forward_recovered")
        return "forward", signals

    # --- request: the principal asking someone for an introduction --------
    # The third party is named in the text and is not on the thread, so no
    # participant count will ever reveal this shape.
    if REQUEST_SUBJECT.search(subject):
        signals.append("request_subject")
    if body and REQUEST_BODY.search(body):
        signals.append("request_body")
    if signals:
        return "request", signals

    return None, []


# --------------------------------------------------------------------------
# Role assignment
# --------------------------------------------------------------------------

def _assign_roles(
    thread: Thread, principal: str | None, kind: str
) -> tuple[str | None, tuple[str, ...], str | None]:
    """Who connected whom, and which seat the principal occupies.

    For handoffs and forwards the connector is the sender of the opening
    message — right the large majority of the time.

    For a *request* the polarity flips: the principal is asking, so the person
    they're asking is the prospective connector and the principal is the
    requester. The third party is named in prose and has no address here, which
    is why they don't appear in `parties`. Extracting that name is a job for a
    model, not a regex — see the seam note in the module docstring.
    """
    if not thread.messages:
        return None, (), None

    first = thread.messages[0]
    if kind == "handoff" and len(participants(first)) < 3:
        # A late handoff: the connector is whoever made the handoff, not
        # whoever opened the thread with the ask.
        k = _late_handoff(thread)
        if k is not None:
            first = thread.messages[k]
    sender = first.from_addr.lower()
    visible = participants(first)
    p = principal.lower() if principal else None

    if kind == "request":
        # Prospective connector = whoever is being asked.
        asked = sorted(visible - {sender})
        connector = asked[0] if asked else None
        if p == sender:
            return connector, (sender,), "requester"
        # Someone asking the principal for an intro — the principal is the
        # prospective connector.
        return sender, tuple(sorted(visible - {sender})), ("connector" if p in visible else None)

    if kind == "forward":
        pool = visible | _recovered_participants(thread)
    else:
        pool = visible

    connector = sender
    parties = tuple(sorted(pool - {connector}))

    role: str | None = None
    if p:
        if p == connector:
            role = "connector"
        elif p in parties:
            role = "party"

    return connector, parties, role


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def detect(thread: Thread, principal: str | None = None, mode: Mode = "full") -> Detection:
    """Classify one thread.

    `principal` is the mailbox owner's address — used only to assign their seat,
    never to decide whether the thread is an introduction.
    """
    if (reason := _disqualify(thread)) is not None:
        return Detection(
            thread_id=thread.id, is_intro=False, confidence=0.0,
            disqualified_by=reason,
        )

    # Shape contributes signals; it does NOT gate scoring. Gating on it made
    # two-party threads unscoreable, so "Nadia/Alice intro" — about as clear a
    # subject line as exists — came back 0.00 in the second scoring run.
    kind, signals = _shape_of(thread, mode)

    subject = _subject_of(thread)

    if SUBJECT_ARROW.search(subject):
        signals.append("subject_arrow")
    if SUBJECT_PAIR_INTRO.search(subject):
        signals.append("subject_pair_intro")
    elif SUBJECT_INTRO_ONLY.search(subject):
        signals.append("subject_intro_only")
    elif SUBJECT_KEYWORD.search(subject):
        # Not both — "Intro" alone shouldn't also collect the generic keyword.
        signals.append("subject_keyword")
    if SUBJECT_SEPARATOR.search(subject):
        signals.append("subject_separator")
    if SUBJECT_MEET.search(subject):
        signals.append("subject_meet")

    # One subject line must not score three times. "Introduction to Acme"
    # matched request_subject (0.45), subject_keyword (0.20) AND
    # subject_separator (0.15) — three signals re-reading the same six words,
    # which is how a cold pitch reached 0.80. request_subject already prices
    # that phrasing; the other two are the same evidence counted again.
    if "request_subject" in signals:
        signals = [s for s in signals
                   if s not in ("subject_keyword", "subject_separator")]

    if mode == "full" and any(
            m.body_text and THANKED_INTRO.search(m.body_text)
            for m in thread.messages[1:]):
        signals.append("thanked_intro")

    if mode == "full":
        body = _first_body(thread)
        if "late_handoff" in signals:
            # The intro wording is in the handoff message and the replies to
            # it, not in the ask that opened the thread.
            k = _late_handoff(thread)
            body = "\n".join([body] + [m.body_text or ""
                                        for m in thread.messages[k:]])
        if BCC_HANDOFF.search(body):
            signals.append("bcc_handoff")
        if BODY_HANDOFF.search(body):
            signals.append("body_handoff")

    # Round BEFORE comparing. Float addition makes 0.10 + 0.35 == 0.4499999...,
    # so a thread scoring exactly at the threshold would fail the comparison
    # while displaying as 0.45. Caught by test_bare_intro_subject_clears_the_threshold.
    score = round(min(1.0, sum(WEIGHTS[s] for s in signals)), 3)
    is_intro = score >= INTRO_THRESHOLD

    if kind is None and not (set(signals) & SHAPELESS_ADMITS):
        return Detection(
            thread_id=thread.id, is_intro=False, confidence=score,
            signals=signals, disqualified_by="weak_two_party",
        )

    connector, parties, role = (
        _assign_roles(thread, principal, kind or "handoff") if is_intro else (None, (), None)
    )

    return Detection(
        thread_id=thread.id,
        is_intro=is_intro,
        confidence=score,
        signals=signals,
        connector=connector,
        parties=parties,
        principal_role=role,
        kind=(kind or "handoff") if is_intro else None,
        disqualified_by=None if is_intro else "below_threshold",
    )


def detect_all(
    threads: Iterable[Thread], principal: str | None = None, mode: Mode = "full"
) -> list[Detection]:
    return [detect(t, principal=principal, mode=mode) for t in threads]


def search_queries() -> Sequence[str]:
    """The retrieval net.

    Detection is the adjudicator, not the retriever — you cannot run it over a
    whole mailbox. These queries cast a wide, cheap net; `detect` decides.
    Ported from the CRM's bob_intro_discovery.py search catalog.
    """
    return (
        'subject:intro', 'subject:introduction', 'subject:introducing',
        'subject:connecting',
        # `subject:"<>"` was here and has been removed. Gmail ignores
        # punctuation, so it collapsed to an empty subject match and returned
        # the whole mailbox — 12,000+ threads against 25–1,124 for every other
        # query. A result cap hid that for months by making it look merely
        # popular. The "A <> B" convention is still caught, by the detector's
        # subject_arrow signal on threads the other queries surface: the net
        # retrieves, `detect` adjudicates, and only the second one needs to
        # understand punctuation.
        '"introduce you to"', '"wanted to introduce"', '"like to introduce"',
        '"connecting you"', '"putting you in touch"', '"put you in touch"',
        '"you two should"', '"intro you to"', '"thought you two"',
        '"moving you to bcc"', '"to bcc"',
        # Added 2026-09-21, each measured finding intros the rest missed on a
        # 1,992-thread sample. Gmail matches whole words: `subject:intro` does
        # not find "Intros". Tried and dropped: subject:meet, subject:connect
        # and the principal's first name -- 150+ threads of noise for one intro.
        'subject:intros', 'subject:introductions',
        '"please meet"', '"connect you with"', '"you should meet"', '"meet my"',
        '"put you two in touch"', '"introduce you two"',
        '"introduce the two of you"', '"e-intro"',
        # Added 2026-09-22: the thank-you reply, found in 6 of 9 intros no
        # other query matched. Gmail matches whole words, so each form is its
        # own query.
        '"for the intro"', '"for the introduction"', '"for introducing"',
        '"the two of you"',
    )
