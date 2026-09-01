"""The SessionStart hook. Invented placeholder people only (repo rule).

The hook fires in *every* project the user opens, so the tests that matter are
the ones asserting silence. It is run as a subprocess because its whole contract
is cwd, exit code and stdout.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "session_start.py"

HEADER = ("address,name,intros_for_you,intros_you_made,"
          "introduced_you_to,is_service,last_contact\n")


def run(cwd: Path):
    return subprocess.run([sys.executable, str(HOOK)], cwd=cwd,
                          capture_output=True, text=True, timeout=30)


def bob_folder(tmp_path: Path, rows: str) -> Path:
    (tmp_path / "intros.csv").write_text("", encoding="utf-8")
    (tmp_path / "people.csv").write_text(HEADER + rows, encoding="utf-8")
    return tmp_path


def stale_row(days: int, name: str = "Ada Placeholder") -> str:
    when = (date.today() - timedelta(days=days)).isoformat()
    return f"ada@example.invalid,{name},2,0,,,{when}\n"


def test_silent_outside_a_bob_folder(tmp_path):
    (tmp_path / "README.md").write_text("an unrelated project", encoding="utf-8")
    r = run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_when_only_one_of_the_two_files_is_present(tmp_path):
    (tmp_path / "people.csv").write_text(HEADER + stale_row(900), encoding="utf-8")
    r = run(tmp_path)
    assert r.stdout == ""


def test_speaks_when_someone_is_stale(tmp_path):
    r = run(bob_folder(tmp_path, stale_row(900)))
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert "Ada Placeholder" in payload["systemMessage"]
    assert "1 person" in payload["systemMessage"]      # not "1 people"


def test_silent_when_nothing_is_stale(tmp_path):
    r = run(bob_folder(tmp_path, stale_row(30)))
    assert r.stdout == ""


def test_silent_inside_the_quiet_window(tmp_path):
    folder = bob_folder(tmp_path, stale_row(900))
    assert json.loads(run(folder).stdout)               # first run speaks
    assert run(folder).stdout == ""                     # second, same day, does not


def test_speaks_again_once_the_quiet_window_has_passed(tmp_path):
    folder = bob_folder(tmp_path, stale_row(900))
    run(folder)
    old = (date.today() - timedelta(days=8)).isoformat()
    (folder / ".bob-last-spoke").write_text(old, encoding="utf-8")
    assert json.loads(run(folder).stdout)


def test_service_addresses_are_not_people(tmp_path):
    rows = "noreply@example.invalid,Example Digest,0,0,,true,2019-01-01\n"
    r = run(bob_folder(tmp_path, rows))
    assert r.stdout == ""


def test_a_blank_last_contact_is_not_found_rather_than_never(tmp_path):
    """The scan leaves last_contact empty; only the roster pass fills it.
    Empty must read as no evidence, not as infinite staleness."""
    r = run(bob_folder(tmp_path, "sol@example.invalid,Sol Placeholder,1,0,,,\n"))
    assert r.stdout == ""


def test_a_malformed_people_file_does_not_crash_the_session(tmp_path):
    (tmp_path / "intros.csv").write_text("", encoding="utf-8")
    (tmp_path / "people.csv").write_text("not,a,valid\x00header\n\x00\x00", encoding="utf-8")
    r = run(tmp_path)
    assert r.returncode == 0


def test_a_garbage_stamp_does_not_crash_the_session(tmp_path):
    folder = bob_folder(tmp_path, stale_row(900))
    (folder / ".bob-last-spoke").write_text("not a date", encoding="utf-8")
    assert run(folder).returncode == 0
