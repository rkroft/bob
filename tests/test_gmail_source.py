"""GmailSource credential handling. No real credentials or contact data."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import gmail_source  # noqa: E402


def test_missing_credentials_error_names_the_env_vars_not_a_local_path(
    tmp_path, monkeypatch
):
    """The shipped `bob scan --gmail` command is a stranger's first run, not
    just the author's. The error a missing token raises must point at the
    supported override (BOB_GOOGLE_TOKEN) and the ~/.bob/ default without
    ever printing an absolute path off this machine — Mobile Documents /
    iCloud vault layout, or any /Users/<name> home directory."""
    missing = tmp_path / "does-not-exist" / "google_token.json"
    monkeypatch.setattr(gmail_source, "TOKEN", missing)

    with pytest.raises(SystemExit) as exc:
        gmail_source.GmailSource()

    message = str(exc.value)
    assert "BOB_GOOGLE_TOKEN" in message
    assert "Mobile Documents" not in message
    assert "/Users/" not in message


def test_default_token_path_lives_under_dot_bob():
    """Defaults must not point at any one person's iCloud vault — the CRM
    directory this module used to hardcode. ~/.bob/ is a plain, portable
    default any user has."""
    assert gmail_source.TOKEN == Path.home() / ".bob" / "google_token.json"
    assert (
        gmail_source.CLIENT_SECRET
        == Path.home() / ".bob" / "google_client_secret.json"
    )


def test_env_var_override_still_works(monkeypatch):
    """BOB_GOOGLE_TOKEN / BOB_GOOGLE_CLIENT_SECRET must keep working exactly
    as before — that's how the author keeps her own setup elsewhere on disk.
    TOKEN/CLIENT_SECRET are computed at import time, so the override is
    exercised by reloading the module with the env vars set first."""
    import importlib

    monkeypatch.setenv("BOB_GOOGLE_TOKEN", "/tmp/somewhere/token.json")
    monkeypatch.setenv("BOB_GOOGLE_CLIENT_SECRET", "/tmp/somewhere/secret.json")
    try:
        reloaded = importlib.reload(gmail_source)
        assert reloaded.TOKEN == Path("/tmp/somewhere/token.json")
        assert reloaded.CLIENT_SECRET == Path("/tmp/somewhere/secret.json")
    finally:
        monkeypatch.delenv("BOB_GOOGLE_TOKEN", raising=False)
        monkeypatch.delenv("BOB_GOOGLE_CLIENT_SECRET", raising=False)
        importlib.reload(gmail_source)
