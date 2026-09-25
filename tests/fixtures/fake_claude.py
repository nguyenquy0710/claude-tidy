"""Builds a fake ``~/.claude`` / Claude Desktop / %TEMP% tree under a tmp dir.

Generated per test rather than checked in as static files, because the
deletion tests destroy the tree they run against.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from claude_tidy.core.activity import (
    FILETIME_TICKS_PER_SECOND,
    FILETIME_UNIX_EPOCH_OFFSET,
    ProcessAccessDenied,
    ProcessGone,
)
from claude_tidy.core.paths import ClaudePaths

NOW = time.time()
HOUR = 3600
DAY = 86400

ALPHA_CWD = r"D:\work\alpha"
WORKTREE_CWD = r"D:\work\alpha\.claude\worktrees\feat-x"

S_OLD = "11111111-1111-1111-1111-111111111111"
S_RECENT = "22222222-2222-2222-2222-222222222222"
S_FRESH = "33333333-3333-3333-3333-333333333333"
S_LIVE = "44444444-4444-4444-4444-444444444444"
S_REUSED = "55555555-5555-5555-5555-555555555555"
S_DEAD = "66666666-6666-6666-6666-666666666666"
S_DENIED = "77777777-7777-7777-7777-777777777777"
S_WORKTREE = "88888888-8888-8888-8888-888888888888"
S_BETA = "99999999-9999-9999-9999-999999999999"

PID_LIVE = 4101
PID_REUSED = 4102
PID_DEAD = 4103
PID_DENIED = 4104
PID_CORRUPT = 4105
PROC_START_LIVE = NOW - 2 * HOUR


def to_filetime(epoch: float) -> str:
    return str(int((epoch + FILETIME_UNIX_EPOCH_OFFSET) * FILETIME_TICKS_PER_SECOND))


class FakeProbe:
    """Deterministic stand-in for psutil: pid -> create_time or exception."""

    def __init__(self, table: dict[int, float | Exception]) -> None:
        self.table = table

    def create_time(self, pid: int) -> float:
        value = self.table.get(pid, ProcessGone(pid))
        if isinstance(value, Exception):
            raise value
        return value


@dataclass
class FakeClaude:
    root: Path
    paths: ClaudePaths
    probe: FakeProbe
    outside_dir: Path
    protected: list[Path] = field(default_factory=list)

    def bundle_artifacts(self, session_id: str, slug: str) -> list[Path]:
        home = self.paths.claude_home
        return [
            home / "projects" / slug / f"{session_id}.jsonl",
            home / "projects" / slug / f"{session_id}.jsonl.wakatime",
            home / "projects" / slug / session_id,
            home / "file-history" / session_id,
            home / "session-env" / session_id,
            home / "tasks" / session_id,
        ]


def _write(path: Path, text: str = "x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _session(home: Path, slug: str, sid: str, cwd: str, title: str, age: float) -> None:
    mtime = NOW - age
    lines = [
        {"type": "ai-title", "aiTitle": title, "sessionId": sid},
        {"type": "user", "cwd": cwd, "sessionId": sid, "message": {"content": "hi"}},
    ]
    proj = home / "projects" / slug
    _write(proj / f"{sid}.jsonl", "\n".join(json.dumps(line) for line in lines) + "\n", mtime)
    _write(proj / f"{sid}.jsonl.wakatime", "123", mtime)
    _write(proj / sid / "subagents" / "agent-1.jsonl", "{}", mtime)
    _write(proj / sid / "tool-results" / "r1.txt", "result", mtime)
    _write(home / "file-history" / sid / "abc@v1", "old content", mtime)
    _write(home / "session-env" / sid / "env.sh", "export A=1", mtime)
    _write(home / "tasks" / sid / ".lock", "", mtime)
    _write(home / "tasks" / sid / ".highwatermark", "1", mtime)


def _index(home: Path, pid: int, sid: str | None, cwd: str, proc_start: float | None,
           raw: str | None = None) -> None:
    data = {"pid": pid, "sessionId": sid, "cwd": cwd, "status": "idle",
            "name": f"session {pid}", "updatedAt": int(NOW * 1000)}
    if proc_start is not None:
        data["procStart"] = to_filetime(proc_start)
    _write(home / "sessions" / f"{pid}.json", raw if raw is not None else json.dumps(data))
    _write(home / "sessions" / f"{pid}.deadbeef{pid}.key", "k")


def make_junction(link: Path, target: Path) -> bool:
    """Directory junction (no admin needed on Windows), else symlink. False if unsupported."""
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        return True
    except (ImportError, OSError):
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except OSError:
            return False


def build(tmp: Path) -> FakeClaude:
    home = tmp / "home" / ".claude"
    desktop = tmp / "appdata" / "Claude"
    temp = tmp / "temp" / "claude"
    paths = ClaudePaths(claude_home=home, desktop_dirs=(desktop,), temp_dir=temp,
                        app_dir=tmp / "localappdata" / "ClaudeTidy")

    alpha = "D--work-alpha"
    _session(home, alpha, S_OLD, ALPHA_CWD, "Old refactor", age=10 * DAY)
    _session(home, alpha, S_RECENT, ALPHA_CWD, "Yesterday's work", age=2 * HOUR)
    _session(home, alpha, S_FRESH, ALPHA_CWD, "Just written", age=60)
    _session(home, alpha, S_LIVE, ALPHA_CWD, "Running now", age=3 * DAY)
    _session(home, alpha, S_REUSED, ALPHA_CWD, "PID reused", age=3 * DAY)
    _session(home, alpha, S_DEAD, ALPHA_CWD, "PID dead", age=3 * DAY)
    _session(home, alpha, S_DENIED, ALPHA_CWD, "Access denied", age=3 * DAY)
    memory = _write(home / "projects" / alpha / "memory" / "MEMORY.md", "- remember this")

    worktree = "D--work-alpha--claude-worktrees-feat-x"
    _session(home, worktree, S_WORKTREE, WORKTREE_CWD, "Worktree task", age=5 * DAY)
    _session(home, "E--other-beta", S_BETA, r"E:\other\beta", "Beta", age=20 * DAY)

    _index(home, PID_LIVE, S_LIVE, ALPHA_CWD, PROC_START_LIVE)
    _index(home, PID_REUSED, S_REUSED, ALPHA_CWD, NOW - 5 * DAY)
    _index(home, PID_DEAD, S_DEAD, ALPHA_CWD, NOW - 3 * DAY)
    _index(home, PID_DENIED, S_DENIED, ALPHA_CWD, NOW - 3 * DAY)
    _index(home, PID_CORRUPT, None, ALPHA_CWD, None, raw="{not json")

    probe = FakeProbe({
        PID_LIVE: PROC_START_LIVE,
        PID_REUSED: NOW - 60,  # same PID, different (newer) process
        PID_DENIED: ProcessAccessDenied(PID_DENIED),
    })

    protected = [
        memory,
        _write(home / "settings.json", "{}"),
        _write(home / "settings.local.json", "{}"),
        _write(home / ".credentials.json", "{\"token\": \"secret\"}"),
        _write(home / "CLAUDE.md", "# rules"),
        _write(home / "commands" / "go.md", "cmd"),
        _write(home / "skills" / "s" / "SKILL.md", "skill"),
        _write(home / "agents" / "a.md", "agent"),
        _write(home / "history.jsonl", "{}"),
    ]

    for name in ("Cache", "GPUCache", "logs"):
        _write(desktop / name / "data_0", "c" * 100)
    protected += [
        _write(desktop / "Local Storage" / "leveldb" / "000.log", "login"),
        _write(desktop / "IndexedDB" / "db", "db"),
        _write(desktop / "claude_desktop_config.json", "{}"),
    ]
    outside = tmp / "outside"
    protected.append(_write(outside / "precious.bin", "do not delete"))
    make_junction(desktop / "vm_bundles", outside)

    _write(temp / "D--work-alpha" / "tmp1.txt", "t" * 50)
    _write(temp / "E--other-beta" / "tmp2.txt", "t" * 50)

    return FakeClaude(root=tmp, paths=paths, probe=probe, outside_dir=outside,
                      protected=protected)
