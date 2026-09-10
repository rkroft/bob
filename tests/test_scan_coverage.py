"""Coverage tests — what the scan may claim about how much it read.

The module is `scan_coverage`, not `coverage`: `src/` goes on sys.path ahead of
site-packages, so a module named `coverage` here would shadow coverage.py the
moment anything runs pytest-cov.

HAP-309. Measured 2026-09-02: every connector query returns
`resultCountEstimate: "201"` — `subject:intro`, `subject:introduction`,
`subject:connecting`, `"connecting you"`, `"like to introduce"`, `label:Bob`,
all 201, and page 2 of `subject:intro` still carried a `nextPageToken`. It is a
sentinel for "200+", not a count.

So Bob can count what it **fetched** and never what **exists**. Cowork's own
model was caught turning that sentinel into *"About 201 threads landed in the
last 7 days"* — a stated fact softened with "About", which reads as rounding
rather than as not knowing. A model will do this by default, which is why the
refusal has to live in code.

The one-way rule these tests enforce: an absent or partial manifest must never
read as complete coverage, and no estimate of what exists may ever be printed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from scan_coverage import (  # noqa: E402
    COMPLETE, PARTIAL, UNKNOWN, Coverage, QueryCoverage, read_coverage,
)


def _manifest(tmp_path, queries, **extra):
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"queries": queries, **extra}))
    return path


# --- the default is ignorance, not completeness -------------------------------

def test_no_manifest_is_unknown_coverage_not_complete(tmp_path):
    """The dangerous direction. A scan with no manifest has no idea what it
    missed, and must not present that as having read everything."""
    cov = read_coverage(tmp_path / "absent.json")

    assert cov.status == UNKNOWN
    assert not cov.complete


def test_an_unreadable_manifest_is_unknown(tmp_path):
    path = tmp_path / "coverage.json"
    path.write_text("{half a page")

    assert read_coverage(path).status == UNKNOWN


@pytest.mark.parametrize("payload", ['[]', '"complete"', '{}',
                                     '{"queries": {}}', '{"queries": "all"}'])
def test_a_malformed_manifest_is_unknown(tmp_path, payload):
    path = tmp_path / "coverage.json"
    path.write_text(payload)

    assert read_coverage(path).status == UNKNOWN


def test_an_empty_query_list_is_unknown_rather_than_complete(tmp_path):
    """Vacuous truth is the trap: "every query was exhausted" is true of no
    queries at all, and would report COMPLETE for a net that never ran."""
    path = _manifest(tmp_path, [])

    assert read_coverage(path).status == UNKNOWN


# --- complete means every query ran out of pages ------------------------------

def test_all_queries_exhausted_is_complete(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
        {"query": "label:Bob", "pages": 1, "threads": 12, "exhausted": True},
    ])

    cov = read_coverage(path)

    assert cov.status == COMPLETE
    assert cov.threads_read == 424
    assert cov.pages_fetched == 4


def test_one_unexhausted_query_makes_the_whole_scan_partial(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
        {"query": "label:Bob", "pages": 1, "threads": 200,
         "exhausted": False},
    ])

    cov = read_coverage(path)

    assert cov.status == PARTIAL
    assert [q.query for q in cov.unexhausted] == ["label:Bob"]


def test_an_errored_query_makes_the_scan_partial_and_is_named(tmp_path):
    """An errored query means threads that exist and were not read. Dropping
    it would make a failed query indistinguishable from an empty one."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
        {"query": "label:Bob", "pages": 0, "threads": 0,
         "error": "connector timed out"},
    ])

    cov = read_coverage(path)

    assert cov.status == PARTIAL
    assert [q.query for q in cov.errored] == ["label:Bob"]
    assert "connector timed out" in cov.report()


def test_a_query_missing_the_exhausted_flag_is_not_assumed_exhausted(tmp_path):
    """Absent is not True. An agent that forgot to record it has told us
    nothing, and the honest reading of nothing is "not proven"."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412},
    ])

    assert read_coverage(path).status == PARTIAL


@pytest.mark.parametrize("flag", ["true", 1, "yes", "", None, 0])
def test_only_a_real_boolean_true_counts_as_exhausted(tmp_path, flag):
    """`bool("true")` and `bool(1)` are both True, and neither is the agent
    having actually recorded exhaustion. Same asymmetry as the durability
    marker: every wrong type falls toward "not proven"."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": flag},
    ])

    assert read_coverage(path).status == PARTIAL


# --- never report a denominator ----------------------------------------------

def test_an_estimate_in_the_manifest_is_never_reported(tmp_path):
    """resultCountEstimate is a sentinel, not a count. If the agent records it
    anyway, Bob must not launder it into the report."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True, "resultCountEstimate": "201"},
    ], total_estimated=9999)

    text = read_coverage(path).report()

    assert "201" not in text
    assert "9999" not in text


def test_the_report_says_what_was_read_never_what_exists(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
    ])

    text = read_coverage(path).report().lower()

    assert "read" in text
    for forbidden in ("of about", "estimated", "approximately", "% of"):
        assert forbidden not in text


def test_unknown_coverage_says_so_in_words(tmp_path):
    text = read_coverage(tmp_path / "absent.json").report().lower()

    assert "don't know" in text or "cannot" in text or "unknown" in text


def test_a_partial_report_names_every_query_it_could_not_finish(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": False},
        {"query": "subject:connecting", "pages": 1, "threads": 200,
         "exhausted": False},
        {"query": "label:Bob", "pages": 1, "threads": 3, "exhausted": True},
    ])

    text = read_coverage(path).report()

    assert "subject:intro" in text
    assert "subject:connecting" in text


# --- skipped lines: the count read_jsonl's docstring says we must report ------

def test_skipped_lines_make_coverage_partial(tmp_path):
    """A truncated line is a page half-written. `read_jsonl` skips it on
    purpose — its docstring says the count is the caller's to report, and
    until now no caller did."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_skipped(2)

    assert cov.status == PARTIAL
    assert "2" in cov.report()


def test_zero_skipped_lines_leaves_the_status_alone(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": True},
    ])

    assert read_coverage(path).with_skipped(0).status == COMPLETE


def test_skipped_lines_alone_are_still_reported_without_a_manifest(tmp_path):
    cov = read_coverage(tmp_path / "absent.json").with_skipped(3)

    assert cov.status == UNKNOWN
    assert "3" in cov.report()


# --- construction from nothing ------------------------------------------------

def test_an_empty_coverage_is_unknown():
    assert Coverage().status == UNKNOWN


def test_query_coverage_defaults_to_unproven():
    assert not QueryCoverage(query="subject:intro").exhausted


def test_the_unknown_report_does_not_reference_output_that_may_not_exist(
        tmp_path):
    """A blocked scan prints the coverage report and then stops. "Treat what
    follows as some of your introductions" is incoherent when nothing
    follows, so the caveat belongs to the caller that produced output."""
    text = read_coverage(tmp_path / "absent.json").report().lower()

    assert "what follows" not in text
    assert "unknown" in text


# --- the file is evidence, the manifest is a claim ----------------------------

def test_the_headline_count_comes_from_the_file_not_the_manifest(tmp_path):
    """Hand-run 2026-09-10: a manifest claiming 412+200 threads printed
    "read 612 threads" while the scan file held 3. The manifest is what the
    agent says it fetched; the JSONL is what actually arrived. Bob states the
    one it can verify.

    Overlap across queries (2 + 2 found, 3 distinct) is the legitimate shape,
    so no mismatch line fires here and the headline is the only count.
    """
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 2,
         "exhausted": True},
        {"query": "subject:introduction", "pages": 1, "threads": 2,
         "exhausted": True},
    ])

    text = read_coverage(path).with_threads_in_file(3).report()

    assert "read 3 threads" in text
    assert "4 threads" not in text          # the manifest's gross count


def test_a_discredited_claim_may_quote_the_manifests_number(tmp_path):
    """The one place a manifest-supplied number reaches stdout, and the framing
    is what makes it safe: "it claims N ... probably from a different run"."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
    ])

    text = read_coverage(path).with_threads_in_file(3).report()

    assert "claims 412" in text
    assert "read 3 threads" in text


def test_the_manifest_still_supplies_pages_and_query_names(tmp_path):
    """What the file cannot show: how many pages were fetched, which queries
    ran, which failed."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
    ])

    text = read_coverage(path).with_threads_in_file(3).report()

    assert "3 pages" in text
    assert "1 query" in text


def test_a_manifest_claiming_fewer_threads_than_the_file_holds_is_flagged(
        tmp_path):
    """Overlapping queries inflate the manifest's gross count, so it can
    exceed the de-duplicated file. It can never be *less* — if it is, the
    manifest belongs to a different run."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 2,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_threads_in_file(50)

    assert cov.status == PARTIAL
    assert "does not match" in cov.report().lower()


def test_overlap_across_queries_is_normal_and_not_flagged(tmp_path):
    """Fifteen overlapping queries find the same thread many times; de-dup is
    the point, not a discrepancy. No SINGLE query exceeds the file here."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 10,
         "exhausted": True},
        {"query": "subject:introduction", "pages": 1, "threads": 10,
         "exhausted": True},
        {"query": "connecting you", "pages": 1, "threads": 8,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_threads_in_file(12).with_expected(
        ["subject:intro", "subject:introduction", "connecting you"])

    assert cov.status == COMPLETE
    assert "different run" not in cov.report().lower()


def test_a_single_query_claiming_more_than_the_file_holds_is_flagged(tmp_path):
    """The dangerous direction, and the one this file's earlier fixture called
    normal. Retrieval dies after a few lines, a coverage.json from a bigger
    earlier run survives beside it, and COMPLETE gets printed over 1 of 412.
    Across queries, overlap explains gross > distinct. Within one query it
    cannot — one query does not return the same thread three times."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_threads_in_file(1)

    assert cov.status == PARTIAL
    assert "different run" in cov.report().lower()


def test_one_skipped_line_reads_as_singular(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": True},
    ])

    text = read_coverage(path).with_skipped(1).report()

    assert "1 line in the scan file could not be read and was skipped" in text


# --- nothing read is never complete ------------------------------------------

def test_a_manifest_cannot_certify_a_scan_that_read_nothing(tmp_path):
    """Reproduced 2026-09-10: a blocked scan printed its refusal and then
    "every query ran to the end of its results, so this is everything those
    queries can find" — over a read of zero threads. `miscounted` did not fire
    because 412 < 0 is false."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 3, "threads": 412,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_threads_in_file(0)

    assert cov.status == UNKNOWN
    assert "everything those queries can find" not in cov.report()


# --- the net is known code, so it IS a denominator ---------------------------
#
# The one denominator this path genuinely has. The mbox path reports "N of 15
# searches hit the limit"; the connector path threw that away along with the
# mail denominator, and only the mail one is actually unavailable.

def test_a_manifest_missing_queries_from_the_net_is_partial(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_threads_in_file(5).with_expected(
        ["subject:intro", "subject:introduction", "connecting you"])

    assert cov.status == PARTIAL
    assert "2 of the 3" in cov.report()


def test_the_missing_queries_are_named(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": True},
    ])

    text = read_coverage(path).with_threads_in_file(5).with_expected(
        ["subject:intro", "subject:introduction"]).report()

    assert "subject:introduction" in text


def test_running_the_whole_net_is_complete(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": True},
        {"query": "subject:introduction", "pages": 1, "threads": 2,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_threads_in_file(5).with_expected(
        ["subject:intro", "subject:introduction"])

    assert cov.status == COMPLETE


def test_extra_queries_beyond_the_net_do_not_make_it_partial(tmp_path):
    """A user or agent adding a query is not a coverage gap."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": True},
        {"query": "subject:handoff", "pages": 1, "threads": 1,
         "exhausted": True},
    ])

    cov = read_coverage(path).with_threads_in_file(5).with_expected(
        ["subject:intro"])

    assert cov.status == COMPLETE


def test_without_an_expected_net_no_query_completeness_claim_is_made(tmp_path):
    """Callers that do not supply the net get the old behaviour rather than a
    fabricated denominator."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5,
         "exhausted": True},
    ])

    text = read_coverage(path).with_threads_in_file(5).report()

    assert "of the" not in text


# --- wording ------------------------------------------------------------------

def test_one_thread_reads_as_singular(tmp_path):
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 1,
         "exhausted": True},
    ])

    text = read_coverage(path).with_threads_in_file(1).with_expected(
        ["subject:intro"]).report()

    assert "read 1 thread " in text or "read 1 thread." in text


def test_a_query_missing_its_flag_is_not_said_to_have_had_more_pages(tmp_path):
    """It lacked the flag. Saying "still had more pages" states as measured
    something nobody measured."""
    path = _manifest(tmp_path, [
        {"query": "subject:intro", "pages": 1, "threads": 5},
    ])

    text = read_coverage(path).with_threads_in_file(5).report()

    assert "still had more pages" not in text
    assert "not shown to have run to the end" in text
