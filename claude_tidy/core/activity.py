from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

import psutil

from claude_tidy.core.models import Activity, IndexEntry, SessionBundle
from claude_tidy.core.paths import ClaudePaths

log = logging.getLogger(__name__)

# procStart in sessions/<pid>.json is a Windows FILETIME: 100ns ticks since 1601-01-01.
FILETIME_TICKS_PER_SECOND = 10_000_000
FILETIME_UNIX_EPOCH_OFFSET = 11_644_473_600
# Observed drift between procStart and psutil's create_time() is 0; a reused PID
# belongs to a process started at a different moment, far outside this window.
PROC_START_TOLERANCE_SECONDS = 1.0

INDEX_JSON_RE = re.compile(r"^(\d+)\.json$")


class ProcessGone(Exception):
    pass


class ProcessAccessDenied(Exception):
    pass


class ProcessProbe(Protocol):
    def create_time(self, pid: int) -> float:
        """Epoch seconds; raises ProcessGone or ProcessAccessDenied."""
        ...


class PsutilProbe:
    def create_time(self, pid: int) -> float:
        try:
            return psutil.Process(pid).create_time()
        except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
            raise ProcessGone(pid) from exc
        except psutil.AccessDenied as exc:
            raise ProcessAccessDenied(pid) from exc


class ProcessState(StrEnum):
    MATCH = "match"
    GONE = "gone"
    REUSED = "reused"
    UNKNOWN = "unknown"


def filetime_to_epoch(value: object) -> float | None:
    try:
        ticks = int(str(value))
    except (TypeError, ValueError):
        return None
    if ticks <= FILETIME_UNIX_EPOCH_OFFSET * FILETIME_TICKS_PER_SECOND:
        return None  # not a FILETIME (or predates 1970) — refuse to guess the unit
    return ticks / FILETIME_TICKS_PER_SECOND - FILETIME_UNIX_EPOCH_OFFSET


def probe_process(pid: int, proc_start: float | None, probe: ProcessProbe) -> ProcessState:
    # pid_exists() alone is not enough: Windows recycles PIDs quickly, so a live
    # PID only proves *some* process has that number. Matching the recorded
    # start time proves it is the same Claude Code process.
    try:
        created = probe.create_time(pid)
    except ProcessGone:
        return ProcessState.GONE
    except ProcessAccessDenied:
        return ProcessState.UNKNOWN
    if proc_start is None:
        return ProcessState.UNKNOWN
    if abs(created - proc_start) <= PROC_START_TOLERANCE_SECONDS:
        return ProcessState.MATCH
    return ProcessState.REUSED


def read_index(paths: ClaudePaths) -> list[IndexEntry]:
    entries: list[IndexEntry] = []
    if not paths.sessions_dir.is_dir():
        return entries
    for f in sorted(paths.sessions_dir.iterdir()):
        m = INDEX_JSON_RE.match(f.name)
        if not m:
            continue
        pid = int(m.group(1))
        entry = IndexEntry(
            path=f, pid=pid, key_files=sorted(paths.sessions_dir.glob(f"{pid}.*.key"))
        )
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as exc:
            log.warning("Corrupt session index %s: %s", f, exc)
            entry.corrupt = True
            entries.append(entry)
            continue
        entry.session_id = data.get("sessionId") if isinstance(data.get("sessionId"), str) else None
        entry.cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else None
        entry.proc_start = filetime_to_epoch(data.get("procStart"))
        entry.status = data.get("status") if isinstance(data.get("status"), str) else None
        entry.name = data.get("name") if isinstance(data.get("name"), str) else None
        updated = data.get("updatedAt")
        entry.updated_at = updated / 1000 if isinstance(updated, (int, float)) else None
        entries.append(entry)
    return entries


class ActivityDetector:
    def __init__(
        self,
        paths: ClaudePaths,
        maybe_active_seconds: float = 300,
        probe: ProcessProbe | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.paths = paths
        self.maybe_active_seconds = maybe_active_seconds
        self.probe = probe or PsutilProbe()
        self.clock = clock
        self._entries: list[IndexEntry] = []
        self._states: dict[int, ProcessState] = {}
        self.refresh()

    def refresh(self) -> None:
        self._entries = read_index(self.paths)
        self._states = {
            e.pid: probe_process(e.pid, e.proc_start, self.probe)
            for e in self._entries
            if e.pid is not None
        }

    def status(self, bundle: SessionBundle) -> Activity:
        for entry in self._entries:
            if entry.session_id != bundle.session_id:
                continue
            state = self._states.get(entry.pid)
            if state is ProcessState.MATCH:
                return Activity.ACTIVE
            if state is ProcessState.UNKNOWN:
                return Activity.MAYBE_ACTIVE
        # Fallback: transcripts written moments ago may belong to a process whose
        # index entry we couldn't match (e.g. sessionId changed after /clear).
        if self.clock() - bundle.last_write < self.maybe_active_seconds:
            return Activity.MAYBE_ACTIVE
        return Activity.INACTIVE

    def index_entries(self) -> list[IndexEntry]:
        return list(self._entries)

    def orphan_state(self, entry: IndexEntry) -> ProcessState | None:
        """The specific reason `is_orphan()` said yes — GONE vs REUSED — for display."""
        if entry.pid is None:
            return None
        return self._states.get(entry.pid) or probe_process(entry.pid, entry.proc_start, self.probe)

    def is_orphan(self, entry: IndexEntry) -> bool:
        return self.orphan_state(entry) in (ProcessState.GONE, ProcessState.REUSED)

    def orphan_entries(self) -> list[IndexEntry]:
        return [e for e in self._entries if self.is_orphan(e)]


def claude_desktop_pid() -> int | None:
    # Claude Code's CLI is also named claude.exe, so match on install location:
    # MSIX (WindowsApps\Claude_*) or Squirrel (AnthropicClaude) — excluding the
    # claude-code binaries Desktop bundles.
    for proc in psutil.process_iter(["name", "exe", "pid"]):
        name = (proc.info.get("name") or "").lower()
        exe = (proc.info.get("exe") or "").lower()
        if name != "claude.exe" or "claude-code" in exe:
            continue
        if "\\windowsapps\\claude_" in exe or "\\anthropicclaude\\" in exe:
            return proc.info["pid"]
    return None


def is_claude_desktop_running() -> bool:
    return claude_desktop_pid() is not None
