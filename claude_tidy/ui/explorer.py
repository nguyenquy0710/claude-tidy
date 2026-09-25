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
        self._row_index = 0

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = tb.Frame(self, width=310)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        left.grid_propagate(False)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        header = tb.Frame(left)
        header.grid(row=0, column=0, sticky="ew")
        tb.Label(header, text="📁 Projects", font=("", 11, "bold")).pack(side="left")
        self.busy_label = tb.Label(header, text="Đang quét…", bootstyle="secondary")
        refresh_btn = tb.Button(header, text="⟳", width=3, command=self.rescan,
                                bootstyle="link")
        refresh_btn.pack(side="right")
        tb.ToolTip(refresh_btn, text="Quét lại danh sách project")

        tb.Separator(left).grid(row=1, column=0, sticky="ew", pady=(6, 6))

        tree_frame = tb.Frame(left)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.project_tree = tb.Treeview(tree_frame, columns=("info",), show="tree headings",
                                        bootstyle="primary")
        self.project_tree.heading("#0", text="Project")
        self.project_tree.heading("info", text="Chi tiết")
        self.project_tree.column("#0", width=185)
        self.project_tree.column("info", width=100, anchor="e")
        self.project_tree.grid(row=0, column=0, sticky="nsew")
        self.project_tree.bind("<<TreeviewSelect>>", self._on_select_project)

        project_vsb = tb.Scrollbar(tree_frame, orient="vertical",
                                   command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=project_vsb.set)
        project_vsb.grid(row=0, column=1, sticky="ns")

        # "odd" only sets background (zebra striping) and the worktree tags
        # only set foreground, so a row can safely carry both at once.
        self.project_tree.tag_configure("odd", background="#f3f5f7")
        self.project_tree.tag_configure("worktree", foreground="#6c757d")
        self.project_tree.tag_configure("worktree-missing", foreground="#dc3545")

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
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_chk = tb.Checkbutton(actions, text="Chọn tất cả", state="disabled",
                                             variable=self.select_all_var,
                                             command=self._toggle_select_all)
        self.select_all_chk.pack(side="left", padx=(0, 12))
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
        self._row_index = 0
        for p in sorted(self.projects, key=lambda p: p.display_name.lower()):
            self._insert_project(p, parent="")
            for w in p.worktrees:
                self._insert_project(w, parent=p.slug)

    def _insert_project(self, p: Project, parent: str) -> None:
        sub = f"{len(p.sessions)} · {human_size(p.size_bytes)}"
        tags = ["odd"] if self._row_index % 2 else []
        self._row_index += 1
        if p.worktree_name:
            if p.worktree_exists:
                icon = "🌿"
                tags.append("worktree")
            else:
                # Full explanation goes in the (wider) session panel header
                # once selected — this narrow sidebar column only has room
                # for a glance-able marker, not the phrase "đã xoá".
                icon = "⚠️"
                tags.append("worktree-missing")
        else:
            icon = "📁"
        self.project_tree.insert(parent, "end", iid=p.slug, text=f"{icon} {p.display_name}",
                                 values=(sub,), open=True, tags=tuple(tags))
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
        subheader = f"{p.cwd or p.slug} · {len(p.sessions)} session · {human_size(p.size_bytes)}"
        if p.worktree_name and not p.worktree_exists:
            subheader += " · ⚠️ thư mục worktree này không còn tồn tại trên đĩa"
        self.subheader_var.set(subheader)
        for s in p.sessions:
            label, tag = BADGE[self.risk.get(s.session_id, RiskLevel.WARNING)]
            when = (datetime.fromtimestamp(s.last_write).strftime("%Y-%m-%d %H:%M")
                   if s.last_write else "?")
            info = f"{s.session_id[:8]} · {when} · {human_size(s.size_bytes)}"
            self.session_tree.insert_row("", s.session_id, "",
                                         (label, s.title or "(không có tiêu đề)", info),
                                         tags=(tag,))
        self.session_tree.render()
        self._update_buttons()

    def _update_buttons(self) -> None:
        p = self.selected
        n = len(self.session_tree.checked_ids())
        total = len(p.sessions) if p is not None else 0
        self.delete_checked_btn.configure(text=f"Xoá đã chọn ({n})",
                                          state="normal" if n else "disabled")
        self.delete_all_btn.configure(
            state="normal" if p is not None and (p.sessions or p.worktrees) else "disabled")
        self.select_all_chk.configure(state="normal" if total else "disabled")
        # Reflect actual selection state without re-triggering the command
        # callback (which would try to check/uncheck everything again).
        self.select_all_var.set(total > 0 and n == total)

    def _toggle_select_all(self) -> None:
        if self.select_all_var.get():
            self.session_tree.check_all()
        else:
            self.session_tree.uncheck_all()
        self._update_buttons()

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
