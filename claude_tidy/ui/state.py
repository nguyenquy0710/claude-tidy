from __future__ import annotations

from dataclasses import dataclass

from claude_tidy.core.activity import ActivityDetector
from claude_tidy.core.paths import ClaudePaths
from claude_tidy.core.settings import Settings, load_settings


@dataclass
class AppState:
    paths: ClaudePaths
    settings: Settings

    @classmethod
    def load(cls) -> AppState:
        paths = ClaudePaths.from_env()
        return cls(paths=paths, settings=load_settings(paths))

    def new_detector(self) -> ActivityDetector:
        return ActivityDetector(self.paths,
                                maybe_active_seconds=self.settings.maybe_active_minutes * 60)
