from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
from pathlib import Path

from claude_tidy.core.models import CacheGroup, Project, SessionBundle
from claude_tidy.core.paths import ClaudePaths
from claude_tidy.core.usage import count_files, is_link, path_size

log = logging.getLogger(__name__)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
INDEX_FILE_RE = re.compile(r"^\d+(\.json|\.[0-9a-f]+\.key)$", re.I)

# Per-session artifacts that live outside projects/<slug>/, keyed by sessionId.
SESSION_SIDE_DIRS = ("file-history", "session-env", "tasks")

# Checked on every path component, so e.g. projects/<slug>/memory/ is refused
# even if some future bug puts it into a delete plan.
PROTECTED_PATTERNS = (
    "memory",
    "settings*.json",
    ".credentials.json",
    "CLAUDE.md",
    "commands",
    "skills",
    "agents",
    "plugins",
    "hooks",
    "rules",
)

# Only well-known, regenerable Chromium/Electron cache dirs. Everything else in
# the Desktop data dir (Local Storage, IndexedDB, config json) holds login
# state or user config.
DESKTOP_CACHE_DIRS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "Crashpad",
    "logs",
)

HEAD_BYTES = 256 * 1024
TAIL_BYTES = 64 * 1024


def check_deletable(path: Path, paths: ClaudePaths) -> str | None:
    """Return a refusal reason, or None if ``path`` may be deleted.

    Allowlist by location (only the exact shapes a session bundle, index file,
    or cache dir can take) plus a denylist on every component. Enforced here
    and again in the deleter, so no UI path can bypass it.
    """
    p = Path(os.path.abspath(path))

    for root, allowed in (
        (paths.claude_home, _allowed_in_claude_home),
        (paths.temp_dir, lambda rel: len(rel) == 1),
        *((d, _allowed_in_desktop) for d in paths.desktop_dirs),
    ):
        rel = _relative_parts(p, Path(os.path.abspath(root)))
        if rel is None:
            continue
        for part in rel:
            if any(fnmatch.fnmatch(part.lower(), pat.lower()) for pat in PROTECTED_PATTERNS):
                return f"protected path component '{part}'"
        if allowed(rel):
            return None
        return "not a session/index/cache location"
    return "outside managed directories"


def _relative_parts(p: Path, root: Path) -> tuple[str, ...] | None:
    p_norm, root_norm = os.path.normcase(str(p)), os.path.normcase(str(root))
    if p_norm != root_norm and not p_norm.startswith(root_norm.rstrip(os.sep) + os.sep):
        return None
    return p.parts[len(root.parts):]


def _allowed_in_claude_home(rel: tuple[str, ...]) -> bool:
    if len(rel) == 3 and rel[0] == "projects":
        return _session_id_of(rel[2]) is not None
    if len(rel) == 2 and rel[0] in SESSION_SIDE_DIRS:
        return bool(UUID_RE.match(rel[1]))
    if len(rel) == 2 and rel[0] == "sessions":
        return bool(INDEX_FILE_RE.match(rel[1]))
    return False


def _allowed_in_desktop(rel: tuple[str, ...]) -> bool:
    return len(rel) == 1 and rel[0] in DESKTOP_CACHE_DIRS


def _session_id_of(name: str) -> str | None:
    for suffix in (".jsonl.wakatime", ".jsonl", ""):
        if name.endswith(suffix):
            stem = name[: len(name) - len(suffix)] if suffix else name
            if UUID_RE.match(stem):
                return stem
    return None


def scan_projects(paths: ClaudePaths) -> list[Project]:
    projects: list[Project] = []
    if not paths.projects_dir.is_dir():
        return projects
    for entry in sorted(paths.projects_dir.iterdir()):
        if not entry.is_dir() or is_link(entry):
            continue
        try:
            projects.append(scan_project(entry, paths))
        except OSError as exc:
            log.warning("Skipping unreadable project dir %s: %s", entry, exc)
    return projects


def scan_project(project_dir: Path, paths: ClaudePaths) -> Project:
    by_id: dict[str, list[Path]] = {}
    for child in project_dir.iterdir():
        sid = _session_id_of(child.name)
        if sid is None or check_deletable(child, paths) is not None:
            continue
        by_id.setdefault(sid, []).append(child)

    sessions = []
    for sid, members in by_id.items():
        for side in SESSION_SIDE_DIRS:
            candidate = paths.claude_home / side / sid
            if candidate.exists() or is_link(candidate):
                members.append(candidate)
        sessions.append(_build_bundle(sid, project_dir.name, members))

    sessions.sort(key=lambda s: s.last_write, reverse=True)
    cwd = next((s.cwd for s in sessions if s.cwd), None)
    return Project(slug=project_dir.name, dir=project_dir, sessions=sessions, cwd=cwd)


def _build_bundle(session_id: str, slug: str, members: list[Path]) -> SessionBundle:
    jsonl = next((m for m in members if m.name == f"{session_id}.jsonl"), None)
    cwd = title = None
    message_count = 0
    if jsonl is not None:
        cwd, title = read_session_meta(jsonl)
        message_count = count_messages(jsonl)
    mtimes = [_mtime(m) for m in ([jsonl] if jsonl else members)]
    return SessionBundle(
        session_id=session_id,
        project_slug=slug,
        paths=sorted(members),
        jsonl=jsonl,
        cwd=cwd,
        title=title,
        message_count=message_count,
        last_write=max(mtimes, default=0.0),
        size_bytes=sum(path_size(m) for m in members),
    )


def count_messages(jsonl: Path) -> int:
    """Count records (one JSON object per line) via a raw byte scan.

    Unlike `read_session_meta`, an accurate count needs the whole file — but
    this only counts b"\\n" bytes in chunks, never parses JSON or loads the
    file into memory, so it stays cheap even for a multi-hundred-MB transcript.
    """
    try:
        count = 0
        with jsonl.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                count += chunk.count(b"\n")
        return count
    except OSError as exc:
        log.warning("Cannot count messages in %s: %s", jsonl, exc)
        return 0


def _mtime(path: Path) -> float:
    try:
        return os.lstat(path).st_mtime
    except OSError:
        return 0.0


def read_session_meta(jsonl: Path) -> tuple[str | None, str | None]:
    """Extract (cwd, title) reading only the head and tail of the file.

    Transcripts can be hundreds of MB; loading them whole to find two fields
    would make scanning a big project take minutes.
    """
    cwd = ai_title = custom_title = None
    try:
        with jsonl.open("rb") as f:
            head = f.read(HEAD_BYTES)
            f.seek(0, os.SEEK_END)
            size = f.tell()
            tail = b""
            if size > HEAD_BYTES:
                f.seek(max(HEAD_BYTES, size - TAIL_BYTES))
                tail = f.read()
    except OSError as exc:
        log.warning("Cannot read %s: %s", jsonl, exc)
        return None, None

    for chunk in (head, tail):
        for line in chunk.splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # partial line at a chunk boundary, or an unknown format
            if not isinstance(obj, dict):
                continue
            if cwd is None and isinstance(obj.get("cwd"), str):
                cwd = obj["cwd"]
            if isinstance(obj.get("customTitle"), str):
                custom_title = obj["customTitle"]
            if isinstance(obj.get("aiTitle"), str):
                ai_title = obj["aiTitle"]
    return cwd, custom_title or ai_title


def scan_cache(paths: ClaudePaths) -> list[CacheGroup]:
    groups: list[CacheGroup] = []
    for desktop in paths.desktop_dirs:
        for name in DESKTOP_CACHE_DIRS:
            d = desktop / name
            if d.is_dir() and not is_link(d):
                groups.append(CacheGroup(name=f"Desktop: {name}", root=desktop, paths=[d],
                                         size_bytes=path_size(d), file_count=count_files([d])))
    if paths.temp_dir.is_dir() and not is_link(paths.temp_dir):
        children = sorted(paths.temp_dir.iterdir())
        if children:
            groups.append(CacheGroup(name="Temp (%TEMP%\\claude)", root=paths.temp_dir,
                                     paths=children, size_bytes=sum(map(path_size, children)),
                                     file_count=count_files(children)))
    return groups
