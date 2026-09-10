"""Preflight tests — the checks that run before Bob reads any mail.

HAP-312's concrete first case: a pilot runs /bob-scan in Cowork with no folder
connected, waits through several hundred threads, and receives output that dies
with the session. The scan must refuse before reading, and it must never claim
persistence it has not proven.

The load-bearing property here is that durability cannot be asserted. Within a
single session an ephemeral container and a connected folder are
indistinguishable — both exist, both are writable. Only the user knows, so
`unknown` is the honest answer until they say otherwise, and every corruption,
race and wrong type below must fail toward `unknown` rather than toward
`durable`. A false `durable` is what silently re-enables the loss.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from preflight import (  # noqa: E402
    DURABLE, UNKNOWN, confirm_marker, container_fingerprint, preflight,
    read_marker, stamp_marker,
)


# --- data dir: proven by writing, not by asking -------------------------------

def test_writable_data_dir_passes_and_leaves_no_probe_behind(tmp_path):
    result = preflight(tmp_path, plugin_root=None)
    check = result.check("data_dir")

    assert check.ok
    assert list(tmp_path.iterdir()) == []


def test_unwritable_data_dir_fails(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        check = preflight(locked, plugin_root=None).check("data_dir")
        assert not check.ok
        assert "writ" in check.detail.lower()
    finally:
        locked.chmod(0o700)


def test_missing_data_dir_fails_rather_than_being_created(tmp_path):
    absent = tmp_path / "not-there"

    check = preflight(absent, plugin_root=None).check("data_dir")

    assert not check.ok
    assert not absent.exists()


# --- durability: unknown until the user says otherwise -----------------------

def test_durability_is_unknown_on_a_first_run(tmp_path):
    assert preflight(tmp_path, plugin_root=None).durability == UNKNOWN


def test_durability_stays_unknown_inside_one_container(tmp_path):
    """The trap. A second scan in the same session finds its own marker, and a
    marker you wrote yourself proves nothing about surviving a wipe."""
    stamp_marker(tmp_path, fingerprint="container-a")

    result = preflight(tmp_path, plugin_root=None, fingerprint="container-a")

    assert result.durability == UNKNOWN


def test_outliving_a_container_is_not_proof_of_durability(tmp_path):
    """Dropped on purpose (code review, 2026-09-10). A fresh sandbox over a
    session-scoped volume satisfies "survived a container" and still dies at
    session end, so this branch could report durable for a folder that is
    about to be wiped — the one direction that re-enables the loss. The
    fingerprint stays recorded as diagnostics and grants nothing."""
    stamp_marker(tmp_path, fingerprint="container-a")

    result = preflight(tmp_path, plugin_root=None, fingerprint="container-b")

    assert result.durability == UNKNOWN


@pytest.mark.parametrize("contents", [
    "{not json at all",                        # unparseable
    "[]",                                      # parses, wrong type
    '"durable"',                               # parses, wrong type
    '{"confirmed": "no"}',                     # bool("no") is True
    '{"confirmed": 1}',                        # truthy, not True
    '{"confirmed": "false"}',                  # truthy, not True
    '{"fingerprint": 12345}',                  # != any string
    '{"fingerprint": ["a"]}',                  # != any string
    '{"first_seen": "2026-09-10T00:00:00"}',   # no verdict at all
])
def test_a_malformed_marker_never_claims_durability(tmp_path, contents):
    """Every corruption and every wrong type must fail toward UNKNOWN. A
    marker that parses is not a marker that means anything, and the dangerous
    direction is a false `durable` — it silently re-enables the data loss."""
    marker = tmp_path / ".bob" / "durability.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(contents)

    result = preflight(tmp_path, plugin_root=None, fingerprint="container-b")

    assert result.durability == UNKNOWN


def test_stamping_twice_keeps_the_original_fingerprint(tmp_path):
    """Diagnostics: the record of where Bob first ran in this folder. Grants
    no durability, but overwriting it would lose that history."""
    stamp_marker(tmp_path, fingerprint="container-a")
    stamp_marker(tmp_path, fingerprint="container-b")

    assert read_marker(tmp_path)["fingerprint"] == "container-a"


def test_stamping_counts_runs(tmp_path):
    stamp_marker(tmp_path, fingerprint="container-a")
    stamp_marker(tmp_path, fingerprint="container-b")

    assert read_marker(tmp_path)["runs"] == 2


def test_container_fingerprint_is_stable_within_a_process():
    assert container_fingerprint() == container_fingerprint()


# --- durability: the user is the authority, and answers once ------------------
#
# The only proof. An earlier design also accepted "the marker outlived a
# container fingerprint", which was removed in review — see
# test_outliving_a_container_is_not_proof_of_durability. The person who
# connected the folder knows whether they connected it, so Bob asks once and
# records the answer.

def test_a_confirmed_folder_is_durable(tmp_path):
    confirm_marker(tmp_path, fingerprint="container-a")

    result = preflight(tmp_path, plugin_root=None, fingerprint="container-a")

    assert result.durability == DURABLE
    assert not result.blocked


def test_confirmation_is_the_only_thing_that_proves_durability(tmp_path):
    confirm_marker(tmp_path, fingerprint="container-a")

    result = preflight(tmp_path, plugin_root=None, fingerprint="container-b")

    assert result.durability == DURABLE


def test_an_unconfirmed_marker_is_not_a_confirmation(tmp_path):
    """stamp_marker runs after every scan; only confirm_marker records an
    answer. Conflating them would let a scan confirm its own folder, and the
    question would never be asked."""
    stamp_marker(tmp_path, fingerprint="container-a")

    result = preflight(tmp_path, plugin_root=None, fingerprint="container-a")

    assert result.durability == UNKNOWN


def test_confirming_preserves_the_run_count(tmp_path):
    stamp_marker(tmp_path, fingerprint="container-a")
    confirm_marker(tmp_path, fingerprint="container-a")

    assert read_marker(tmp_path)["runs"] == 1
    assert read_marker(tmp_path)["confirmed"] is True


# --- the verdict the command acts on ------------------------------------------

def test_unproven_durability_blocks_the_scan(tmp_path):
    result = preflight(tmp_path, plugin_root=None)

    assert result.blocked
    assert "folder" in result.refusal.lower()


def test_proven_durability_does_not_block(tmp_path):
    confirm_marker(tmp_path, fingerprint="container-a")

    result = preflight(tmp_path, plugin_root=None, fingerprint="container-b")

    assert not result.blocked
    assert result.refusal == ""


def test_a_failed_check_blocks_even_when_durability_is_proven(tmp_path):
    confirm_marker(tmp_path, fingerprint="container-a")
    absent = tmp_path / "not-there"

    result = preflight(absent, plugin_root=None, fingerprint="container-b")

    assert result.blocked


# --- python and plugin version: reported, not claimed -------------------------

def test_python_version_is_the_real_one(tmp_path):
    detail = preflight(tmp_path, plugin_root=None).check("python").detail

    assert ".".join(str(n) for n in sys.version_info[:3]) in detail


def test_plugin_version_comes_from_the_manifest(tmp_path):
    root = tmp_path / "plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "bob", "version": "9.9.9"}))

    check = preflight(tmp_path, plugin_root=root).check("plugin")

    assert check.ok
    assert "9.9.9" in check.detail


def test_a_missing_manifest_fails_rather_than_guessing(tmp_path):
    check = preflight(tmp_path, plugin_root=tmp_path / "nope").check("plugin")

    assert not check.ok
    assert "9.9.9" not in check.detail


def test_plugin_check_is_skipped_when_no_root_is_supplied(tmp_path):
    """Callers outside a plugin install (tests, the mbox path) have no
    manifest, and a missing one there is not a fault."""
    assert preflight(tmp_path, plugin_root=None).check("plugin") is None


# --- last run: reported, never a gate ----------------------------------------

def test_last_run_is_reported_when_a_marker_exists(tmp_path):
    stamp_marker(tmp_path, fingerprint="container-a")

    check = preflight(tmp_path, plugin_root=None,
                      fingerprint="container-b").check("last_run")

    assert check.ok


def test_last_run_says_never_on_a_first_run(tmp_path):
    """Informational, not a gate. A first run has no previous run by
    definition, and failing it would block the only scan that matters."""
    check = preflight(tmp_path, plugin_root=None).check("last_run")

    assert check.ok
    assert "never" in check.detail.lower()


# --- the report a human reads -------------------------------------------------

def test_report_names_every_check_and_the_verdict(tmp_path):
    text = preflight(tmp_path, plugin_root=None).report()

    assert "data_dir" in text
    assert "python" in text
    assert UNKNOWN in text


def test_report_carries_the_refusal_when_blocked(tmp_path):
    result = preflight(tmp_path, plugin_root=None)

    assert result.refusal in result.report()


# --- confirmation must not conjure the folder it confirms ---------------------

def test_confirming_a_missing_folder_is_refused_and_creates_nothing(tmp_path):
    """`_write_marker` mkdirs its parents, so an unguarded confirm would
    create the folder and then vouch for it. Worse, on a genuine data_dir
    failure the model could ask the question, get a yes, and confirm the error
    away."""
    absent = tmp_path / "not-there"

    with pytest.raises(ValueError):
        confirm_marker(absent)

    assert not absent.exists()


def test_confirming_a_relative_folder_is_refused(tmp_path):
    """An unset $CLAUDE_PLUGIN_OPTION_DATA_DIR arrives as "", which Path turns
    into "." — a confirmation written into whatever the cwd happens to be."""
    with pytest.raises(ValueError):
        confirm_marker(Path(""))


def test_confirming_an_unwritable_folder_is_refused(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        with pytest.raises(ValueError):
            confirm_marker(locked)
    finally:
        locked.chmod(0o700)


# --- one report, one next action ----------------------------------------------

def test_a_hard_failure_suppresses_the_durability_question(tmp_path):
    """Otherwise the report says "this folder does not exist" AND "is this
    folder yours?" in the same breath, and answering the second does nothing
    about the first."""
    result = preflight(tmp_path / "not-there", plugin_root=None)

    assert result.blocked
    assert result.refusal == ""
    assert "does not exist" in result.report()


def test_an_unreadable_manifest_does_not_block_the_scan(tmp_path):
    """The plugin version is informational. Cowork's layout is unknown until
    HAP-341 runs, so a surprising CLAUDE_PLUGIN_ROOT must not hard-block every
    pilot with a message about a version file."""
    confirm_marker(tmp_path)

    result = preflight(tmp_path, plugin_root=tmp_path / "nope")

    assert not result.check("plugin").ok
    assert not result.blocked


# --- paths -------------------------------------------------------------------

def test_a_literal_tilde_is_expanded(tmp_path, monkeypatch):
    """plugin.json defaults data_dir to `~/bob-network`, and the markdown uses
    it inside double quotes, so the shell never expands it. Blocking on a
    literal `~` would send the pilot into a setup loop that cannot help."""
    monkeypatch.setenv("HOME", str(tmp_path))

    check = preflight("~", plugin_root=None).check("data_dir")

    assert check.ok
    assert "~" not in check.detail


# --- timestamps ---------------------------------------------------------------

def test_marker_timestamps_carry_an_offset(tmp_path):
    """A marker written in a UTC container and read on a Mac is otherwise
    silently misleading."""
    confirm_marker(tmp_path)

    assert read_marker(tmp_path)["confirmed_at"][-6] in "+-"


# --- /proc/1/stat parsing -----------------------------------------------------

def test_pid1_starttime_survives_a_comm_containing_spaces(tmp_path):
    """`split()[21]` is field 22 only when PID 1's name has no spaces. With
    spaces it drifts onto utime/cutime, which GROW over one container's life —
    two Bob processes would then disagree and read each other's markers as
    having survived a boundary."""
    from preflight import pid1_starttime

    plain = "1 (systemd) S 0 1 1 0 -1 4194560 " + " ".join(
        str(n) for n in range(8, 23)) + " rest"
    spaced = plain.replace("(systemd)", "(my init proc)")

    assert pid1_starttime(plain) == pid1_starttime(spaced)
