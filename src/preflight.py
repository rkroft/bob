"""What Bob proves before it reads any mail.

HAP-312, narrowed to the case HAP-325 calls concrete: a pilot runs `/bob-scan`
in Cowork with no folder connected, waits through several hundred threads, and
receives output that dies with the session — under closing copy that says
"it is a file on your disk, not a session."

Three rules shape this module.

**Prove, don't assert.** A check that returns ok without checking is the same
lie in a smaller box. `data_dir` is proven by writing a probe file and reading
it back, not by `os.access`. `python` and `plugin` report the real values and
have no opinion.

**Durability cannot be proven from inside one session.** An ephemeral container
and a connected folder are indistinguishable while you are standing in either:
both exist, both are writable. So `UNKNOWN` is the honest answer, and the only
thing that retires it is the user saying so. They did the connecting; they are
the authority. Bob asks once, before reading anything, and records the answer.

A second proof was built and then removed (code review, 2026-09-10): if the
marker was written under a different container fingerprint, the folder outlived
a container. It reads as evidence and is not. A fresh sandbox over a
session-scoped volume satisfies it and still dies at session end, so it could
report `durable` for a folder about to be wiped — the one direction that
re-enables the loss this module exists to prevent. It also bought nothing, since
one confirmation retires the question permanently. The fingerprint is still
recorded, as diagnostics, and grants nothing.

**Every failure falls toward UNKNOWN.** Only `confirm_marker` ever writes
`confirmed`, and only `is True` is read as a yes, so no corruption, race,
partial write or wrong type can fabricate a confirmation. That asymmetry is the
whole safety property.

Nothing here infers the answer from a path. Cowork's connected-folder mount
point is unknown until HAP-341 runs, and a path heuristic written before that
would be a guess wearing a check's clothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

DURABLE = "durable"
UNKNOWN = "unknown"

MARKER = Path(".bob") / "durability.json"
PROBE_PREFIX = ".bob-probe-"
STALE_PROBE_SECONDS = 3600

#: The refusal. Spelled out here rather than left to the model, because the
#: model is the component that would paper over the gap.
REFUSAL = (
    "Bob has not confirmed that this folder survives the session, so nothing "
    "was read.\n\n"
    "On some surfaces the working folder is a temporary container that is "
    "wiped when the session ends. Bob cannot tell the difference from the "
    "inside — a temporary folder exists and is writable exactly like a real "
    "one — and a scan can take several hundred threads before there is "
    "anything to lose.\n\n"
    "Is this folder one you connected yourself, that will still be there "
    "tomorrow? Answer and Bob will remember; it does not ask twice."
)

_FINGERPRINT: Optional[str] = None


def as_dir(data_dir) -> Path:
    """Every path in this module goes through here.

    `plugin.json` defaults `data_dir` to `~/bob-network`, and the command
    markdown passes it inside double quotes, so the shell never expands it and
    a literal `~` arrives. Blocking on that would send a pilot into a setup
    loop that cannot help them. Output paths get the same treatment in `bob.py`
    — expanding in one place only would let the marker and the CSVs diverge.
    """
    return Path(str(data_dir)).expanduser()


# --- container identity (diagnostics only) ------------------------------------

def pid1_starttime(stat_text: str) -> str:
    """PID 1's start time out of `/proc/1/stat`.

    Field 22, but `split()[21]` is only field 22 when PID 1's name has no
    spaces: comm is parenthesized and may contain them, shifting every later
    index left. Seven spaces lands on `utime`, eight on `cutime` — both of
    which grow over one container's life, so two Bob processes in the same
    container would compute different fingerprints. Split after the last `)`.
    """
    fields = stat_text[stat_text.rindex(")") + 2:].split()
    return fields[19]


def container_fingerprint() -> str:
    """An id for the machine-or-container this process is running in.

    Recorded in the marker for diagnostics. It does not grant durability — see
    the module docstring for why that branch was removed.

    Cached, so two calls in one process always agree.
    """
    global _FINGERPRINT
    if _FINGERPRINT is None:
        parts = [platform.system(), socket.gethostname()]
        for path in ("/etc/machine-id", "/proc/sys/kernel/random/boot_id"):
            try:
                parts.append(Path(path).read_text(errors="replace").strip())
            except (OSError, ValueError):
                pass
        try:
            parts.append(pid1_starttime(
                Path("/proc/1/stat").read_text(errors="replace")))
        except (OSError, ValueError, IndexError):
            pass
        _FINGERPRINT = hashlib.sha256(
            "\x00".join(parts).encode("utf-8", "replace")).hexdigest()[:16]
    return _FINGERPRINT


# --- the marker ---------------------------------------------------------------

def read_marker(data_dir) -> Optional[dict]:
    """The marker, or None if it is absent, unreadable or not an object. A
    corrupt marker is treated as no marker — it must never read as a
    confirmation."""
    try:
        loaded = json.loads((as_dir(data_dir) / MARKER).read_text())
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _int(value) -> int:
    """A wrong-typed `runs` must not raise inside a scan's final step."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _str(value) -> Optional[str]:
    return value if isinstance(value, str) else None


def _write_marker(data_dir, marker: dict) -> dict:
    """Atomic. `write_text` truncates first, so a crash or a full disk mid-write
    would leave an empty marker, `read_marker` would return None, and a
    confirmation the user already gave would be gone — Bob would ask again,
    contradicting "it does not ask twice"."""
    path = as_dir(data_dir) / MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="durability-",
                              suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(marker, fh, indent=2, sort_keys=True)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return marker


def _carry(data_dir, fingerprint: Optional[str]) -> dict:
    existing = read_marker(data_dir) or {}
    return {
        "first_seen": _str(existing.get("first_seen")) or _now(),
        # Preserved on purpose: overwriting it with the current container would
        # destroy the record of where Bob first ran here.
        "fingerprint": (_str(existing.get("fingerprint"))
                        or fingerprint or container_fingerprint()),
        "last_run": _str(existing.get("last_run")),
        "runs": _int(existing.get("runs")),
        "confirmed": existing.get("confirmed") is True,
    }


def stamp_marker(data_dir, fingerprint: Optional[str] = None) -> dict:
    """Record that Bob ran here. Called after a scan, never before."""
    marker = _carry(data_dir, fingerprint)
    marker["last_run"] = _now()
    marker["runs"] += 1
    return _write_marker(data_dir, marker)


def confirm_marker(data_dir, fingerprint: Optional[str] = None) -> dict:
    """Record that the user confirmed this folder is theirs and will persist.

    Deliberately separate from `stamp_marker`: if a scan could confirm its own
    folder, the question would answer itself and never be asked.

    Refuses anything that is not already an absolute, writable directory.
    `_write_marker` mkdirs its parents, so an unguarded confirm would create
    the folder and then vouch for it — and on a genuine `data_dir` failure the
    model could ask the question, get a yes, and confirm the error away.
    """
    path = as_dir(data_dir)
    if not str(data_dir).strip():
        raise ValueError("no folder given — $CLAUDE_PLUGIN_OPTION_DATA_DIR is "
                         "unset or empty")
    if not path.is_absolute():
        raise ValueError(f"{path} is a relative path; Bob needs the real "
                         f"folder, not wherever it happens to be running")
    check = _check_data_dir(path)
    if not check.ok:
        raise ValueError(check.detail)

    marker = _carry(data_dir, fingerprint)
    marker["confirmed"] = True
    marker["confirmed_at"] = _now()
    return _write_marker(data_dir, marker)


def _now() -> str:
    """Offset-aware. A marker written in a UTC container and read on a Mac is
    otherwise silently misleading, and the field becomes load-bearing the
    moment anything compares two of them."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --- checks -------------------------------------------------------------------

@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    #: A failed non-fatal check is reported and does not stop the scan.
    fatal: bool = True

    def line(self) -> str:
        if self.ok:
            mark = "ok  "
        else:
            mark = "FAIL" if self.fatal else "warn"
        return f"  {mark}  {self.name}: {self.detail}"


@dataclass(frozen=True)
class Preflight:
    checks: List[Check]
    durability: str
    refusal: str

    def check(self, name: str) -> Optional[Check]:
        for c in self.checks:
            if c.name == name:
                return c
        return None

    @property
    def failed(self) -> bool:
        return any(not c.ok and c.fatal for c in self.checks)

    @property
    def blocked(self) -> bool:
        return self.failed or self.durability != DURABLE

    @property
    def exit_code(self) -> int:
        """1 = something is broken. 2 = nothing is broken and durability is
        unproven. The command markdown branches on this rather than on its own
        reading of the prose, which is the failure mode this whole slice is
        about."""
        if self.failed:
            return 1
        return 2 if self.durability != DURABLE else 0

    def report(self) -> str:
        lines = [c.line() for c in self.checks]
        lines.append(f"  durability: {self.durability}")
        if self.refusal:
            lines.append("")
            lines.append(self.refusal)
        return "\n".join(lines)


def _sweep_stale_probes(data_dir: Path) -> None:
    """A SIGKILL between write and unlink leaves a probe sitting in the user's
    visible folder next to intros.csv forever."""
    cutoff = time.time() - STALE_PROBE_SECONDS
    try:
        stale = list(data_dir.glob(PROBE_PREFIX + "*"))
    except OSError:
        return
    for probe in stale:
        try:
            if probe.stat().st_mtime < cutoff:
                probe.unlink()
        except OSError:
            pass


def _check_data_dir(data_dir: Path) -> Check:
    """Proven by writing. `os.access` answers a question about permission bits;
    this answers the question that matters, which is whether a write lands."""
    if not data_dir.is_dir():
        return Check("data_dir", False,
                     f"{data_dir} does not exist — run /bob-setup")
    _sweep_stale_probes(data_dir)
    # mkstemp, not the pid: container pids are small and collide across two
    # containers sharing one mount, which would make the read-back meaningless.
    try:
        fd, probe = tempfile.mkstemp(dir=str(data_dir), prefix=PROBE_PREFIX)
    except OSError as exc:
        return Check("data_dir", False, f"{data_dir} is not writable: {exc}")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("probe")
        if Path(probe).read_text() != "probe":
            return Check("data_dir", False,
                         f"{data_dir} did not read back what was written")
    except OSError as exc:
        return Check("data_dir", False, f"{data_dir} is not writable: {exc}")
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass
    return Check("data_dir", True, f"{data_dir} exists and is writable")


def _check_plugin(plugin_root) -> Check:
    """Non-fatal. The version is informational, and Cowork's layout is unknown
    until HAP-341 runs — a surprising CLAUDE_PLUGIN_ROOT must not hard-block
    every pilot with a message about a version file."""
    manifest = as_dir(plugin_root) / ".claude-plugin" / "plugin.json"
    try:
        version = json.loads(manifest.read_text()).get("version")
    except (OSError, ValueError) as exc:
        return Check("plugin", False, f"cannot read {manifest}: {exc}",
                     fatal=False)
    if not version:
        return Check("plugin", False, f"{manifest} names no version",
                     fatal=False)
    return Check("plugin", True, f"{version}", fatal=False)


def _check_last_run(marker: Optional[dict]) -> Check:
    """Informational, and `ok` regardless. "Bob has never run here" is a true
    report about a first run, not a fault — treating it as one would block
    every pilot's first scan, which is the only scan that matters."""
    if not marker or not _str(marker.get("last_run")):
        return Check("last_run", True, "never — Bob has not run here before",
                     fatal=False)
    return Check("last_run", True,
                 f"{marker['last_run']} ({_int(marker.get('runs'))} runs)",
                 fatal=False)


def preflight(data_dir, plugin_root=None,
              fingerprint: Optional[str] = None) -> Preflight:
    """Everything Bob can prove about where it is about to work.

    `plugin_root=None` skips the manifest check: callers outside a plugin
    install — the tests, the mbox path — have no manifest, and a missing one
    there is not a fault.
    """
    path = as_dir(data_dir)
    marker = read_marker(path)

    checks = [
        _check_data_dir(path),
        Check("python", True, ".".join(str(n) for n in sys.version_info[:3]),
              fatal=False),
    ]
    if plugin_root is not None:
        checks.append(_check_plugin(plugin_root))
    checks.append(_check_last_run(marker))

    # `is True` and nothing looser. bool("no") is True, and a marker that
    # merely parses is not a marker that means anything.
    durable = bool(marker) and marker.get("confirmed") is True
    durability = DURABLE if durable else UNKNOWN

    result = Preflight(checks=checks, durability=durability, refusal="")
    if durability == DURABLE or result.failed:
        # One report, one next action. Printing "this folder does not exist"
        # and "is this folder yours?" together invites answering the second,
        # which does nothing about the first.
        return result
    return Preflight(checks=checks, durability=durability, refusal=REFUSAL)
