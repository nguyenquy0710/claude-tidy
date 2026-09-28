from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_CLAUDE_HOME = "CLAUDE_TIDY_CLAUDE_HOME"
ENV_DESKTOP_DIRS = "CLAUDE_TIDY_DESKTOP_DIRS"
ENV_TEMP_DIR = "CLAUDE_TIDY_TEMP_DIR"
ENV_APP_DIR = "CLAUDE_TIDY_APP_DIR"
ENV_OPENCODE_DATA_DIR = "CLAUDE_TIDY_OPENCODE_DATA_DIR"


@dataclass(frozen=True)
class ClaudePaths:
    claude_home: Path
    desktop_dirs: tuple[Path, ...]
    temp_dir: Path
    app_dir: Path
    # OpenCode CLI (opencode.ai) data dir — a *separate* tool from Claude Code.
    # Only its known regenerable cache-like subdirs are ever offered for
    # deletion (see scanner.OPENCODE_CACHE_DIRS); opencode.db (the app's own
    # session/message database) and its credential files are never touched —
    # see claude_tidy/CLAUDE.md's OpenCode section for the full rationale.
    opencode_data_dir: Path

    @property
    def projects_dir(self) -> Path:
        return self.claude_home / "projects"

    @property
    def sessions_dir(self) -> Path:
        return self.claude_home / "sessions"

    @property
    def settings_file(self) -> Path:
        return self.app_dir / "settings.json"

    @property
    def oplog_file(self) -> Path:
        return self.app_dir / "operations.jsonl"

    @property
    def default_backup_dir(self) -> Path:
        return self.app_dir / "backups"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ClaudePaths:
        env = os.environ if env is None else env
        home = Path(env.get("USERPROFILE") or Path.home())
        appdata = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
        local_appdata = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
        temp = Path(env.get("TEMP") or env.get("TMP") or local_appdata / "Temp")

        claude_home = Path(
            env.get(ENV_CLAUDE_HOME) or env.get("CLAUDE_CONFIG_DIR") or home / ".claude"
        )
        if env.get(ENV_DESKTOP_DIRS):
            desktop_dirs = tuple(Path(p) for p in env[ENV_DESKTOP_DIRS].split(os.pathsep) if p)
        else:
            desktop_dirs = _desktop_candidates(appdata, local_appdata)

        return cls(
            claude_home=claude_home,
            desktop_dirs=desktop_dirs,
            temp_dir=Path(env.get(ENV_TEMP_DIR) or temp / "claude"),
            app_dir=Path(env.get(ENV_APP_DIR) or local_appdata / "ClaudeTidy"),
            opencode_data_dir=Path(
                env.get(ENV_OPENCODE_DATA_DIR) or home / ".local" / "share" / "opencode"
            ),
        )


def _desktop_candidates(appdata: Path, local_appdata: Path) -> tuple[Path, ...]:
    # The MSIX (Microsoft Store) build of Claude Desktop virtualizes %APPDATA%,
    # so its real data lives under Packages\Claude_<publisher>\LocalCache.
    candidates = [appdata / "Claude"]
    packages = local_appdata / "Packages"
    if packages.is_dir():
        candidates += sorted(
            p / "LocalCache" / "Roaming" / "Claude" for p in packages.glob("Claude_*")
        )
    return tuple(candidates)
