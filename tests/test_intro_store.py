"""intros.csv round-trip. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from intro_store import COLUMNS, IntroRow, read_intros, write_intros  # noqa: E402

ROW = IntroRow(
    thread_id="t1",
    date="2019-03-14",
    direction="inbound",
    introducer="dana.okafor@example.com",
    introduced=("alice.tran@examplecorp.com", "ben.mercer@otherco.io"),
    subject="Intro: Alice <> Ben",
    thread_link="https://mail.google.com/mail/u/0/#all/t1",
    confidence=0.82,
)


def test_round_trip_preserves_every_field(tmp_path):
    p = tmp_path / "intros.csv"
    write_intros([ROW], p)
    assert read_intros(p) == [ROW]


def test_header_is_written_and_stable(tmp_path):
    p = tmp_path / "intros.csv"
    write_intros([ROW], p)
    assert p.read_text().splitlines()[0] == ",".join(COLUMNS)


def test_multiple_introduced_survive_the_semicolon_join(tmp_path):
    p = tmp_path / "intros.csv"
    write_intros([ROW], p)
    assert read_intros(p)[0].introduced == (
        "alice.tran@examplecorp.com", "ben.mercer@otherco.io")


def test_empty_file_reads_as_no_rows(tmp_path):
    p = tmp_path / "intros.csv"
    write_intros([], p)
    assert read_intros(p) == []


def test_missing_file_reads_as_no_rows(tmp_path):
    assert read_intros(tmp_path / "nope.csv") == []


def test_subject_with_comma_survives_round_trip(tmp_path):
    """Subject containing comma must survive CSV quoting."""
    row = IntroRow(
        thread_id="t2",
        date="2019-03-14",
        direction="inbound",
        introducer="dana.okafor@example.com",
        introduced=("alice.tran@examplecorp.com",),
        subject="Intro: Alice, meet Ben",
        thread_link="https://mail.google.com/mail/u/0/#all/t2",
        confidence=0.75,
    )
    p = tmp_path / "intros.csv"
    write_intros([row], p)
    assert read_intros(p)[0].subject == "Intro: Alice, meet Ben"


def test_subject_with_double_quote_survives_round_trip(tmp_path):
    """Subject containing double quote must survive CSV escaping."""
    row = IntroRow(
        thread_id="t3",
        date="2019-03-14",
        direction="inbound",
        introducer="dana.okafor@example.com",
        introduced=("alice.tran@examplecorp.com",),
        subject='Re: "quick intro"',
        thread_link="https://mail.google.com/mail/u/0/#all/t3",
        confidence=0.85,
    )
    p = tmp_path / "intros.csv"
    write_intros([row], p)
    assert read_intros(p)[0].subject == 'Re: "quick intro"'


def test_subject_with_newline_survives_round_trip(tmp_path):
    """Subject containing newline must survive CSV quoting."""
    row = IntroRow(
        thread_id="t4",
        date="2019-03-14",
        direction="inbound",
        introducer="dana.okafor@example.com",
        introduced=("alice.tran@examplecorp.com",),
        subject="Intro: Alice\nmeet Ben",
        thread_link="https://mail.google.com/mail/u/0/#all/t4",
        confidence=0.90,
    )
    p = tmp_path / "intros.csv"
    write_intros([row], p)
    assert read_intros(p)[0].subject == "Intro: Alice\nmeet Ben"


def test_non_ascii_subject_survives_round_trip(tmp_path):
    """Subject with non-ASCII characters must survive round-trip."""
    row = IntroRow(
        thread_id="t5",
        date="2019-03-14",
        direction="inbound",
        introducer="dana.okafor@example.com",
        introduced=("alice.tran@examplecorp.com",),
        subject="Intro: Zoë <> Bjørn",
        thread_link="https://mail.google.com/mail/u/0/#all/t5",
        confidence=0.88,
    )
    p = tmp_path / "intros.csv"
    write_intros([row], p)
    assert read_intros(p)[0].subject == "Intro: Zoë <> Bjørn"
