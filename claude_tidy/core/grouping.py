from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

from claude_tidy.core.models import (
    CacheGroup,
    DeletePlan,
    DeleteTarget,
    IndexEntry,
    PlanMode,
    Project,
    SessionBundle,
    TargetKind,
)
from claude_tidy.core.usage import total_size

WORKTREE_CWD_RE = re.compile(r"^(?P<parent>.+?)[\\/]\.claude[\\/]worktrees[\\/](?P<name>[^\\/]+)")
WORKTREE_SLUG_SEP = "--claude-worktrees-"


def group_projects(projects: Iterable[Project]) -> list[Project]:
    """Nest worktree projects under their parent; return the top-level list.

    Parent is found via ``cwd`` (slugs are lossy — ``\\``, ``:``, ``.`` and ``-``
    all become ``-``), falling back to the slug pattern when no cwd is known.
    """
    projects = list(projects)
    by_cwd = {_norm(p.cwd): p for p in projects if p.cwd}
    by_slug = {p.slug: p for p in projects}
    top: list[Project] = []

    for project in projects:
        parent = None
        m = WORKTREE_CWD_RE.match(project.cwd or "")
        if m:
            project.worktree_name = m.group("name")
            parent = by_cwd.get(_norm(m.group("parent")))
        elif WORKTREE_SLUG_SEP in project.slug:
            parent_slug, _, name = project.slug.partition(WORKTREE_SLUG_SEP)
            project.worktree_name = name
            parent = by_slug.get(parent_slug)

        if project.worktree_name:
            project.worktree_exists = Path(project.cwd).is_dir() if project.cwd else False
        if parent is not None and parent is not project:
            project.parent_slug = parent.slug
            parent.worktrees.append(project)
        else:
            top.append(project)
    return top


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def build_session_plan(
    mode: PlanMode,
    project: Project,
    session_ids: Iterable[str] = (),
    include_worktrees: bool = False,
) -> DeletePlan:
    ids = list(session_ids)
    if mode is PlanMode.SINGLE and len(ids) != 1:
        raise ValueError("single mode needs exactly one session id")
    if mode is PlanMode.MULTI and not ids:
        raise ValueError("multi mode needs at least one session id")
    if mode not in (PlanMode.SINGLE, PlanMode.MULTI, PlanMode.ALL):
        raise ValueError(f"not a session plan mode: {mode}")

    if mode is PlanMode.ALL:
        sources = [project, *(project.worktrees if include_worktrees else [])]
        bundles = [s for p in sources for s in p.sessions]
    else:
        wanted = set(ids)
        available = {s.session_id: s for s in _all_sessions(project)}
        missing = wanted - available.keys()
        if missing:
            raise KeyError(f"sessions not in project {project.slug}: {sorted(missing)}")
        bundles = [available[i] for i in ids]

    return DeletePlan(mode=mode, label=project.display_name,
                      targets=[session_target(b) for b in bundles])


def _all_sessions(project: Project) -> list[SessionBundle]:
    return [*project.sessions, *(s for w in project.worktrees for s in w.sessions)]


def session_target(bundle: SessionBundle) -> DeleteTarget:
    return DeleteTarget(
        kind=TargetKind.SESSION,
        id=bundle.session_id,
        label=bundle.title or bundle.session_id,
        paths=list(bundle.paths),
        size_bytes=bundle.size_bytes,
        session=bundle,
    )


def build_index_plan(entry: IndexEntry) -> DeletePlan:
    # One entry per plan on purpose: orphan index files are confirmed one by one.
    files = [entry.path, *entry.key_files]
    return DeletePlan(
        mode=PlanMode.INDEX,
        label=entry.name or entry.cwd or entry.path.name,
        targets=[DeleteTarget(kind=TargetKind.INDEX, id=entry.path.name,
                              label=entry.name or entry.path.name, paths=files,
                              size_bytes=total_size(files), index_entry=entry)],
    )


def build_cache_plan(groups: Iterable[CacheGroup]) -> DeletePlan:
    return DeletePlan(
        mode=PlanMode.CACHE,
        label="cache",
        targets=[DeleteTarget(kind=TargetKind.CACHE, id=g.name, label=g.name,
                              paths=list(g.paths), size_bytes=g.size_bytes) for g in groups],
    )
