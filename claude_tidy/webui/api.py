"""The `js_api` object exposed to the frontend — the one trust boundary
between untrusted JS and the filesystem. See claude_tidy/webui/CLAUDE.md.

Every method here returns a JSON-safe dict (via `dto.py`); nothing returns a
`Path`, a dataclass, or anything `json.dumps` can't handle directly, since
pywebview marshals return values to JS through its own JSON encoding.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path

from claude_tidy.core import restore as restore_mod
from claude_tidy.core.activity import claude_desktop_pid
from claude_tidy.core.deleter import execute, preview
from claude_tidy.core.grouping import (
    build_cache_plan,
    build_index_plan,
    build_session_plan,
    group_projects,
)
from claude_tidy.core.models import CacheGroup, DeletePlan, IndexEntry, PlanMode, Project
from claude_tidy.core.risk import classify
from claude_tidy.core.scanner import scan_cache, scan_project, scan_projects
from claude_tidy.core.settings import save_settings
from claude_tidy.webui import dto
from claude_tidy.webui.jobs import JobRunner


class InvalidRequest(Exception):
    """Raised for a malformed/unsafe request — reported as an error dict to
    JS, never lets a bad request quietly become a no-op delete of the wrong
    thing."""


class Api:
    def __init__(self, state, notify) -> None:
        self._state = state
        self._jobs = JobRunner(notify)
        self._delete_lock = threading.Lock()
        self._deleting = False
        self._restore_lock = threading.Lock()
        self._restoring = False

        # Populated by list_projects()/scan_cache()/list_orphan_index(); every
        # id the frontend ever sends is resolved against *this*, never a raw
        # path it supplies — see "Trust boundary" in webui/CLAUDE.md.
        self._projects: list[Project] = []
        self._cache_groups: list[CacheGroup] = []
        self._index_entries: dict[str, IndexEntry] = {}

        # token -> (DeletePlan, required_typed_name | None). One-time use:
        # popped in execute_delete, so a token can't be replayed.
        self._pending: dict[str, tuple[DeletePlan, str | None]] = {}

        # token -> resolved backup zip path. Same one-time-use shape as
        # `_pending`, popped in execute_restore.
        self._pending_restores: dict[str, Path] = {}

    # ------------------------------------------------------------- read side

    def list_projects(self) -> list[dict]:
        self._projects = group_projects(scan_projects(self._state.paths))
        return [dto.project_to_dict(p) for p in self._projects]

    def list_sessions(self, project_id: str) -> dict:
        try:
            project = self._find_project(project_id)
        except InvalidRequest as exc:
            # Real case, not just paranoia: rescanSessions() re-selects the
            # previously-open project on every refresh, and that project may
            # have been the one just deleted (e.g. "delete all").
            return {"error": str(exc)}
        detector = self._state.new_detector()
        now = time.time()
        sessions = []
        active_pid_by_session = {
            e.session_id: e.pid for e in detector.index_entries()
            if e.session_id and e.pid is not None
        }
        for s in project.sessions:
            status = detector.status(s)
            risk = classify(status, s.last_write, now, self._state.settings.recent_hours)
            sessions.append(dto.session_to_dict(
                s, risk.value, status.value, active_pid_by_session.get(s.session_id)))
        return {"project": dto.project_to_dict(project), "sessions": sessions}

    def rescan_project(self, project_id: str) -> dict:
        """Re-scan just this project's own directory (new/removed session
        files), without re-walking the whole ~/.claude/projects tree — a
        cheaper alternative to list_projects() for a right-click "refresh"."""
        try:
            project = self._find_project(project_id)
        except InvalidRequest as exc:
            return {"error": str(exc)}
        fresh = scan_project(project.dir, self._state.paths)
        project.sessions = fresh.sessions
        project.cwd = fresh.cwd
        return self.list_sessions(project_id)

    def open_project_folder(self, project_id: str) -> dict:
        try:
            project = self._find_project(project_id)
        except InvalidRequest as exc:
            return {"error": str(exc)}
        if not project.cwd or not Path(project.cwd).is_dir():
            return {"error": "Không tìm thấy thư mục project trên đĩa (worktree có thể đã mất)."}
        os.startfile(project.cwd)
        return {"ok": True}

    def scan_cache(self) -> dict:
        self._cache_groups = scan_cache(self._state.paths)
        pid = claude_desktop_pid()
        return {"groups": [dto.cache_group_to_dict(g) for g in self._cache_groups],
               "claude_desktop_pid": pid}

    def list_orphan_index(self) -> list[dict]:
        detector = self._state.new_detector()
        orphans = detector.orphan_entries()
        self._index_entries = {e.path.name: e for e in orphans}
        out = []
        for e in orphans:
            state = detector.orphan_state(e)
            if e.corrupt:
                reason = "File index hỏng · không đọc được JSON"
            elif state is not None and state.value == "reused":
                reason = "PID bị tái sử dụng · create_time hiện tại không khớp procStart"
            else:
                reason = "Process đã tắt · không còn process nào với PID này"
            out.append(dto.index_entry_to_dict(e, reason))
        return out

    def get_settings(self) -> dict:
        s = self._state.settings
        return {
            "backup_dir": str(s.backup_dir),
            "retention_days": s.retention_days,
            "auto_prune_backups": s.auto_prune_backups,
            "maybe_active_minutes": s.maybe_active_minutes,
            "recent_hours": s.recent_hours,
        }

    def save_settings(self, values: dict) -> dict:
        # Validated in Python, not trusted from JS — a negative/non-numeric
        # threshold from a tampered frontend must not reach core code.
        try:
            retention_days = int(values["retention_days"])
            maybe_active_minutes = int(values["maybe_active_minutes"])
            recent_hours = int(values["recent_hours"])
        except (KeyError, TypeError, ValueError):
            return {"error": "Các ngưỡng phải là số nguyên."}
        if min(retention_days, maybe_active_minutes, recent_hours) < 0:
            return {"error": "Giá trị không được âm."}
        backup_dir = str(values.get("backup_dir") or "").strip()
        if not backup_dir:
            return {"error": "Thư mục backup không được để trống."}
        s = self._state.settings
        s.backup_dir = Path(backup_dir)
        s.retention_days = retention_days
        s.auto_prune_backups = bool(values.get("auto_prune_backups"))
        s.maybe_active_minutes = maybe_active_minutes
        s.recent_hours = recent_hours
        save_settings(self._state.paths, s)
        return {"ok": True}

    def pick_folder(self, initial_dir: str | None = None) -> str | None:
        import webview

        window = webview.windows[0] if webview.windows else None
        if window is None:
            return None
        result = window.create_file_dialog(webview.FOLDER_DIALOG,
                                           directory=initial_dir or "")
        return result[0] if result else None

    # -------------------------------------------------------- delete flow

    def preview_delete(self, spec: dict) -> dict:
        try:
            plan, typed_name = self._build_plan(spec)
        except InvalidRequest as exc:
            return {"error": str(exc)}
        detector = self._state.new_detector()
        pv = preview(plan, self._state.paths, detector)
        token = secrets.token_urlsafe(16)
        self._pending[token] = (plan, typed_name)
        result = dto.preview_to_dict(pv, plan)
        result["token"] = token
        result["typed_name_required"] = typed_name
        return result

    def execute_delete(self, token: str, confirmed_ids: list[str],
                       typed_name: str | None = None) -> dict:
        # The lock only guards this quick check-and-commit; `_deleting` is
        # what actually stays true for the whole background job (reset in
        # `work()`'s `finally`, below) — the delete itself runs on a worker
        # thread, so releasing the lock when this method returns (almost
        # immediately, since starting a job is non-blocking) would NOT
        # actually block a second execute_delete() call arriving while the
        # first delete is still running.
        with self._delete_lock:
            if self._deleting:
                return {"error": "Đang có thao tác xoá khác chạy — thử lại sau."}
            entry = self._pending.get(token)
            if entry is None:
                return {"error": "Token không hợp lệ hoặc đã dùng."}
            plan, required_name = entry
            if required_name is not None and typed_name != required_name:
                return {"error": "Tên nhập vào không khớp tên project."}
            # Only consumed once validation passes — a wrong name shouldn't
            # permanently burn a one-time token the user might retry.
            del self._pending[token]
            self._deleting = True

        def work(on_progress, cancel):
            def bridge(p) -> None:
                on_progress({"phase": p.phase, "done": p.done, "total": p.total,
                            "current": p.current})

            try:
                result = execute(plan, paths=self._state.paths,
                                 detector=self._state.new_detector(),
                                 backup_dir=self._state.settings.backup_dir,
                                 confirmed=set(confirmed_ids), on_progress=bridge,
                                 cancel=cancel)
                if self._state.settings.auto_prune_backups:
                    from claude_tidy.core.backup import prune_backups
                    prune_backups(self._state.settings.backup_dir,
                                  self._state.settings.retention_days)
                return dto.result_to_dict("", result)
            finally:
                with self._delete_lock:
                    self._deleting = False

        job_id = self._jobs.start(work)
        return {"job_id": job_id}

    def cancel_job(self, job_id: str) -> bool:
        return self._jobs.cancel(job_id)

    # ------------------------------------------------------------- restore

    def list_backups(self) -> list[dict]:
        backups = restore_mod.list_backups(self._state.settings.backup_dir)
        return [dto.backup_file_to_dict(b) for b in backups]

    def preview_restore(self, backup_id: str) -> dict:
        zip_path = self._resolve_backup(backup_id)
        if zip_path is None:
            return {"error": "Không tìm thấy file backup."}
        try:
            pv = restore_mod.preview_restore(zip_path, self._state.paths)
        except restore_mod.RestoreError as exc:
            return {"error": str(exc)}
        token = secrets.token_urlsafe(16)
        self._pending_restores[token] = zip_path
        result = dto.restore_preview_to_dict(pv)
        result["token"] = token
        return result

    def execute_restore(self, token: str, confirmed_ids: list[str]) -> dict:
        # Same shape as execute_delete: the lock only guards this
        # check-and-commit step, `_restoring` covers the whole background job.
        with self._restore_lock:
            if self._restoring:
                return {"error": "Đang có thao tác khôi phục khác chạy — thử lại sau."}
            zip_path = self._pending_restores.get(token)
            if zip_path is None:
                return {"error": "Token không hợp lệ hoặc đã dùng."}
            del self._pending_restores[token]
            self._restoring = True

        def work(on_progress, cancel):
            def bridge(p) -> None:
                on_progress({"phase": p.phase, "done": p.done, "total": p.total,
                            "current": p.current})

            try:
                result = restore_mod.restore(zip_path, self._state.paths,
                                             confirmed=set(confirmed_ids), on_progress=bridge,
                                             cancel=cancel)
                return dto.restore_result_to_dict("", result)
            finally:
                with self._restore_lock:
                    self._restoring = False

        job_id = self._jobs.start(work)
        return {"job_id": job_id}

    def _resolve_backup(self, backup_id: str) -> Path | None:
        # backup_id is a bare filename from JS, never trusted as a path —
        # resolve it under the configured backup dir and reject anything
        # that escapes it (e.g. "..\\..\\windows\\x.zip").
        backup_dir = self._state.settings.backup_dir.resolve()
        candidate = (backup_dir / backup_id).resolve()
        try:
            candidate.relative_to(backup_dir)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    # ------------------------------------------------------------- internal

    def _find_project(self, project_id: str) -> Project:
        for p in self._projects:
            for proj in (p, *p.worktrees):
                if proj.slug == project_id:
                    return proj
        raise InvalidRequest(f"Không tìm thấy project: {project_id}")

    def _build_plan(self, spec: dict) -> tuple[DeletePlan, str | None]:
        mode = spec.get("mode")
        if mode in ("single", "multi", "all"):
            project = self._find_project(spec.get("project_id", ""))
            plan_mode = PlanMode(mode)
            if mode == "all":
                plan = build_session_plan(plan_mode, project,
                                          include_worktrees=bool(spec.get("include_worktrees")))
                typed_name = project.worktree_name or _short_name(project)
                return plan, typed_name
            ids = spec.get("session_ids") or []
            if not ids:
                raise InvalidRequest("Chưa chọn session nào.")
            plan = build_session_plan(plan_mode, project, ids)
            return plan, None
        if mode == "cache":
            group_ids = set(spec.get("group_ids") or [])
            groups = [g for g in self._cache_groups if g.name in group_ids]
            if not groups:
                raise InvalidRequest("Chưa chọn nhóm cache nào.")
            return build_cache_plan(groups), None
        if mode == "index":
            entry = self._index_entries.get(spec.get("entry_id", ""))
            if entry is None:
                raise InvalidRequest("Không tìm thấy file index.")
            return build_index_plan(entry), None
        raise InvalidRequest(f"Chế độ không hợp lệ: {mode!r}")


def _short_name(project: Project) -> str:
    raw = (project.cwd or project.slug).replace("\\", "/").rstrip("/")
    return raw.rsplit("/", 1)[-1]
