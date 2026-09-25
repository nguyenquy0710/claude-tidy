from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class Activity(StrEnum):
    ACTIVE = "active"
    MAYBE_ACTIVE = "maybe_active"
    INACTIVE = "inactive"


class RiskLevel(StrEnum):
    SAFE = "safe"
    WARNING = "warning"
    DANGER = "danger"


class TargetKind(StrEnum):
    SESSION = "session"
    INDEX = "index"
    CACHE = "cache"


class PlanMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"
    ALL = "all"
    INDEX = "index"
    CACHE = "cache"


@dataclass
class SessionBundle:
    session_id: str
    project_slug: str
    paths: list[Path]
    jsonl: Path | None = None
    cwd: str | None = None
    title: str | None = None
    last_write: float = 0.0
    size_bytes: int = 0


@dataclass
class Project:
    slug: str
    dir: Path
    sessions: list[SessionBundle] = field(default_factory=list)
    cwd: str | None = None
    worktrees: list[Project] = field(default_factory=list)
    parent_slug: str | None = None
    worktree_name: str | None = None
    worktree_exists: bool | None = None

    @property
    def display_name(self) -> str:
        if self.worktree_name:
            return self.worktree_name
        return self.cwd or self.slug

    @property
    def size_bytes(self) -> int:
        return sum(s.size_bytes for s in self.sessions)


@dataclass
class IndexEntry:
    """One ``sessions/<pid>.json`` file plus its ``<pid>.<hash>.key`` companions."""

    path: Path
    pid: int | None
    key_files: list[Path] = field(default_factory=list)
    session_id: str | None = None
    cwd: str | None = None
    proc_start: float | None = None
    status: str | None = None
    name: str | None = None
    updated_at: float | None = None
    corrupt: bool = False


@dataclass
class CacheGroup:
    name: str
    root: Path
    paths: list[Path]
    size_bytes: int = 0


@dataclass
class DeleteTarget:
    kind: TargetKind
    id: str
    label: str
    paths: list[Path]
    size_bytes: int = 0
    session: SessionBundle | None = None
    index_entry: IndexEntry | None = None


@dataclass
class DeletePlan:
    mode: PlanMode
    label: str
    targets: list[DeleteTarget]

    @property
    def size_bytes(self) -> int:
        return sum(t.size_bytes for t in self.targets)


@dataclass
class Preview:
    will_delete: list[DeleteTarget] = field(default_factory=list)
    skipped: list[tuple[DeleteTarget, str]] = field(default_factory=list)
    needs_confirmation: list[DeleteTarget] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return sum(t.size_bytes for t in self.will_delete)


@dataclass
class Progress:
    phase: str
    done: int
    total: int
    current: str = ""


@dataclass
class DeleteResult:
    deleted: list[DeleteTarget] = field(default_factory=list)
    skipped: list[tuple[DeleteTarget, str]] = field(default_factory=list)
    needs_confirmation: list[DeleteTarget] = field(default_factory=list)
    failed_files: list[tuple[Path, str]] = field(default_factory=list)
    backup_path: Path | None = None
    cancelled: bool = False
    error: str | None = None

    @property
    def freed_bytes(self) -> int:
        return sum(t.size_bytes for t in self.deleted)
