"""Suite-wide isolation.

A Claude Code session with Bob enabled exports the user's real folder and
address as $CLAUDE_PLUGIN_OPTION_*. Left in place, any test that omits a flag
would read -- or stamp -- the user's actual Bob folder.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_plugin_settings(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_DATA_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_PRINCIPAL", raising=False)
