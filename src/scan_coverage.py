"""How much of the mailbox a scan actually read, and what it may claim.

HAP-309. Measured 2026-09-02: every connector query returns
`resultCountEstimate: "201"` — `subject:intro`, `subject:introduction`,
`subject:connecting`, `"connecting you"`, `"like to introduce"`, `label:Bob`,
all 201, and page 2 of `subject:intro` still carried a `nextPageToken`. It is a
sentinel for "200+", not a count.

So Bob can count what it **fetched** and never what **exists**. There is no
denominator on this path, and this module's job is to make that structural
rather than remembered.

The failure it prevents was seen in the wild, unprompted: asked to search mail,
Cowork's own model reported *"About 201 threads landed in the last 7 days."* It
turned the sentinel into a stated fact and softened it with "About", which reads
as rounding rather than as not knowing. A capable model does this by default, so
the refusal cannot live in an instruction — it lives here, in a type.

`scan.py` already has this discipline for the mbox/Gmail path: capping is
"a silent lie about coverage", and `capped_out` names every truncated query.
This is the same rule for a source where retrieval happened in the agent, so
the evidence has to arrive as a file rather than as a return value.

**The manifest.** The agent writes `coverage.json` next to the JSONL as it
pages:

    {"queries": [
      {"query": "subject:intro", "pages": 3, "threads": 412, "exhausted": true},
      {"query": "label:Bob",     "pages": 0, "threads": 0, "error": "timed out"}
    ]}

`exhausted` means `nextPageToken` was absent on the last page — the query ran
out of results rather than out of patience.

**Everything unproven reads as unproven.** No manifest, an unreadable one, an
empty query list, a missing `exhausted`, or an `exhausted` that is any truthy
value other than real `True` — all of these produce PARTIAL or UNKNOWN, never
COMPLETE. Same asymmetry as `preflight`'s durability marker, for the same
reason: the direction that costs the user is the one where Bob overstates what
it saw.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional, Tuple

COMPLETE = "complete"
PARTIAL = "partial"
UNKNOWN = "unknown"

MANIFEST_NAME = "coverage.json"


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class QueryCoverage:
    """One query's share of the net.

    `exhausted` defaults to False: a query nobody recorded an answer for has
    not been shown to have finished.
    """
    query: str
    pages: int = 0
    threads: int = 0
    exhausted: bool = False
    error: Optional[str] = None


@dataclass(frozen=True)
class Coverage:
    queries: Tuple[QueryCoverage, ...] = field(default_factory=tuple)
    skipped_lines: int = 0
    #: False when there was no manifest to read. Distinct from "a manifest that
    #: says nothing was read" — one is ignorance, the other is a measurement.
    manifest_found: bool = False
    #: Distinct threads actually present in the scan file. The manifest is what
    #: the agent says it fetched; this is what arrived. Where they disagree,
    #: this is the one Bob states, because it is the one Bob can verify.
    threads_in_file: Optional[int] = None
    #: The net that was supposed to run — `intro_detect.search_queries()`. Known
    #: code, so unlike the mail count it IS a legitimate denominator: the mbox
    #: path already reports "N of 15 searches". Empty means no claim is made.
    expected: Tuple[str, ...] = field(default_factory=tuple)

    def with_threads_in_file(self, count: int) -> "Coverage":
        """The de-duplicated thread count `ConnectorSource` actually loaded."""
        return replace(self, threads_in_file=max(0, _int(count)))

    def with_expected(self, queries) -> "Coverage":
        """The net the retrieval step was told to run."""
        return replace(self, expected=tuple(
            q.strip() for q in (queries or []) if isinstance(q, str) and q.strip()))

    def with_skipped(self, skipped: int) -> "Coverage":
        """The count `connector_source.read_jsonl` drops on the floor. Its own
        docstring says reporting it is the caller's job."""
        return replace(self, skipped_lines=max(0, _int(skipped)))

    @property
    def errored(self) -> List[QueryCoverage]:
        return [q for q in self.queries if q.error]

    @property
    def unexhausted(self) -> List[QueryCoverage]:
        return [q for q in self.queries if not q.exhausted and not q.error]

    @property
    def threads_claimed(self) -> int:
        """The manifest's gross count, summed over queries. Inflated by design:
        fifteen overlapping queries find the same thread many times. Never the
        headline — see `threads_read`."""
        return sum(q.threads for q in self.queries)

    @property
    def threads_read(self) -> int:
        """What Bob may state. The file when it is known, and only otherwise
        the manifest's claim."""
        if self.threads_in_file is not None:
            return self.threads_in_file
        return self.threads_claimed

    @property
    def miscounted(self) -> bool:
        """The manifest claims fewer threads than the file holds.

        Overlap can only push the gross count *above* the de-duplicated file,
        never below it, so this is a provable contradiction rather than a
        threshold someone picked: the manifest belongs to a different run.
        """
        if self.threads_in_file is None or not self.queries:
            return False
        return self.threads_claimed < self.threads_in_file

    @property
    def missing(self) -> List[str]:
        """Queries in the net that the manifest never mentions.

        Extra queries beyond the net are not a gap — someone adding a search
        is not a coverage hole — so this is one-directional.
        """
        if not self.expected or not self.queries:
            return []
        ran = {q.query for q in self.queries}
        return [q for q in self.expected if q not in ran]

    @property
    def short_of_the_file(self) -> bool:
        """A single query claims more threads than the whole file holds.

        The dangerous direction, and the realistic one: retrieval dies after a
        few lines and a `coverage.json` from a larger earlier run survives
        beside the truncated JSONL, so COMPLETE gets printed over 1 of 412.

        Across queries, overlap explains a gross count above the de-duplicated
        file. Within one query it cannot — a query does not return the same
        thread three times — so no threshold has to be invented. (Paging drift
        could repeat one thread mid-run; over-flagging in that direction costs
        a caveat, under-flagging costs the user their network.)
        """
        if self.threads_in_file is None or not self.queries:
            return False
        return max((q.threads for q in self.queries), default=0) > self.threads_in_file

    @property
    def pages_fetched(self) -> int:
        return sum(q.pages for q in self.queries)

    @property
    def status(self) -> str:
        if not self.manifest_found or not self.queries:
            # Vacuous truth is the trap: "every query was exhausted" is true of
            # no queries at all, and would report COMPLETE for a net that
            # never ran.
            return UNKNOWN
        if self.threads_in_file == 0:
            # Nothing arrived, so the manifest describes some other run. It
            # cannot certify a scan that read nothing -- reproduced 2026-09-10,
            # where a blocked scan printed its refusal and then "this is
            # everything those queries can find".
            return UNKNOWN
        if (self.errored or self.unexhausted or self.skipped_lines
                or self.miscounted or self.short_of_the_file or self.missing):
            return PARTIAL
        return COMPLETE

    @property
    def complete(self) -> bool:
        return self.status == COMPLETE

    def report(self) -> str:
        """What the scan is allowed to say. Counts of what was fetched, names of
        what was not finished, and no denominator anywhere."""
        lines: List[str] = []
        if self.status == UNKNOWN:
            # No reference to output here. A blocked scan prints this report
            # and then stops, and "treat what follows as some of your
            # introductions" is incoherent when nothing follows. The caveat
            # belongs to the caller that actually produced a result.
            lines.append(
                "Coverage: unknown. There is no record of which queries ran, "
                "so Bob cannot say how much of the mailbox was read.")
        else:
            lines.append(
                f"Coverage: read {self.threads_read:,} "
                f"{'thread' if self.threads_read == 1 else 'threads'} over "
                f"{self.pages_fetched:,} "
                f"{'page' if self.pages_fetched == 1 else 'pages'} across "
                f"{len(self.queries)} "
                f"{'query' if len(self.queries) == 1 else 'queries'}.")
            if self.status == COMPLETE:
                lines.append(
                    "   Every query ran to the end of its results, so this is "
                    "everything those queries can find.")

        if self.unexhausted:
            # "was not shown to have run to the end", not "still had more
            # pages": a query that merely lacked the flag was never measured,
            # and asserting the stronger thing states as fact something nobody
            # checked.
            lines.append(
                f"   {len(self.unexhausted)} "
                f"{'query' if len(self.unexhausted) == 1 else 'queries'} "
                f"{'was' if len(self.unexhausted) == 1 else 'were'} not shown "
                f"to have run to the end, so older mail may not have been "
                f"read:")
            for q in self.unexhausted:
                lines.append(f"     {q.query}")
        if self.missing:
            lines.append(
                f"   {len(self.missing)} of the {len(self.expected)} searches "
                f"Bob uses did not run at all:")
            for q in self.missing:
                lines.append(f"     {q}")
        if self.errored:
            lines.append(
                f"   {len(self.errored)} "
                f"{'query' if len(self.errored) == 1 else 'queries'} failed, "
                f"so whatever they would have found is missing:")
            for q in self.errored:
                lines.append(f"     {q.query} — {q.error}")
        if self.skipped_lines:
            one = self.skipped_lines == 1
            lines.append(
                f"   {self.skipped_lines} {'line' if one else 'lines'} in the "
                f"scan file could not be read and "
                f"{'was' if one else 'were'} skipped — most likely a page "
                f"half-written when a previous run stopped.")
        if self.miscounted or self.short_of_the_file:
            lines.append(
                f"   The record does not match the file: it claims "
                f"{self.threads_claimed:,} threads but the scan file holds "
                f"{self.threads_in_file:,}. It is probably from a different "
                f"run, so the queries named here may not be the ones that "
                f"produced this data.")
        # Deliberately absent: any total, estimate or percentage of what
        # exists. The connector cannot supply one, and resultCountEstimate is
        # a "200+" sentinel that reads as a number.
        return "\n".join(lines)


def _query_from_json(obj) -> Optional[QueryCoverage]:
    if not isinstance(obj, dict):
        return None
    query = obj.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    error = obj.get("error")
    return QueryCoverage(
        query=query.strip(),
        pages=_int(obj.get("pages")),
        threads=_int(obj.get("threads")),
        # `is True` and nothing looser. bool("true") and bool(1) are both True,
        # and neither is the agent having recorded exhaustion.
        exhausted=obj.get("exhausted") is True,
        error=error.strip() if isinstance(error, str) and error.strip()
        else None,
    )


def read_coverage(path) -> Coverage:
    """The manifest at `path`, or an UNKNOWN coverage if it is absent,
    unreadable, or not the shape this module expects.

    Never raises. A scan that has already read the mailbox must not die because
    its bookkeeping file is malformed — it must report that it does not know.
    """
    try:
        loaded = json.loads(Path(str(path)).read_text())
    except (OSError, ValueError):
        return Coverage()
    if not isinstance(loaded, dict):
        return Coverage()
    raw = loaded.get("queries")
    if not isinstance(raw, list):
        return Coverage()
    queries = tuple(q for q in (_query_from_json(o) for o in raw) if q)
    if not queries:
        return Coverage()
    return Coverage(queries=queries, manifest_found=True)


def beside(scan_files) -> Optional[Path]:
    """Where the manifest lives: `coverage.json` next to the first scan file."""
    for f in ([scan_files] if isinstance(scan_files, (str, Path))
              else list(scan_files or [])):
        return Path(str(f)).expanduser().parent / MANIFEST_NAME
    return None
