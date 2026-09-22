"""What the release audit can ever see is decided here.

The generator reads the maintainer's contact list and writes the terms the
audit matches. All people below are invented stand-ins for contacts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest  # noqa: E402

# tools/private_denylist.py is not shipped (release.py SHIP_FILES), so in the
# public export there is nothing to test here and the suite must still run.
private_denylist = pytest.importorskip("private_denylist")
terms = private_denylist.terms


def _terms(name, email=""):
    return terms([{"Name": name, "Email": email}])


def test_a_distinctive_name_becomes_a_term():
    assert "Quillan" in _terms("Quillan Stark")


def test_an_ordinary_word_name_is_not_a_term_on_its_own():
    """A contact called Bright or Hunter must not block every release."""
    out = _terms("Bright Hunter")
    assert "Bright" not in out and "Hunter" not in out


def test_every_two_part_name_becomes_a_phrase():
    assert "Bright Hunter" in _terms("Bright Hunter")
    assert "Quillan Stark" in _terms("Quillan Stark")


def test_the_fixture_cast_is_never_a_term():
    assert _terms("Dana Okafor", "dana.okafor@example.com") == {"Dana Okafor"}


def test_a_first_last_local_part_becomes_a_term():
    assert "quillan.stark" in _terms("Quillan Stark", "Quillan.Stark@example.com")


def test_a_company_domain_becomes_a_term_but_freemail_does_not():
    out = _terms("Quillan Stark", "quillan@quillanworks.test, qs@gmail.com")
    assert "quillanworks" in out and "gmail" not in out


def test_a_single_name_makes_no_phrase():
    assert _terms("Quillan") == {"Quillan"}
