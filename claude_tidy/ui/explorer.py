from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime

import ttkbootstrap as tb

from claude_tidy.core.grouping import build_session_plan, group_projects
from claude_tidy.core.models import PlanMode, Project, RiskLevel
from claude_tidy.core.risk import classify
from claude_tidy.core.scanner import scan_projects
from claude_tidy.core.usage import human_size
from claude_tidy.ui.delete_flow import run_delete_flow
from claude_tidy.ui.dispatch import Dispatcher, run_in_background
from claude_tidy.ui.state import AppState
from claude_tidy.ui.widgets import CheckTreeview

# Shared with other_views.py — one risk vocabulary, one set of colors.
BADGE = {
    RiskLevel.SAFE: ("an toàn", "success"),
    RiskLevel.WARNING: ("cảnh báo", "warning"),
    RiskLevel.DANGER: ("đang chạy", "danger"),
}
_TAG_FG = {"success": "#198754", "warning": "#b45309", "danger": "#dc3545"}


class ExplorerView(tb.Frame):
    def __init__(self, master, root: tk.Misc, dispatcher: Dispatcher, state: AppState) -> None:
        super().__init__(master)
        self._root = root
        self._dispatcher = dispatcher
        self.state = state
        self.projects: list[Project] = []
        self.risk: dict[str, RiskLevel] = {}
        self.selected: Project | None = None
        self._item_to_project: dict[str, Project] = {}

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = tb.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        header = tb.Frame(left)
        header.pack(fill="x")
        tb.Label(header, text="Projects", font=("", 10, "bold")).pack(side="left")
        self.busy_label = tb.Label(header, text="Đang quét…", bootstyle="secondary")
        tb.Button(header, text="⟳", width=3, command=self.rescan, bootstyle="link"
                 ).pack(side="right")

        self.project_tree = tb.Treeview(left, columns=("info",), show="tree headings",
                                        height=28)
        self.project_tree.heading("#0", text="Project")
        self.project_tree.heading("info", text="")
        self.project_tree.column("#0", width=200)
        self.project_tree.column("info", width=140)
        self.project_tree.pack(fill="both", expand=True)
        self.project_tree.bind("<<TreeviewSelect>>", self._on_select_project)

        right = tb.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        self.header_var = tk.StringVar(value="Chọn một project")
        tb.Label(right, textvariable=self.header_var, font=("", 13, "bold")
                ).grid(row=0, column=0, sticky="w")
        self.subheader_var = tk.StringVar()
        tb.Label(right, textvariable=self.subheader_var, bootstyle="secondary"
                ).grid(row=1, column=0, sticky="w", pady=(0, 6))

        actions = tb.Frame(right)
        actions.grid(row=2, column=0, sticky="w", pady=(0, 6))
        self.delete_checked_btn = tb.Button(actions, text="Xoá đã chọn (0)", state="disabled",
                                            command=self._delete_checked, bootstyle="danger")
        self.delete_checked_btn.pack(side="left", padx=(0, 6))
        self.delete_all_btn = tb.Button(actions, text="Xoá tất cả session", state="disabled",
                                        command=self._delete_all, bootstyle="danger-outline")
        self.delete_all_btn.pack(side="left")

        self.session_tree = CheckTreeview(
            right, columns=("risk", "title", "info"),
            headings={"risk": "", "title": "Tiêu đề", "info": "Chi tiết"},
            on_change=lambda _iid, _v: self._update_buttons(),
            on_activate=self._delete_single,
        )
        self.session_tree.tree.column("#0", width=0, stretch=False)
        for tag, color in _TAG_FG.items():
            self.session_tree.configure_tag(tag, foreground=color)
        self.session_tree.grid(row=3, column=0, sticky="nsew")

    def rescan(self) -> None:
        self.busy_label.pack(side="right", padx=(0, 6))
        run_in_background(self._dispatcher, self._scan_worker, on_done=self._apply_scan)

    def _scan_worker(self) -> tuple[list[Project], dict[str, RiskLevel]]:
        # Off the main thread: scanning a large ~/.claude takes seconds.
        detector = self.state.new_detector()
        now = time.time()
        projects = group_projects(scan_projects(self.state.paths))
        risk = {}
        for p in projects:
            for proj in (p, *p.worktrees):
                for s in proj.sessions:
                    risk[s.session_id] = classify(detector.status(s), s.last_write, now,
                                                  self.state.settings.recent_hours)
        return projects, risk

    def _apply_scan(self, result: tuple[list[Project], dict[str, RiskLevel]]) -> None:
        self.projects, self.risk = result
        if self.selected is not None:
            self.selected = self._find(self.selected.slug)
        self.busy_label.pack_forget()
        self._render_projects()
        self._render_sessions()

    def _find(self, slug: str) -> Project | None:
        for p in self.projects:
            for proj in (p, *p.worktrees):
                if proj.slug == slug:
                    return proj
        return None

    def _render_projects(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        self._item_to_project.clear()
        for p in sorted(self.projects, key=lambda p: p.display_name.lower()):
            self._insert_project(p, parent="")
            for w in p.worktrees:
                self._insert_project(w, parent=p.slug)

    def _insert_project(self, p: Project, parent: str) -> None:
        sub = f"{len(p.sessions)} · {human_size(p.size_bytes)}"
        if p.worktree_name and not p.worktree_exists:
            sub += " · đã xoá"
        self.project_tree.insert(parent, "end", iid=p.slug, text=p.display_name,
                                 values=(sub,), open=True)
        self._item_to_project[p.slug] = p
        if self.selected is not None and self.selected.slug == p.slug:
            self.project_tree.selection_set(p.slug)

    def _on_select_project(self, _event) -> None:
        selection = self.project_tree.selection()
        if not selection:
            return
        self.selected = self._item_to_project.get(selection[0])
        self._render_sessions()

    def _render_sessions(self) -> None:
        self.session_tree.clear()
        p = self.selected
        if p is None:
            self.header_var.set("Chọn một project")
            self.subheader_var.set("")
            self._update_buttons()
            return
        self.header_var.set(p.display_name)
        self.subheader_var.set(f"{p.cwd or p.slug} · {len(p.sessions)} session · "
                               f"{human_size(p.size_bytes)}")
        for s in p.sessions:
            label, tag = BADGE[self.risk.get(s.session_id, RiskLevel.WARNING)]
            when = (datetime.fromtimestamp(s.last_write).strftime("%Y-%m-%d %H:%M")
                   if s.last_write else "?")
            info = f"{s.session_id[:8]} · {when} · {human_size(s.size_bytes)}"
            self.session_tree.insert_row("", s.session_id, "",
                                         (label, s.title or "(không có tiêu đề)", info),
                                         tags=(tag,))
        self._update_buttons()

    def _update_buttons(self) -> None:
        p = self.selected
        n = len(self.session_tree.checked_ids())
        self.delete_checked_btn.configure(text=f"Xoá đã chọn ({n})",
                                          state="normal" if n else "disabled")
        self.delete_all_btn.configure(
            state="normal" if p is not None and (p.sessions or p.worktrees) else "disabled")

    def _delete_single(self, session_id: str) -> None:
        plan = build_session_plan(PlanMode.SINGLE, self.selected, [session_id])
        run_delete_flow(self._root, self._dispatcher, self.state, plan, self.rescan)

    def _delete_checked(self) -> None:
        ids = list(self.session_tree.checked_ids())
        plan = build_session_plan(PlanMode.MULTI, self.selected, ids)
        run_delete_flow(self._root, self._dispatcher, self.state, plan, self.rescan)

    def _delete_all(self) -> None:
        project = self.selected
        if not project.worktrees:
            self._confirm_all(project, include_worktrees=False)
            return

        dialog = tb.Toplevel(title="Xoá tất cả session", transient=self._root)
        dialog.grab_set()
        include_var = tk.BooleanVar(value=False)
        tb.Checkbutton(dialog, variable=include_var,
                      text=f"Áp dụng cho cả {len(project.worktrees)} worktree con"
                      ).pack(padx=16, pady=16)

        def go() -> None:
            dialog.destroy()
            self._confirm_all(project, include_worktrees=include_var.get())

        actions = tb.Frame(dialog)
        actions.pack(pady=(0, 12))
        tb.Button(actions, text="Huỷ", command=dialog.destroy, bootstyle="secondary"
                 ).pack(side="left", padx=6)
        tb.Button(actions, text="Tiếp tục", command=go, bootstyle="primary").pack(side="left")

    def _confirm_all(self, project: Project, include_worktrees: bool) -> None:
        plan = build_session_plan(PlanMode.ALL, project, include_worktrees=include_worktrees)
        confirm_name = project.worktree_name or _short_name(project)
        run_delete_flow(self._root, self._dispatcher, self.state, plan, self.rescan,
                        typed_confirmation=confirm_name)


def _short_name(project: Project) -> str:
    raw = (project.cwd or project.slug).replace("\\", "/").rstrip("/")
    return raw.rsplit("/", 1)[-1]
