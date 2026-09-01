"""Mbox implementation of the MailSource interface.

Reads a Google Takeout `.mbox` export off disk. No credentials, no network, no
provider account — which makes it the one mail source that works for a mailbox
Bob cannot be connected to, and the reproducible one: the corpus is a file, so a
scoring run can be repeated exactly.

Two jobs, in order of when they mattered:

1. Score detection against a second, uncurated mailbox (Product Definition §5.1)
   without adding a second connector.
2. Ship as the mail source for anyone not on Claude Code, where there is no
   verified Gmail connector to borrow (Plugin MVP §9).

**Threading.** Takeout preserves Gmail's own `X-GM-THRID`, so threads reassemble
exactly as Gmail grouped them. Where it is absent — a non-Takeout mbox — we fall
back to `References` / `In-Reply-To` chains, and finally to a normalized subject.
That last fallback is deliberately weak: it is better to under-thread (splitting
one conversation into two) than to over-thread, because the structural signal in
detection depends on who was on the *first* message.

**Memory.** A personal mailbox does not fit comfortably in RAM. `mailbox.mbox`
indexes lazily, so scanning reads one message at a time and retains only thread
ids. `prescan()` exists because the retrieval net is ~16 queries and there is no
reason to read the file sixteen times.
"""

from __future__ import annotations

import mailbox
import re
from email.header import decode_header, make_header
from email.message import Message as EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Sequence

from mail_source import Message, Thread

# Body text kept per message when scanning. Intro language ("I'd like to
# introduce you two") appears in the opening lines; a 20k prefix is generous
# for that and keeps a large mailbox scannable.
_BODY_SCAN_LIMIT = 20_000

_WS = re.compile(r"\s+")
_RE_PREFIX = re.compile(r"^\s*(re|fwd?|fw)\s*:\s*", re.I)


def _decode(raw: str | None) -> str:
    """RFC 2047 header -> text. Malformed headers degrade to their raw form
    rather than raising, because one bad header must not lose a mailbox."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _addrs(msg: EmailMessage, header: str) -> list[str]:
    return _named(msg, header)[0]


def _named(msg: EmailMessage, header: str) -> tuple:
    """(addresses, display names) — parallel lists.

    `getaddresses` has always returned both halves; the name half used to be
    discarded here, which is why every node in the graph read `mlee` instead
    of `Marcus Lee`.
    """
    vals = msg.get_all(header, [])
    pairs = [(name, addr) for name, addr
             in getaddresses([_decode(v) for v in vals]) if addr]
    return [a for _, a in pairs], [_decode(n) for n, _ in pairs]


def _body_text(msg: EmailMessage) -> str:
    """Prefer text/plain; fall back to stripped HTML. Attachments are skipped."""
    parts: list[str] = []
    html: list[str] = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if part.get_filename():
            continue
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        (parts if ctype == "text/plain" else html).append(text)
    if not parts and html:
        parts = [re.sub(r"<[^>]+>", " ", h) for h in html]
    return _WS.sub(" ", "\n".join(parts)).strip()


def _is_bulk(msg: EmailMessage) -> bool:
    if msg.get("List-Unsubscribe") or msg.get("List-Id"):
        return True
    return (msg.get("Precedence") or "").strip().lower() in {"bulk", "list", "junk"}


def _is_calendar(msg: EmailMessage) -> bool:
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_type() == "text/calendar":
            return True
    return False


def _refs(msg: EmailMessage) -> list[str]:
    out: list[str] = []
    for header in ("In-Reply-To", "References"):
        out.extend(re.findall(r"<[^>]+>", msg.get(header) or ""))
    return out


def _norm_subject(subject: str) -> str:
    prev = None
    s = subject.strip()
    while prev != s:                      # strip stacked "Re: Fwd: Re:"
        prev, s = s, _RE_PREFIX.sub("", s)
    return _WS.sub(" ", s).strip().lower()


class _Query:
    """The retrieval net speaks Gmail syntax (`intro_detect.search_queries()`),
    so this source has to understand the same dialect or it is not a drop-in.

    Supported, because it is all the net uses: `subject:term`,
    `subject:"phrase"`, `"phrase"`, and a bare term. Terms are matched
    case-insensitively as substrings — the net is meant to over-catch, and
    `detect` is the adjudicator.
    """

    _TOKEN = re.compile(r'(subject:)?("(?:[^"]*)"|\S+)')

    def __init__(self, raw: str) -> None:
        self.clauses: list[tuple[bool, str]] = []
        for field, value in self._TOKEN.findall(raw):
            needle = value[1:-1] if value.startswith('"') else value
            needle = needle.strip().lower()
            if needle:
                self.clauses.append((field == "subject:", needle))

    def matches(self, subject_lower: str, body_lower: str) -> bool:
        """All clauses must hit — the net's queries are single-clause today, and
        AND is the correct reading of Gmail's implicit conjunction."""
        return all(
            needle in (subject_lower if subject_only else f"{subject_lower}\n{body_lower}")
            for subject_only, needle in self.clauses
        )


class MboxSource:
    """MailSource over one or more `.mbox` files."""

    def __init__(self, path: str | Path, principal: str) -> None:
        p = Path(path)
        if p.is_dir():
            self.paths = sorted(p.glob("*.mbox"))
        else:
            # A missing path must fail here rather than scan an empty mailbox —
            # a silent zero-result run is indistinguishable from "no intros".
            self.paths = [p] if p.exists() else []
        if not self.paths:
            raise FileNotFoundError(f"no .mbox file at {p}")
        self._principal = principal.strip().lower()
        self._hits: dict[str, set[str]] = {}      # query -> thread ids

    # -- MailSource --------------------------------------------------------

    def principal(self) -> str:
        return self._principal

    def search(self, query: str, limit=None) -> Sequence[str]:
        if query not in self._hits:
            self.prescan([query])
        hits = sorted(self._hits[query])
        return hits if limit is None else hits[:limit]

    def fetch(self, thread_ids: Sequence[str], include_bodies: bool = True) -> Sequence[Thread]:
        # SORTED, not set order. Python randomises string hashing per process,
        # so iterating the set returned threads in a different order every run.
        # That order becomes the name-harvest order, which decides ties in
        # best_name — so a label could flip between rescans and make the graph
        # look broken. Determinism here is a correctness property, not tidiness.
        wanted = sorted(set(thread_ids))
        if not wanted:
            return []
        wanted_set = set(wanted)
        collected: dict[str, list[Message]] = {tid: [] for tid in wanted}
        for tid, raw in self._walk():
            if tid in wanted_set:
                collected[tid].append(self._to_message(raw, include_bodies))
        return [Thread(id=tid, messages=msgs) for tid, msgs in collected.items() if msgs]

    # -- one pass for the whole retrieval net -------------------------------

    def prescan(self, queries: Iterable[str]) -> None:
        """Evaluate many queries in a single read of the mailbox."""
        compiled = [(q, _Query(q)) for q in queries if q not in self._hits]
        if not compiled:
            return
        for q, _ in compiled:
            self._hits[q] = set()
        for tid, raw in self._walk():
            subject = _decode(raw.get("Subject")).lower()
            body = _body_text(raw)[:_BODY_SCAN_LIMIT].lower()
            for q, compiled_q in compiled:
                if compiled_q.matches(subject, body):
                    self._hits[q].add(tid)

    # -- internals ---------------------------------------------------------

    def _walk(self):
        """(thread_id, raw email) for every message, one file at a time."""
        ref_to_thread: dict[str, str] = {}
        subject_to_thread: dict[str, str] = {}
        for path in self.paths:
            box = mailbox.mbox(str(path), create=False)
            try:
                for key in box.iterkeys():
                    try:
                        raw = box[key]
                    except Exception:
                        continue          # a corrupt message must not end the scan
                    yield self._thread_id(raw, ref_to_thread, subject_to_thread), raw
            finally:
                box.close()

    @staticmethod
    def _thread_id(
        raw: EmailMessage,
        ref_to_thread: dict[str, str],
        subject_to_thread: dict[str, str],
    ) -> str:
        gm = (raw.get("X-GM-THRID") or "").strip()
        if gm:
            return gm                                   # Gmail's own grouping

        mid = (raw.get("Message-ID") or "").strip()
        for ref in _refs(raw):
            if ref in ref_to_thread:
                tid = ref_to_thread[ref]
                break
        else:
            tid = mid or f"subj:{_norm_subject(_decode(raw.get('Subject')))}"
        if mid:
            ref_to_thread[mid] = tid
        for ref in _refs(raw):
            ref_to_thread.setdefault(ref, tid)

        subject = _norm_subject(_decode(raw.get("Subject")))
        if subject and not _refs(raw) and not gm:
            tid = subject_to_thread.setdefault(subject, tid)
        return tid

    @staticmethod
    def _to_message(raw: EmailMessage, include_bodies: bool) -> Message:
        try:
            date = parsedate_to_datetime(raw.get("Date"))
        except Exception:
            date = None
        if date is not None and date.tzinfo is not None:
            date = date.replace(tzinfo=None)             # naive, to sort with peers
        from_addrs, from_names = _named(raw, "From")
        to_addrs, to_names = _named(raw, "To")
        cc_addrs, cc_names = _named(raw, "Cc")
        return Message(
            id=(raw.get("Message-ID") or "").strip(),
            from_addr=from_addrs[0] if from_addrs else "",
            from_name=from_names[0] if from_names else "",
            to_addrs=to_addrs,
            to_names=to_names,
            cc_addrs=cc_addrs,
            cc_names=cc_names,
            subject=_decode(raw.get("Subject")),
            date=date,
            body_text=_body_text(raw) if include_bodies else None,
            is_calendar_invite=_is_calendar(raw),
            is_bulk=_is_bulk(raw),
        )
