"""Bob without plugin settings.

Cowork never passes a plugin's userConfig to the session: `${user_config.*}`
and `$CLAUDE_PLUGIN_OPTION_*` both arrive empty (anthropics/claude-code#39125,
closed not planned). So the folder is the anchor, and the address is saved in
it once, by `bob setup`, and read back by every later command.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import bob  # noqa: E402
import bob_config  # noqa: E402
from intro_store import IntroRow, write_intros  # noqa: E402

DANA = "dana.okafor@example.com"


def test_setup_creates_the_folder_and_saves_the_address(tmp_path, capsys):
    folder = tmp_path / "bob-network"
    assert bob.main(["setup", "--data-dir", str(folder),
                     "--principal", DANA]) == 0
    assert json.loads((folder / "bob.json").read_text())["principal"] == DANA
    out = capsys.readouterr().out
    assert str(folder) in out and DANA in out


def test_setup_without_an_address_asks_for_one(tmp_path, capsys):
    rc = bob.main(["setup", "--data-dir", str(tmp_path)])
    assert rc == 2
    assert "address" in capsys.readouterr().out.lower()
    assert not (tmp_path / "bob.json").exists()


def test_setup_again_keeps_the_saved_address(tmp_path):
    bob.main(["setup", "--data-dir", str(tmp_path), "--principal", DANA])
    assert bob.main(["setup", "--data-dir", str(tmp_path)]) == 0
    assert bob_config.principal(None, tmp_path) == DANA


def test_blank_address_is_not_saved(tmp_path):
    # A substitution that failed arrives as "" -- never write that over a
    # real address.
    bob.main(["setup", "--data-dir", str(tmp_path), "--principal", DANA])
    bob.main(["setup", "--data-dir", str(tmp_path), "--principal", ""])
    assert bob_config.principal(None, tmp_path) == DANA


def test_blank_folder_is_refused_not_read_as_the_working_directory(capsys):
    # `Path("")` is `.` -- an empty setting used to become "wherever Bob
    # happens to be running", silently.
    with pytest.raises(SystemExit) as exc:
        bob.main(["setup", "--data-dir", "", "--principal", DANA])
    assert "folder" in str(exc.value).lower()


def test_blank_folder_falls_back_to_the_plugin_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DATA_DIR", str(tmp_path))
    assert bob_config.data_dir("") == tmp_path


def test_given_address_beats_saved_beats_env(tmp_path, monkeypatch):
    # Saved outranks the plugin setting: `bob setup` is how a user corrects
    # the address, and Claude Code always exports the setting.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_PRINCIPAL", "env@example.com")
    assert bob_config.principal("", tmp_path) == "env@example.com"
    bob_config.save_principal(tmp_path, "saved@example.com")
    assert bob_config.principal("", tmp_path) == "saved@example.com"
    assert bob_config.principal(DANA, tmp_path) == DANA


def test_omitted_folder_never_adopts_the_plugin_setting(tmp_path, monkeypatch):
    # Only an explicitly blank --data-dir (a failed substitution) falls back.
    # Otherwise a hand-run scan would quietly write into the user's folder.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DATA_DIR", str(tmp_path))
    assert bob_config.data_dir(None) is None


def test_setup_refuses_something_that_is_not_an_address(tmp_path):
    assert bob.main(["setup", "--data-dir", str(tmp_path),
                     "--principal", "Dana Okafor"]) == 1
    assert not (tmp_path / "bob.json").exists()


def test_corrupt_config_is_not_overwritten(tmp_path):
    (tmp_path / "bob.json").write_text("{not json")
    with pytest.raises(ValueError):
        bob_config.save_principal(tmp_path, DANA)
    assert (tmp_path / "bob.json").read_text() == "{not json"


def test_blank_plugin_root_is_not_the_working_directory(tmp_path, capsys):
    rc = bob.main(["preflight", "--data-dir", str(tmp_path),
                   "--plugin-root", ""])
    assert "plugin.json" not in capsys.readouterr().out
    assert rc in (0, 2)


def test_saving_keeps_other_keys(tmp_path):
    (tmp_path / "bob.json").write_text(json.dumps({"other": 1}))
    bob_config.save_principal(tmp_path, DANA)
    saved = json.loads((tmp_path / "bob.json").read_text())
    assert saved == {"other": 1, "principal": DANA}


def test_graph_needs_only_the_folder(tmp_path):
    bob.main(["setup", "--data-dir", str(tmp_path), "--principal", DANA])
    write_intros([IntroRow(
        thread_id="t1", date="2026-03-03", direction="inbound",
        introducer="ben.mercer@otherco.io",
        introduced=("alice.tran@examplecorp.com",),
        subject="Intro: Dana <> Alice", thread_link="", confidence=0.9,
    )], tmp_path / "intros.csv")
    assert bob.main(["graph", "--data-dir", str(tmp_path)]) == 0
    assert (tmp_path / "network.html").exists()


def test_graph_with_no_address_anywhere_says_so(tmp_path):
    with pytest.raises(SystemExit) as exc:
        bob.main(["graph", "--data-dir", str(tmp_path)])
    assert "address" in str(exc.value).lower()


def test_scan_writes_into_the_folder_by_default(tmp_path):
    import mailbox
    from email.message import EmailMessage

    m = EmailMessage()
    m["From"] = "ben.mercer@otherco.io"
    m["To"] = f"{DANA}, alice.tran@examplecorp.com"
    m["Subject"] = "Intro: Dana <> Alice"
    m["Date"] = "Tue, 03 Mar 2026 09:00:00 -0800"
    m["X-GM-THRID"] = "1"
    m.set_content("I'd like to introduce you two. Moving myself to bcc.")
    box = mailbox.mbox(str(tmp_path / "mail.mbox"), create=True)
    box.add(m)
    box.flush()
    box.close()

    folder = tmp_path / "bob-network"
    bob.main(["setup", "--data-dir", str(folder), "--principal", DANA])
    bob.main(["confirm-folder", "--data-dir", str(folder)])
    rc = bob.main(["scan", "--mbox", str(tmp_path / "mail.mbox"),
                   "--data-dir", str(folder)])
    assert rc == 0
    assert (folder / "intros.csv").exists()
    assert (folder / "people.csv").exists()


def test_scan_records_the_address_it_actually_read(tmp_path, capsys):
    # The token decides whose mailbox a Gmail scan reads. If that differs from
    # the saved address, the graph would draw a different "you".
    import mailbox
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = "ben.mercer@otherco.io"
    m["To"] = f"{DANA}, alice.tran@examplecorp.com"
    m["Subject"] = "Intro: Dana <> Alice"
    m["Date"] = "Tue, 03 Mar 2026 09:00:00 -0800"
    m["X-GM-THRID"] = "1"
    m.set_content("I'd like to introduce you two. Moving myself to bcc.")
    box = mailbox.mbox(str(tmp_path / "mail.mbox"), create=True)
    box.add(m)
    box.flush()
    box.close()
    folder = tmp_path / "net"
    bob.main(["setup", "--data-dir", str(folder),
              "--principal", "someone.else@example.com"])
    bob.main(["confirm-folder", "--data-dir", str(folder)])
    assert bob.main(["scan", "--mbox", str(tmp_path / "mail.mbox"),
                     "--data-dir", str(folder), "--principal", DANA]) == 0
    assert bob_config.principal(None, folder) == DANA
    assert "saved" in capsys.readouterr().out.lower()


def test_setup_with_a_token_takes_the_address_from_it(tmp_path, monkeypatch):
    import types
    fake = types.ModuleType("gmail_source")

    class GmailSource:
        def principal(self):
            return DANA
    fake.GmailSource = GmailSource
    monkeypatch.setitem(sys.modules, "gmail_source", fake)
    assert bob.main(["setup", "--data-dir", str(tmp_path), "--gmail",
                     "--principal", "guess@example.com"]) == 0
    assert bob_config.principal(None, tmp_path) == DANA


def test_address_check_rejects_lists_and_half_domains():
    assert bob_config.looks_like_address(DANA)
    for bad in (f"{DANA},ben@otherco.io", "dana@example.", "dana@.com", "Dana Okafor", "@example.com"):
        assert not bob_config.looks_like_address(bad), bad


def test_saved_address_is_lowercased_and_case_is_not_a_mismatch(tmp_path, capsys):
    bob_config.save_principal(tmp_path, "Dana.Okafor@Example.com")
    assert bob_config.principal(None, tmp_path) == DANA
    args = type("A", (), {"data_dir": tmp_path})()
    bob._remember_principal(args, DANA)
    assert "note" not in capsys.readouterr().out


def test_scan_does_not_freeze_an_address_nobody_saved(tmp_path):
    args = type("A", (), {"data_dir": tmp_path})()
    bob._remember_principal(args, DANA)
    assert not (tmp_path / "bob.json").exists()
