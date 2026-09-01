"""The Gmail token bootstrap. No network: the consent flow is stubbed.

What is worth testing here is not OAuth — it is the things that go wrong on a
real machine: a missing client secret, a token left world-readable, and a
command that silently overwrites a working credential.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import auth  # noqa: E402


class FakeCreds:
    def to_json(self): return '{"token": "not-a-real-token"}'


def test_a_missing_client_secret_explains_how_to_get_one(tmp_path):
    import pytest
    with pytest.raises(SystemExit) as e:
        auth.authorize(client_secret=tmp_path / "nope.json",
                       token=tmp_path / "t.json")
    msg = str(e.value)
    assert "console.cloud.google.com" in msg
    assert "Gmail API" in msg


def test_it_offers_the_no_credential_path_too(tmp_path):
    """A user who will not create a Cloud project is not stuck — Takeout plus
    `--mbox` is the same Bob."""
    import pytest
    with pytest.raises(SystemExit) as e:
        auth.authorize(client_secret=tmp_path / "nope.json",
                       token=tmp_path / "t.json")
    assert "--mbox" in str(e.value)
    assert "Takeout" in str(e.value)


def test_the_token_is_written_private(tmp_path, monkeypatch):
    secret = tmp_path / "cs.json"
    secret.write_text("{}", encoding="utf-8")
    token = tmp_path / "sub" / "token.json"

    class Flow:
        @staticmethod
        def from_client_secrets_file(path, scopes): return Flow()
        def run_local_server(self, **kw): return FakeCreds()

    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow",
                        type(sys)("m"))
    sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = Flow
    built = type(sys)("m")
    built.build = lambda *a, **k: _Svc()
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", built)

    who = auth.authorize(client_secret=secret, token=token)
    assert who == "someone@example.invalid"
    assert token.exists()
    assert stat.S_IMODE(os.stat(token).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(token.parent).st_mode) == 0o700


class _Svc:
    def users(self): return self
    def getProfile(self, userId): return self
    def execute(self): return {"emailAddress": "someone@example.invalid"}


def test_it_asks_only_for_read_only_mail():
    """Bob never sends from this credential — drafts go through the user's own
    connector (§4.8), so the token that reads six years of mail cannot write."""
    assert auth.SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert not any("compose" in s or "send" in s or "modify" in s
                   for s in auth.SCOPES)


def test_an_existing_token_is_not_silently_replaced(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(auth, "TOKEN", tmp_path / "t.json")
    auth.TOKEN.write_text("{}", encoding="utf-8")
    assert auth.main([]) == 0
    assert "already exists" in capsys.readouterr().out


def test_the_walkthrough_does_not_steer_people_into_testing_mode():
    """An app left in "Testing" expires its refresh token every 7 days, so the
    user re-authorizes weekly forever. An earlier version of these very
    instructions said to add yourself under "Test users" — which is that trap,
    written by the person who had already researched it."""
    w = auth.HOW_TO_GET_A_CLIENT_SECRET
    assert "In production" in w
    assert "7 days" in w
    assert "Test users" not in w
