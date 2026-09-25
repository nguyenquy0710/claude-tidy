from __future__ import annotations

import time
from datetime import datetime

import flet as ft

from claude_tidy.core.grouping import build_session_plan, group_projects
from claude_tidy.core.models import PlanMode, Project, RiskLevel, SessionBundle
from claude_tidy.core.risk import classify
from claude_tidy.core.scanner import scan_projects
from claude_tidy.core.usage import human_size
from claude_tidy.ui.delete_flow import run_delete_flow
from claude_tidy.ui.state import AppState

BADGE = {
    RiskLevel.SAFE: ("an toàn", ft.Colors.GREEN_600),
    RiskLevel.WARNING: ("cảnh báo", ft.Colors.AMBER_700),
    RiskLevel.DANGER: ("đang chạy", ft.Colors.RED_600),
}


class ExplorerView(ft.Row):
    def __init__(self, page: ft.Page, state: AppState) -> None:
        super().__init__(expand=True, spacing=0)
        self._page = page
        self.state = state
        self.projects: list[Project] = []
        self.risk: dict[str, RiskLevel] = {}
        self.selected: Project | None = None
        self.checked: set[str] = set()

        self.project_list = ft.ListView(expand=True, spacing=2)
        self.session_list = ft.ListView(expand=True, spacing=2)
        self.header = ft.Text("Chọn một project", size=18, weight=ft.FontWeight.BOLD)
        self.subheader = ft.Text("", size=12)
        self.busy = ft.ProgressRing(width=18, height=18, visible=False)
        self.delete_checked_btn = ft.FilledButton(content="Xoá đã chọn", disabled=True,
                                                  on_click=self._delete_checked)
        self.delete_all_btn = ft.OutlinedButton(content="Xoá tất cả session", disabled=True,
                                                on_click=self._delete_all)

        left = ft.Container(
            ft.Column([
                ft.Row([ft.Text("Projects", weight=ft.FontWeight.BOLD), self.busy,
                        ft.IconButton(ft.Icons.REFRESH, tooltip="Quét lại",
                                      on_click=lambda _e: self.rescan())],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.project_list,
            ], expand=True),
            width=340, padding=10,
        )
        right = ft.Container(
            ft.Column([
                self.header, self.subheader,
                ft.Row([self.delete_checked_btn, self.delete_all_btn]),
                ft.Divider(),
                self.session_list,
            ], expand=True),
            expand=True, padding=10,
        )
        self.controls = [left, ft.VerticalDivider(width=1), right]

    def rescan(self) -> None:
        self.busy.visible = True
        self._page.update()
        self._page.run_thread(self._scan_worker)

    def _scan_worker(self) -> None:
        # Scanning a large ~/.claude takes seconds; keep it off the UI thread.
        detector = self.state.new_detector()
        now = time.time()
        projects = group_projects(scan_projects(self.state.paths))
        risk = {}
        for p in projects:
            for proj in (p, *p.worktrees):
                for s in proj.sessions:
                    risk[s.session_id] = classify(detector.status(s), s.last_write, now,
                                                  self.state.settings.recent_hours)
        self.projects, self.risk = projects, risk
        if self.selected is not None:
            self.selected = self._find(self.selected.slug)
        self.checked.clear()
        self.busy.visible = False
        self._render_projects()
        self._render_sessions()

    def _find(self, slug: str) -> Project | None:
        for p in self.projects:
            for proj in (p, *p.worktrees):
                if proj.slug == slug:
                    return proj
        return None

    def _render_projects(self) -> None:
        rows: list[ft.Control] = []
        for p in sorted(self.projects, key=lambda p: p.display_name.lower()):
            rows.append(self._project_tile(p, indent=0))
            rows += [self._project_tile(w, indent=20) for w in p.worktrees]
        self.project_list.controls = rows
        self._page.update()

    def _project_tile(self, p: Project, indent: int) -> ft.Control:
        name = f"↳ {p.display_name}" if indent else p.display_name
        sub = f"{len(p.sessions)} session · {human_size(p.size_bytes)}"
        if p.worktree_name and not p.worktree_exists:
            sub += " · worktree không còn tồn tại"
        selected = self.selected is not None and self.selected.slug == p.slug
        return ft.Container(
            ft.Column([ft.Text(name, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                               tooltip=p.cwd or p.slug),
                       ft.Text(sub, size=11, color=ft.Colors.GREY_700)], spacing=0),
            padding=ft.Padding.only(left=8 + indent, top=6, right=8, bottom=6),
            border_radius=6,
            bgcolor=ft.Colors.BLUE_50 if selected else None,
            on_click=lambda _e, p=p: self._select(p),
        )

    def _select(self, p: Project) -> None:
        self.selected = p
        self.checked.clear()
        self._render_projects()
        self._render_sessions()

    def _render_sessions(self) -> None:
        p = self.selected
        if p is None:
            self.session_list.controls = []
            self._page.update()
            return
        self.header.value = p.display_name
        self.subheader.value = (f"{p.cwd or p.slug} · {len(p.sessions)} session · "
                                f"{human_size(p.size_bytes)}")
        self.session_list.controls = [self._session_row(s) for s in p.sessions]
        self._update_buttons()

    def _session_row(self, s: SessionBundle) -> ft.Control:
        label, color = BADGE[self.risk.get(s.session_id, RiskLevel.WARNING)]
        when = (datetime.fromtimestamp(s.last_write).strftime("%Y-%m-%d %H:%M")
                if s.last_write else "?")
        return ft.Row([
            ft.Checkbox(value=s.session_id in self.checked,
                        on_change=lambda e, sid=s.session_id: self._toggle(sid, e.control.value)),
            ft.Container(ft.Text(label, size=11, color=ft.Colors.WHITE), bgcolor=color,
                         padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                         border_radius=10, width=78),
            ft.Column([
                ft.Text(s.title or "(không có tiêu đề)", size=13, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{s.session_id[:8]} · {when} · {human_size(s.size_bytes)}", size=11,
                        color=ft.Colors.GREY_700),
            ], spacing=0, expand=True),
            ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Xoá session này",
                          on_click=lambda _e, sid=s.session_id: self._delete_single(sid)),
        ])

    def _toggle(self, sid: str, value: bool) -> None:
        (self.checked.add if value else self.checked.discard)(sid)
        self._update_buttons()

    def _update_buttons(self) -> None:
        p = self.selected
        self.delete_checked_btn.content = f"Xoá đã chọn ({len(self.checked)})"
        self.delete_checked_btn.disabled = not self.checked
        self.delete_all_btn.disabled = p is None or not (p.sessions or p.worktrees)
        self._page.update()

    def _delete_single(self, sid: str) -> None:
        plan = build_session_plan(PlanMode.SINGLE, self.selected, [sid])
        run_delete_flow(self._page, self.state, plan, self.rescan)

    def _delete_checked(self, _e) -> None:
        ids = [s.session_id for s in self.selected.sessions if s.session_id in self.checked]
        plan = build_session_plan(PlanMode.MULTI, self.selected, ids)
        run_delete_flow(self._page, self.state, plan, self.rescan)

    def _delete_all(self, _e) -> None:
        project = self.selected
        if not project.worktrees:
            self._confirm_all(project, include_worktrees=False)
            return
        include = ft.Checkbox(label=f"Áp dụng cho cả {len(project.worktrees)} worktree con",
                              value=False)

        def go(_e) -> None:
            self._page.pop_dialog()
            self._confirm_all(project, include_worktrees=bool(include.value))

        self._page.show_dialog(ft.AlertDialog(
            modal=True, title=ft.Text("Xoá tất cả session"),
            content=include,
            actions=[ft.TextButton(content="Huỷ", on_click=lambda _e: self._page.pop_dialog()),
                     ft.FilledButton(content="Tiếp tục", on_click=go)],
        ))

    def _confirm_all(self, project: Project, include_worktrees: bool) -> None:
        plan = build_session_plan(PlanMode.ALL, project, include_worktrees=include_worktrees)
        confirm_name = project.worktree_name or _short_name(project)
        run_delete_flow(self._page, self.state, plan, self.rescan,
                        typed_confirmation=confirm_name)


def _short_name(project: Project) -> str:
    raw = (project.cwd or project.slug).replace("\\", "/").rstrip("/")
    return raw.rsplit("/", 1)[-1]
