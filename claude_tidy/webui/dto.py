"""Converts core dataclasses to JSON-safe dicts for the JS side.

Nothing here ever sends a filesystem path to JS beyond what's needed for
display — `js_api` calls back into Python with `project_id`/`session_id`,
never a path, and `api.py` re-resolves those ids against a fresh scan. See
claude_tidy/webui/CLAUDE.md "Trust boundary".
"""

from __future__ import annotations

from claude_tidy.core.models import (
    CacheGroup,
    DeletePlan,
    DeleteResult,
    DeleteTarget,
    IndexEntry,
    Preview,
    Progress,
    Project,
    SessionBundle,
)
from claude_tidy.core.usage import human_size


def project_to_dict(p: Project, size_bytes: int | None = None) -> dict:
    return {
        "id": p.slug,
        "display_name": p.display_name,
        "cwd": p.cwd,
        "session_count": len(p.sessions),
        "size_bytes": p.size_bytes if size_bytes is None else size_bytes,
        "size_human": human_size(p.size_bytes if size_bytes is None else size_bytes),
        "worktree_name": p.worktree_name,
        "worktree_exists": p.worktree_exists,
        "parent_id": p.parent_slug,
        "worktrees": [project_to_dict(w) for w in p.worktrees],
    }


def session_to_dict(s: SessionBundle, risk: str, activity: str,
                    active_pid: int | None = None) -> dict:
    return {
        "id": s.session_id,
        "title": s.title,
        "cwd": s.cwd,
        "last_write": s.last_write,
        "size_bytes": s.size_bytes,
        "size_human": human_size(s.size_bytes),
        "message_count": s.message_count,
        "risk": risk,
        "activity": activity,
        "active_pid": active_pid,
    }


def cache_group_to_dict(g: CacheGroup) -> dict:
    return {
        "id": g.name,
        "name": g.name,
        "root": str(g.root),
        "file_count": g.file_count,
        "size_bytes": g.size_bytes,
        "size_human": human_size(g.size_bytes),
    }


def index_entry_to_dict(e: IndexEntry, reason: str) -> dict:
    return {
        "id": e.path.name,
        "pid": e.pid,
        "cwd": e.cwd,
        "proc_start": e.proc_start,
        "updated_at": e.updated_at,
        "corrupt": e.corrupt,
        "name": e.name,
        "reason": reason,
    }


def target_to_dict(t: DeleteTarget) -> dict:
    return {"id": t.id, "kind": t.kind.value, "label": t.label, "size_bytes": t.size_bytes,
           "size_human": human_size(t.size_bytes)}


def preview_to_dict(pv: Preview, plan: DeletePlan) -> dict:
    return {
        "mode": plan.mode.value,
        "label": plan.label,
        "will_delete": [target_to_dict(t) for t in pv.will_delete],
        "needs_confirmation": [target_to_dict(t) for t in pv.needs_confirmation],
        "skipped": [{"target": target_to_dict(t), "reason": reason} for t, reason in pv.skipped],
        "size_bytes": pv.size_bytes,
        "size_human": human_size(pv.size_bytes),
    }


def progress_to_dict(job_id: str, p: Progress) -> dict:
    return {"job_id": job_id, "phase": p.phase, "done": p.done, "total": p.total,
           "current": p.current}


def result_to_dict(job_id: str, r: DeleteResult) -> dict:
    return {
        "job_id": job_id,
        "deleted": [target_to_dict(t) for t in r.deleted],
        "skipped": [{"target": target_to_dict(t), "reason": reason} for t, reason in r.skipped],
        "needs_confirmation": [target_to_dict(t) for t in r.needs_confirmation],
        "failed_files": [{"path": str(p), "error": e} for p, e in r.failed_files],
        "backup_path": str(r.backup_path) if r.backup_path else None,
        "cancelled": r.cancelled,
        "error": r.error,
        "freed_bytes": r.freed_bytes,
        "freed_human": human_size(r.freed_bytes),
    }
