from __future__ import annotations

import pytest

from claude_tidy.core.activity import ActivityDetector
from claude_tidy.core.paths import (
    ENV_APP_DIR,
    ENV_CLAUDE_HOME,
    ENV_DESKTOP_DIRS,
    ENV_TEMP_DIR,
    ClaudePaths,
)
from tests.fixtures import fake_claude


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path_factory, monkeypatch):
    # Any code that falls back to ClaudePaths.from_env() must land in a tmp dir,
    # never the developer's real ~/.claude — this suite exercises deletion.
    sandbox = tmp_path_factory.mktemp("env-sandbox")
    for var in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        monkeypatch.setenv(var, str(sandbox / var.lower()))
    monkeypatch.setenv(ENV_CLAUDE_HOME, str(sandbox / ".claude"))
    monkeypatch.setenv(ENV_DESKTOP_DIRS, str(sandbox / "desktop"))
    monkeypatch.setenv(ENV_TEMP_DIR, str(sandbox / "temp-claude"))
    monkeypatch.setenv(ENV_APP_DIR, str(sandbox / "app"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    paths = ClaudePaths.from_env()
    assert str(paths.claude_home).startswith(str(sandbox))


@pytest.fixture
def fake(tmp_path) -> fake_claude.FakeClaude:
    return fake_claude.build(tmp_path)


@pytest.fixture
def detector(fake) -> ActivityDetector:
    return ActivityDetector(fake.paths, maybe_active_seconds=300, probe=fake.probe,
                            clock=lambda: fake_claude.NOW)
