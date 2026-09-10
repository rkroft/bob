"""Threads as the user's own Claude Gmail connector delivers them.

The third `mail_source`, alongside `mbox_source` and `gmail_source`. It exists
because Bob's Python cannot call the connector — the connector is a tool the
*agent* holds, not something a subprocess can reach. So the scan inverts: the
agent runs the retrieval net and writes what it gets to disk, and this module
reads that file. See `Connector Pivot.md` §2.1.

Input is JSONL: one `search_threads` thread object per line, exactly as the API
returned it, no reformatting. That shape is deliberate — a file the agent can
append to page by page, and one a human can `grep` when a scan looks wrong.

**Three fields cannot be populated from this source, and two of them matter.**
The connector returns parsed metadata, not headers, so there is nothing to read
them from. They are left at their defaults rather than guessed, because a
plausible-looking guess in a disqualifier is worse than a missing one:

- `is_bulk` — set from `List-Unsubscribe` / `Precedence: bulk` on the mbox path,
  and read by `intro_detect._disqualify`, `after.after_signal` and
  `last_contact`. Losing it removes one newsletter defence. The
  automated-sender check still fires (measured 2026-09-02: two newsletters
  rejected at 0.00 on `automated_sender`, not on bulk), so this is a precision
  risk to measure, not a known failure.
- `from_name` / `to_names` — **the connector returns bare addresses everywhere.**
  Not `"Dana Okafor <dana.okafor@example.com>"`, just `"dana.okafor@example.com"`, in both
  `search_threads` and `get_thread`. So `scan(names_out=...)` collects nothing
  and `best_name` has no candidates, which means the graph renders local-parts.
  This makes HAP-295 worse rather than better and needs its own answer.
- `is_calendar_invite` — `Content-Type: text/calendar` on the mbox path. Not
  inferred from the sender here: guessing it from an address list is the kind of
  quiet heuristic that later reads as a bug.

BCC is returned by the connector but `Message` has no field for it, and folding
it into `cc_addrs` would invent participants — a self-BCC on the principal's own
sent mail is common and would make them a third party to their own thread. It is
dropped, deliberately.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, Sequence

from mail_source import Message, Thread


def _date(raw: str | None) -> datetime | None:
    """`2026-08-30T21:42:42Z` -> datetime, or None.

    An unparseable date is dropped rather than defaulted: `Thread` sorts
    undated messages last and keeps their order, which is honest, whereas a
    substituted date would silently reorder a thread and change which message
    detection treats as the opener.
    """
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def thread_from_json(obj: dict) -> Thread:
    """One `search_threads` thread object -> a normalized Thread."""
    messages = [
        Message(
            id=m.get("id", ""),
            from_addr=m.get("sender", ""),
            to_addrs=list(m.get("toRecipients") or []),
            cc_addrs=list(m.get("ccRecipients") or []),
            subject=m.get("subject", ""),
            date=_date(m.get("date")),
            body_text=None,          # metadata mode — see the module docstring
        )
        for m in (obj.get("messages") or [])
    ]
    return Thread(id=obj.get("id", ""), messages=messages)


def read_jsonl(path: Path, on_skip: "Optional[Callable[[str], None]]" = None
               ) -> Iterator[dict]:
    """Yield one object per non-blank line, skipping malformed ones.

    A single truncated line — a page half-written when a scan was interrupted —
    must not cost the whole file. The count of skipped lines is the caller's to
    report; silence about them would be the failure this whole module is trying
    to avoid. `on_skip` is called once per skipped line so a caller can honour
    that; blank lines are not skips, they are just whitespace.

    `on_skip` receives the raw line, which carries addresses and subjects — it
    is fine for counting, but do not log it.
    """
    # errors="replace" rather than strict: a half-written multi-byte character
    # is the same interrupted-page failure as a broken brace, and it used to
    # kill the whole scan from inside this loop. Mangled text then fails the
    # JSON parse below and is COUNTED, which is the contract.
    with Path(path).open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if on_skip:
                    on_skip(line)
                continue


def load_counted(paths: Sequence[Path] | Path) -> tuple[list[Thread], int]:
    """Threads plus the number of lines that could not be used.

    De-duplication is not optional. The retrieval net runs fifteen overlapping
    queries, so the same thread arrives from several of them; without this the
    same introduction would be counted once per query that found it. A repeat
    is therefore not a loss and is not counted as a skip.

    An object with no thread id *is* counted: `load` has to drop it because it
    cannot be de-duplicated, and a silent drop is exactly what this module's
    docstring warns about.
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    seen: dict[str, Thread] = {}
    skipped = 0

    def note(_line):
        nonlocal skipped
        skipped += 1

    for p in paths:
        for obj in read_jsonl(Path(p), on_skip=note):
            if not isinstance(obj, dict):
                # Valid JSON of the wrong shape -- `[1,2]` parses and then
                # blows up in thread_from_json.
                skipped += 1
                continue
            t = thread_from_json(obj)
            if not t.id:
                skipped += 1
                continue
            if t.id not in seen:
                seen[t.id] = t
    return list(seen.values()), skipped


def load(paths: Sequence[Path] | Path) -> list[Thread]:
    """`load_counted` without the count, for callers that do not report it."""
    return load_counted(paths)[0]


class ConnectorSource:
    """A `MailSource` over files the agent already wrote.

    `search` is not implemented and must not be: retrieval happened before this
    module was reached. Raising is the point — a caller that tries to search
    here has misunderstood the split, and should hear so rather than get an
    empty list back.
    """

    def __init__(self, principal: str, paths: Sequence[Path] | Path) -> None:
        self._principal = principal
        threads, skipped = load_counted(paths)
        self._threads = {t.id: t for t in threads}
        #: Lines that could not be used. Reported, never swallowed.
        self.skipped_lines = skipped

    @property
    def threads_read(self) -> int:
        return len(self._threads)

    @property
    def blocked(self) -> bool:
        """Nothing usable came out of the file, so nothing was read.

        This is the distinction HAP-312 asks for as a return type: `0
        introductions` and `I could not look` must not be the same value. An
        empty scan file means the agent's retrieval wrote nothing — a failure —
        and reporting it as an empty mailbox would present a broken scan as a
        finished one. `granola-silence-is-not-evidence`, in Python.
        """
        return not self._threads

    def principal(self) -> str:
        return self._principal

    def search(self, query: str, limit: int = 200) -> Sequence[str]:
        raise NotImplementedError(
            "ConnectorSource does not search. The agent runs the retrieval net "
            "and writes the results; this reads them. See Connector Pivot.md §2.1."
        )

    def fetch(self, thread_ids: Iterable[str],
              include_bodies: bool = True) -> Sequence[Thread]:
        """Ids -> threads. `include_bodies` is accepted and ignored.

        It is ignored rather than rejected because the contract is shared with
        two sources that honour it. There are no bodies on this path at all, so
        honouring it would mean pretending a body was withheld when none was
        ever fetched.
        """
        return [self._threads[i] for i in thread_ids if i in self._threads]

    def all_threads(self) -> Sequence[Thread]:
        """Every thread the net wrote. The scan's entry point on this source."""
        return list(self._threads.values())
