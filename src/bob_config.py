"""Where Bob's folder is and whose mail it reads, without plugin settings.

Claude Code hands a plugin its settings as `$CLAUDE_PLUGIN_OPTION_*`. Cowork
never does (anthropics/claude-code#39125, closed not planned) -- the values
arrive empty, and an empty folder used to become `Path("")`, which is the
working directory, silently.

So the folder is the anchor. Whoever runs Bob names it (Claude Code's setting,
or the folder the user connected in Cowork), and the address is saved inside
it once, in `bob.json`, because the folder is the one thing that outlives a
Cowork session.

Precedence. Folder: given > plugin setting, and the setting is consulted only
when the folder was passed blank (a failed substitution) -- a command run with
no folder at all never adopts the user's real one. Address: given > saved >
plugin setting, because `bob setup` is how a user corrects it and Claude Code
always exports the setting.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

CONFIG = "bob.json"
ENV_DIR = "CLAUDE_PLUGIN_OPTION_DATA_DIR"
ENV_PRINCIPAL = "CLAUDE_PLUGIN_OPTION_PRINCIPAL"


def _blank(value) -> bool:
    return value is None or not str(value).strip()


def data_dir(given: Optional[str]) -> Optional[Path]:
    """The folder, or None when nothing names one. Never the working
    directory by accident."""
    if given is None:
        return None
    for value in (given, os.environ.get(ENV_DIR)):
        if not _blank(value):
            return Path(str(value).strip()).expanduser()
    return None


def looks_like_address(value: str) -> bool:
    value = (value or "").strip()
    if any(c in value for c in " ,;"):
        return False
    local, _, domain = value.rpartition("@")
    name, _, tld = domain.rpartition(".")
    return bool(local) and bool(name) and bool(tld)


def read_config(folder) -> dict:
    """{} when there is no file. A file that exists but cannot be parsed
    raises: silently treating it as empty is how a save would erase it."""
    path = Path(folder) / CONFIG
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def principal(given: Optional[str], folder) -> str:
    if not _blank(given):
        return str(given).strip()
    if folder is not None:
        try:
            saved = read_config(folder).get("principal")
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, str) and saved.strip():
            return saved.strip()
    env = os.environ.get(ENV_PRINCIPAL)
    return "" if _blank(env) else env.strip()


def save_principal(folder, address: str) -> None:
    """Atomic, and keeps whatever else the file holds."""
    if _blank(address):
        return
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    config = read_config(folder)
    config["principal"] = address.strip().lower()
    fd, tmp = tempfile.mkstemp(dir=str(folder), prefix="bob-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(config, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(folder / CONFIG))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
