from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from claude_tidy.core.paths import ClaudePaths

log = logging.getLogger(__name__)


@dataclass
class Settings:
    backup_dir: Path
    retention_days: int = 14
    auto_prune_backups: bool = True
    maybe_active_minutes: int = 5
    recent_hours: int = 24

    @classmethod
    def defaults(cls, paths: ClaudePaths) -> Settings:
        return cls(backup_dir=paths.default_backup_dir)


def load_settings(paths: ClaudePaths) -> Settings:
    settings = Settings.defaults(paths)
    try:
        raw = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return settings
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable settings file %s: %s", paths.settings_file, exc)
        return settings

    known = {f.name for f in fields(Settings)}
    for key, value in raw.items():
        if key not in known:
            continue
        default = getattr(settings, key)
        try:
            coerce = Path if isinstance(default, Path) else type(default)
            setattr(settings, key, coerce(value))
        except (TypeError, ValueError):
            log.warning("Ignoring invalid setting %s=%r", key, value)
    return settings


def save_settings(paths: ClaudePaths, settings: Settings) -> None:
    data = {k: str(v) if isinstance(v, Path) else v for k, v in asdict(settings).items()}
    paths.app_dir.mkdir(parents=True, exist_ok=True)
    paths.settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
