"""Monthly buckets. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from intro_store import IntroRow  # noqa: E402
from timeline import month_buckets, year_ticks  # noqa: E402


def row(date, direction="inbound"):
    return IntroRow("t", date, direction, "dana@x.test", ("a@x.test",),
                    "Intro", "", 0.9)


def test_empty_months_are_present_not_skipped():
    """84 of Rachel's 191 months have no introductions. Dropping them would
    compress sixteen years and invent a rhythm that is not in the data."""
    b = month_buckets([row("2024-01-05"), row("2024-04-02")])
    assert [x["month"] for x in b] == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert [x["total"] for x in b] == [1, 0, 0, 1]


def test_the_two_directions_are_counted_separately():
    b = month_buckets([row("2024-01-05"), row("2024-01-09", "outbound")])
    assert b[0] == {"month": "2024-01", "inbound": 1, "outbound": 1, "total": 2}


def test_a_year_boundary_is_crossed_correctly():
    b = month_buckets([row("2023-11-01"), row("2024-02-01")])
    assert [x["month"] for x in b] == ["2023-11", "2023-12", "2024-01", "2024-02"]


def test_rows_without_a_date_are_ignored_not_bucketed():
    assert month_buckets([row(""), row("2024-01-01")])[0]["month"] == "2024-01"


def test_no_dated_rows_is_no_buckets():
    assert month_buckets([]) == []
    assert month_buckets([row("")]) == []


def test_a_single_month_is_one_bucket():
    assert len(month_buckets([row("2024-06-01")])) == 1


def test_year_ticks_mark_the_first_bucket_of_each_year():
    b = month_buckets([row("2023-11-01"), row("2024-02-01")])
    assert year_ticks(b) == [{"i": 0, "label": "2023"}, {"i": 2, "label": "2024"}]


# -- arrivals: people, not events ------------------------------------------

def irow(date, introducer, introduced, direction="inbound"):
    return IntroRow("t" + date, date, direction, introducer, tuple(introduced),
                    "Intro", "", 0.9)


ME = "me@x.test"


def test_a_person_arrives_once_however_often_they_reappear():
    """The introductions table lists events; this lists people. Seeing someone
    again in a later thread is not a second arrival."""
    from timeline import arrivals
    a = arrivals([irow("2024-01-01", "dana@x.test", ["sarah@x.test"]),
                  irow("2024-06-01", "marcus@x.test", ["sarah@x.test"])], ME)
    assert len(a) == 1
    assert a[0]["date"] == "2024-01-01"      # the FIRST sighting


def test_the_principal_never_arrives_in_their_own_network():
    from timeline import arrivals
    a = arrivals([irow("2024-01-01", "dana@x.test", [ME, "sarah@x.test"])], ME)
    assert [x["person"] for x in a] == ["sarah@x.test"]


def test_arrivals_are_newest_first():
    from timeline import arrivals
    a = arrivals([irow("2020-01-01", "d@x.test", ["old@x.test"]),
                  irow("2026-01-01", "d@x.test", ["new@x.test"])], ME)
    assert [x["person"] for x in a] == ["new@x.test", "old@x.test"]


def test_who_introduced_them_is_carried():
    from timeline import arrivals
    a = arrivals([irow("2024-01-01", "dana@x.test", ["sarah@x.test"])], ME)
    assert a[0]["by"] == "dana@x.test"


def test_undated_rows_produce_no_arrival():
    from timeline import arrivals
    assert arrivals([irow("", "d@x.test", ["a@x.test"])], ME) == []


def test_grouping_keeps_the_given_order():
    from timeline import arrivals, group_by_month
    a = arrivals([irow("2026-01-05", "d@x.test", ["a@x.test"]),
                  irow("2026-01-20", "d@x.test", ["b@x.test"]),
                  irow("2025-11-01", "d@x.test", ["c@x.test"])], ME)
    g = group_by_month(a)
    assert [m for m, _ in g] == ["2026-01", "2025-11"]
    assert len(g[0][1]) == 2


def test_columns_run_oldest_first():
    from timeline import arrival_columns
    c = arrival_columns([irow("2026-01-01", "d@x.test", ["new@x.test"]),
                         irow("2020-01-01", "d@x.test", ["old@x.test"])], ME)
    assert c[0]["month"] == "2020-01" and c[-1]["month"] == "2026-01"


def test_quiet_months_keep_their_place_in_the_strip():
    """A quiet year must look quiet. Closing up the empty months would make
    every period look equally busy."""
    from timeline import arrival_columns
    c = arrival_columns([irow("2024-01-01", "d@x.test", ["a@x.test"]),
                         irow("2024-04-01", "d@x.test", ["b@x.test"])], ME)
    assert [x["month"] for x in c] == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert [len(x["people"]) for x in c] == [1, 0, 0, 1]


def test_several_arrivals_stack_in_one_column():
    from timeline import arrival_columns
    c = arrival_columns([irow("2024-01-01", "d@x.test", ["a@x.test", "b@x.test"])], ME)
    assert len(c[0]["people"]) == 2
