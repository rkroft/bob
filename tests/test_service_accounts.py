"""Humans vs services. Invented placeholder people only (repo rule)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from intro_store import IntroRow  # noqa: E402
from people_store import build_people, is_service  # noqa: E402

ME = "alice.tran@examplecorp.com"


def row(introducer):
    return IntroRow("t", "2024-01-01", "inbound", introducer, (ME, "x@y.test"),
                    "Intro", "", 0.9)


# -- the rule --------------------------------------------------------------


def test_a_role_address_you_never_wrote_to_is_a_service():
    assert is_service("talent@jobs.example.com", contacted=set(), automated=True)


def test_a_role_address_you_have_written_to_is_a_person():
    """`hello@theirstartup.com` is very often a founder. Having written to them
    is the evidence that settles it — you do not reply to a mailer."""
    assert not is_service("hello@startup.test", contacted={"hello@startup.test"},
                          automated=True)


def test_an_ordinary_address_is_a_person_even_if_never_written_to():
    """Never replying is not evidence of a machine on its own — plenty of real
    introductions go unanswered, and calling those people services would be
    both wrong and insulting."""
    assert not is_service("dana.okafor@example.com", contacted=set(),
                          automated=False)


def test_a_person_at_a_normal_address_is_never_a_service():
    assert not is_service("nadia@secondco.io", contacted=set(), automated=False)


# -- it reaches the roster -------------------------------------------------


def test_the_roster_marks_services():
    people = {p.address: p for p in build_people(
        [row("talent@jobs.example.com"), row("nadia@secondco.io")], ME, {},
        contacted={"nadia@secondco.io"}, automated={"talent@jobs.example.com"})}
    assert people["talent@jobs.example.com"].is_service is True
    assert people["nadia@secondco.io"].is_service is False


def test_services_still_appear_in_the_roster():
    """They belong in the data. It is the leaderboard they do not belong in —
    there is nobody at talent@jobs.example.com to thank."""
    people = build_people([row("talent@jobs.example.com")], ME, {},
                          contacted=set(), automated={"talent@jobs.example.com"})
    assert any(p.address == "talent@jobs.example.com" for p in people)


def test_classification_defaults_to_person_when_nothing_is_known():
    """Called without the evidence arguments, nobody is called a machine."""
    people = build_people([row("talent@jobs.example.com")], ME, {})
    assert people[0].is_service is False
