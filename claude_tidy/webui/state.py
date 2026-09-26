from __future__ import annotations

from dataclasses import dataclass

from claude_tidy.core.activity import ActivityDetector, ProcessProbe
from claude_tidy.core.paths import ClaudePaths
from claude_tidy.core.settings import Settings, load_settings


@dataclass
class AppState:
    paths: ClaudePaths
    settings: Settings
    # None in production (ActivityDetector defaults to the real PsutilProbe).
    # Injectable so tests can substitute a FakeProbe — see tests/test_webui_api.py:
    # a fixture's synthetic PIDs read against the *real* psutil never match
    # ACTIVE/REUSED, only ever GONE.
    probe: ProcessProbe | None = None

    @classmethod
    def load(cls) -> AppState:
        paths = ClaudePaths.from_env()
        return cls(paths=paths, settings=load_settings(paths))

    def new_detector(self) -> ActivityDetector:
        kwargs = {} if self.probe is None else {"probe": self.probe}
        return ActivityDetector(self.paths,
                                maybe_active_seconds=self.settings.maybe_active_minutes * 60,
                                **kwargs)
