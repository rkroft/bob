"""people.csv — the roster's first increment: who these people are, and how
many introductions each of them made.

All people here are invented placeholders (repo rule — never real contacts).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from intro_store import IntroRow  # noqa: E402
from people_store import (  # noqa: E402
    PEOPLE_COLUMNS, Person, build_people, read_people, write_people,
)

ME = "alice.tran@examplecorp.com"
DANA = "dana.okafor@example.com"
BEN = "ben.mercer@otherco.io"
CARA = "cara.silva@thirdco.com"


def row(tid, introducer, introduced, direction="inbound", names=None):
    return IntroRow(thread_id=tid, date="2026-01-01", direction=direction,
                    introducer=introducer, introduced=tuple(introduced),
                    subject="Intro", thread_link="", confidence=0.9)


# -- building the roster --------------------------------------------------


def test_one_row_per_person():
    people = build_people([row("1", DANA, [ME, BEN])], ME, {})
    assert sorted(p.address for p in people) == sorted([DANA, ME, BEN])


def test_counts_introductions_made_for_the_principal():
    rows = [row("1", DANA, [ME]), row("2", DANA, [ME]), row("3", BEN, [ME])]
    people = {p.address: p for p in build_people(rows, ME, {})}
    assert people[DANA].intros_for_you == 2
    assert people[BEN].intros_for_you == 1


def test_outbound_rows_do_not_count_as_intros_made_for_you():
    rows = [row("1", ME, [BEN, CARA], direction="outbound")]
    people = {p.address: p for p in build_people(rows, ME, {})}
    assert people[ME].intros_for_you == 0
    assert people[ME].intros_you_made == 1


def test_names_come_from_the_supplied_lookup():
    people = {p.address: p for p in build_people(
        [row("1", DANA, [ME])], ME, {DANA: "Dana Okafor"})}
    assert people[DANA].name == "Dana Okafor"


def test_a_person_with_no_known_name_falls_back_to_the_local_part():
    people = {p.address: p for p in build_people([row("1", DANA, [ME])], ME, {})}
    assert people[DANA].name == "Dana Okafor"       # derived from dana.okafor


def test_roster_is_ordered_by_intros_made_for_you():
    rows = [row("1", BEN, [ME]), row("2", DANA, [ME]), row("3", DANA, [ME])]
    assert [p.address for p in build_people(rows, ME, {})][:2] == [DANA, BEN]


def test_who_they_introduced_you_to_is_recorded():
    rows = [row("1", DANA, [ME, BEN]), row("2", DANA, [ME, CARA])]
    people = {p.address: p for p in build_people(rows, ME, {})}
    assert sorted(people[DANA].introduced_you_to) == sorted([BEN, CARA])


def test_the_principal_is_never_listed_among_who_they_introduced_you_to():
    people = {p.address: p for p in build_people([row("1", DANA, [ME, BEN])], ME, {})}
    assert ME not in people[DANA].introduced_you_to


def test_empty_input_is_an_empty_roster():
    assert build_people([], ME, {}) == []


# -- the file -------------------------------------------------------------


PERSON = Person(address=DANA, name="Dana Okafor", intros_for_you=3,
                intros_you_made=1, introduced_you_to=(BEN, CARA))


def test_round_trip_preserves_every_field(tmp_path):
    p = tmp_path / "people.csv"
    write_people([PERSON], p)
    assert read_people(p) == [PERSON]


def test_header_is_stable(tmp_path):
    p = tmp_path / "people.csv"
    write_people([PERSON], p)
    assert p.read_text().splitlines()[0] == ",".join(PEOPLE_COLUMNS)


def test_a_name_containing_a_comma_survives(tmp_path):
    p = tmp_path / "people.csv"
    write_people([Person(DANA, "Okafor, Dana", 1, 0, ())], p)
    assert read_people(p)[0].name == "Okafor, Dana"


def test_missing_file_reads_as_no_rows(tmp_path):
    assert read_people(tmp_path / "nope.csv") == []


def test_last_contact_survives_a_round_trip(tmp_path):
    """The roster's whole point is 'who have I lost touch with', so the date
    has to persist next to the person rather than being recomputed on every
    render -- the pass that produces it reads the whole mailbox."""
    p = tmp_path / "people.csv"
    write_people([Person("dana@example.com", "Dana", 2, 0, (),
                         last_contact="2026-03-14")], p)
    assert read_people(p)[0].last_contact == "2026-03-14"


def test_a_people_csv_written_before_last_contact_existed_still_reads(tmp_path):
    """522 rows are already on disk without this column. A roster pass that
    could not read them would silently start the corpus over."""
    p = tmp_path / "old.csv"
    p.write_text("address,name,intros_for_you,intros_you_made,"
                 "introduced_you_to,is_service\n"
                 "dana@example.com,Dana,2,0,,\n", encoding="utf-8")
    people = read_people(p)
    assert people[0].name == "Dana"
    assert people[0].last_contact == ""


def test_a_person_with_no_recorded_contact_says_so_rather_than_guessing(tmp_path):
    p = tmp_path / "people.csv"
    write_people([Person("dana@example.com", "Dana")], p)
    assert read_people(p)[0].last_contact == ""
