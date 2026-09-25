from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime

import ttkbootstrap as tb

from claude_tidy.core.activity import ActivityDetector
from claude_tidy.core.grouping import build_session_plan, group_projects
from claude_tidy.core.models import Activity, PlanMode, Project, RiskLevel, SessionBundle
from claude_tidy.core.risk import classify
from claude_tidy.core.scanner import scan_projects
from claude_tidy.core.usage import human_size
from claude_tidy.ui.delete_flow import run_delete_flow
from claude_tidy.ui.dispatch import Dispatcher, run_in_background
from claude_tidy.ui.state import AppState
from claude_tidy.ui.theme import DANGER_FG, TEXT_MUTED, WARNING_FG
from claude_tidy.ui.theme import font_family as ff
from claude_tidy.ui.widgets import CheckTreeview

RISK_FILTERS: tuple[tuple[str, RiskLevel | None], ...] = (
    ("Tất cả", None),
    ("An toàn", RiskLevel.SAFE),
    ("Cảnh báo", RiskLevel.WARNING),
    ("Đang chạy", RiskLevel.DANGER),
)


def _relative_time(ts: float, now: float) -> str:
    if ts <= 0:
        return "?"
    delta = now - ts
    if delta < 60:
        return "vừa xong"
    if delta < 3600:
        return f"{int(delta // 60)} phút trước"
    if delta < 86400:
        return f"{int(delta // 3600)} giờ trước"
    days = int(delta // 86400)
    if days < 30:
        return f"{days} ngày trước"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


class ExplorerView(tb.Frame):
    def __init__(
        self, master, root: tk.Misc, dispatcher: Dispatcher, state: AppState,
        status_var: tk.StringVar | None = None,
    ) -> None:
        super().__init__(master)
        self._root = root
        self._dispatcher = dispatcher
        self.state = state
        self._status_var = status_var
        self.projects: list[Project] = []
        self.risk: dict[str, RiskLevel] = {}
        self.activity: dict[str, Activity] = {}
        self.active_pid: dict[str, int] = {}
        self.selected: Project | None = None
        self._item_to_project: dict[str, Project] = {}
        self._session_by_id: dict[str, SessionBundle] = {}
        self._risk_filter: RiskLevel | None = None

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_left()
        self._build_right()

    # ------------------------------------------------------------------ left

    def _build_left(self) -> None:
        # A distinct off-white panel from the (white) main content area,
        # matching the mockup — see Sidebar.TFrame/TLabel in theme.py.
        left = tb.Frame(self, width=300, style="Sidebar.TFrame")
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        left.grid_propagate(False)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        header = tb.Frame(left, style="Sidebar.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tb.Label(header, text="PROJECT", font=(ff(), 9, "bold"), style="SidebarMuted.TLabel"
                 ).pack(side="left")
        self.project_stats_var = tk.StringVar()
        tb.Label(header, textvariable=self.project_stats_var, font=(ff(), 9),
                style="SidebarMuted.TLabel").pack(side="right")

        self.project_filter_var = tk.StringVar()
        self.project_filter_var.trace_add("write", lambda *_a: self._render_projects())
        filter_entry = tb.Entry(left, textvariable=self.project_filter_var)
        filter_entry.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        # ttkbootstrap has no native placeholder text; a light hint label
        # overlaid isn't worth the complexity here — the entry's own accname
        # in the status bar / tooltip carries the hint instead.
        tb.ToolTip(filter_entry, text="Lọc project theo tên")

        tree_frame = tb.Frame(left, style="Sidebar.TFrame")
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.project_tree = tb.Treeview(tree_frame, columns=("info",), show="tree headings")
        self.project_tree.heading("#0", text="Project")
        self.project_tree.heading("info", text="")
        self.project_tree.column("#0", width=190)
        self.project_tree.column("info", width=95, anchor="e")
        self.project_tree.grid(row=0, column=0, sticky="nsew")
        self.project_tree.bind("<<TreeviewSelect>>", self._on_select_project)

        project_vsb = tb.Scrollbar(tree_frame, orient="vertical",
                                    command=self.project_tree.yview)
        self.project_tree.configure(yscrollcommand=project_vsb.set)
        project_vsb.grid(row=0, column=1, sticky="ns")

        self.project_tree.tag_configure("worktree-missing", foreground=DANGER_FG)

    def _build_right(self) -> None:
        right = tb.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(4, weight=1)
        right.columnconfigure(0, weight=1)

        top = tb.Frame(right)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        titles = tb.Frame(top)
        titles.grid(row=0, column=0, sticky="w")
        self.header_var = tk.StringVar(value="Chọn một project")
        tb.Label(titles, textvariable=self.header_var, font=(ff(), 15, "bold")).pack(anchor="w")
        self.subheader_var = tk.StringVar()
        tb.Label(titles, textvariable=self.subheader_var, bootstyle="secondary"
                 ).pack(anchor="w")

        stats = tb.Frame(top)
        stats.grid(row=0, column=1, sticky="e")
        self.stat_sessions_var = tk.StringVar()
        self.stat_size_var = tk.StringVar()
        self.stat_active_var = tk.StringVar()
        self._stat_block(stats, self.stat_sessions_var, "session")
        self._stat_block(stats, self.stat_size_var, "trên đĩa")
        self._stat_block(stats, self.stat_active_var, "đang chạy")

        chips = tb.Frame(right)
        chips.grid(row=1, column=0, sticky="w", pady=(10, 6))
        self.chip_buttons: dict[RiskLevel | None, tb.Button] = {}
        for label, level in RISK_FILTERS:
            btn = tb.Button(chips, text=label, style="Neutral.TButton",
                             command=lambda lv=level: self._set_risk_filter(lv))
            if level is None:
                btn.configure(bootstyle="primary")
            btn.pack(side="left", padx=(0, 6))
            self.chip_buttons[level] = btn

        actions = tb.Frame(right)
        actions.grid(row=2, column=0, sticky="w", pady=(0, 8))
        tb.Button(actions, text="⟳ Quét lại", command=self.rescan, style="Neutral.TButton"
                  ).pack(side="left", padx=(0, 8))
        self.delete_checked_btn = tb.Button(actions, text="Xoá đã chọn", state="disabled",
                                             command=self._delete_checked, bootstyle="primary")
        self.delete_checked_btn.pack(side="left", padx=(0, 8))
        self.delete_all_btn = tb.Button(actions, text="Xoá tất cả session…", state="disabled",
                                         command=self._delete_all, bootstyle="danger-outline")
        self.delete_all_btn.pack(side="left")

        self.busy_label = tb.Label(right, text="Đang quét…", bootstyle="secondary")
        self.busy_label.grid(row=3, column=0, sticky="w")

        self.session_tree = CheckTreeview(
            right, columns=("session", "last", "messages", "size", "risk"),
            headings={"session": "Session", "last": "Ghi lần cuối", "messages": "Tin nhắn",
                      "size": "Dung lượng", "risk": "Rủi ro"},
            on_change=lambda _iid, _v: self._update_buttons(),
            on_activate=self._delete_single,
        )
        self.session_tree.grid(row=4, column=0, sticky="nsew")
        # Every named column defaults to stretch=True with an equal share;
        # narrow the fixed-content ones so "Session" (title + filename, the
        # longest text) gets the leftover space instead of splitting evenly.
        for cid, width in ((2, 110), (3, 80), (4, 90), (5, 140)):
            self.session_tree.table.tablecolumns[cid].configure(width=width, stretch=False)
        for tag, color in (("danger", DANGER_FG), ("warning", WARNING_FG),
                           ("safe", TEXT_MUTED)):
            self.session_tree.configure_tag(tag, foreground=color)

    def _stat_block(self, parent, var: tk.StringVar, label: str) -> None:
        block = tb.Frame(parent)
        block.pack(side="left", padx=(16, 0))
        tb.Label(block, textvariable=var, font=(ff(), 13, "bold")).pack(anchor="e")
        tb.Label(block, text=label, bootstyle="secondary", font=(ff(), 9)).pack(anchor="e")

    # --------------------------------------------------------------- scanning

    def rescan(self) -> None:
        self.busy_label.grid()
        run_in_background(self._dispatcher, self._scan_worker, on_done=self._apply_scan)

    def _scan_worker(self):
        # Off the main thread: scanning a large ~/.claude takes seconds.
        started = time.perf_counter()
        detector = self.state.new_detector()
        now = time.time()
        projects = group_projects(scan_projects(self.state.paths))
        risk: dict[str, RiskLevel] = {}
        activity: dict[str, Activity] = {}
        active_pid = self._active_pids(detector)
        for p in projects:
            for proj in (p, *p.worktrees):
                for s in proj.sessions:
                    status = detector.status(s)
                    activity[s.session_id] = status
                    risk[s.session_id] = classify(status, s.last_write, now,
                                                   self.state.settings.recent_hours)
        elapsed = time.perf_counter() - started
        return projects, risk, activity, active_pid, elapsed

    @staticmethod
    def _active_pids(detector: ActivityDetector) -> dict[str, int]:
        return {
            e.session_id: e.pid
            for e in detector.index_entries()
            if e.session_id and e.pid is not None
        }

    def _apply_scan(self, result) -> None:
        self.projects, self.risk, self.activity, self.active_pid, elapsed = result
        if self.selected is not None:
            self.selected = self._find(self.selected.slug)
        self.busy_label.grid_remove()
        self._render_projects()
        self._render_sessions()
        self._update_status_bar(elapsed)

    def _update_status_bar(self, elapsed: float) -> None:
        if self._status_var is None:
            return
        total_sessions = sum(len(s) for s in self._all_session_lists())
        self._status_var.set(
            f"Đã quét {len(self.projects)} project · {total_sessions} session · "
            f"{human_size(self._total_size())} trong {elapsed:.1f} s"
        )

    def _all_session_lists(self) -> list[list[SessionBundle]]:
        return [proj.sessions for p in self.projects for proj in (p, *p.worktrees)]

    def _total_size(self) -> int:
        return sum(b.size_bytes for bundles in self._all_session_lists() for b in bundles)

    def _find(self, slug: str) -> Project | None:
        for p in self.projects:
            for proj in (p, *p.worktrees):
                if proj.slug == slug:
                    return proj
        return None

    # ------------------------------------------------------------- rendering

    def _render_projects(self) -> None:
        self.project_tree.delete(*self.project_tree.get_children())
        self._item_to_project.clear()
        query = self.project_filter_var.get().strip().lower()
        self.project_stats_var.set(
            f"{len(self.projects)} project · {human_size(self._total_size())}")
        for p in sorted(self.projects, key=lambda p: p.display_name.lower()):
            if query and query not in p.display_name.lower():
                continue
            self._insert_project(p, parent="")
            for w in p.worktrees:
                self._insert_project(w, parent=p.slug)

    def _insert_project(self, p: Project, parent: str) -> None:
        sub = f"{len(p.sessions)} · {human_size(p.size_bytes)}"
        tags = ()
        if p.worktree_name and not p.worktree_exists:
            sub += " · mất"
            tags = ("worktree-missing",)
        self.project_tree.insert(parent, "end", iid=p.slug, text=p.display_name,
                                  values=(sub,), open=True, tags=tags)
        self._item_to_project[p.slug] = p
        if self.selected is not None and self.selected.slug == p.slug:
            self.project_tree.selection_set(p.slug)

    def _on_select_project(self, _event) -> None:
        selection = self.project_tree.selection()
        if not selection:
            return
        self.selected = self._item_to_project.get(selection[0])
        self._render_sessions()

    def _visible_sessions(self, p: Project) -> list[SessionBundle]:
        if self._risk_filter is None:
            return p.sessions
        return [s for s in p.sessions if self.risk.get(s.session_id) == self._risk_filter]

    def _set_risk_filter(self, level: RiskLevel | None) -> None:
        self._risk_filter = level
        for lv, btn in self.chip_buttons.items():
            if lv == level:
                btn.configure(bootstyle="primary")
            else:
                btn.configure(style="Neutral.TButton")
        self._render_sessions()

    def _render_sessions(self) -> None:
        self.session_tree.clear()
        self._session_by_id.clear()
        p = self.selected
        if p is None:
            self.header_var.set("Chọn một project")
            self.subheader_var.set("")
            for var in (self.stat_sessions_var, self.stat_size_var, self.stat_active_var):
                var.set("–")
            self._update_buttons()
            return

        self.header_var.set(p.display_name)
        self.subheader_var.set(f"{p.cwd or p.slug}")
        if p.worktree_name and not p.worktree_exists:
            self.subheader_var.set(self.subheader_var.get() +
                                    " · ⚠️ thư mục worktree này không còn tồn tại trên đĩa")
        active_count = sum(1 for s in p.sessions if self.risk.get(s.session_id) is RiskLevel.DANGER)
        self.stat_sessions_var.set(str(len(p.sessions)))
        self.stat_size_var.set(human_size(p.size_bytes))
        self.stat_active_var.set(str(active_count))

        now = time.time()
        for s in self._visible_sessions(p):
            self._session_by_id[s.session_id] = s
            tag, label = self._risk_display(s)
            checkable = self.risk.get(s.session_id) is not RiskLevel.DANGER
            session_col = f"{s.title or '(không có tiêu đề)'}  ·  {s.session_id[:8]}.jsonl"
            self.session_tree.insert_row(
                "", s.session_id, "",
                (session_col, _relative_time(s.last_write, now), str(s.message_count),
                 human_size(s.size_bytes), label),
                tags=(tag,), checkable=checkable,
            )
        self.session_tree.render()
        self._update_buttons()

    def _risk_display(self, s: SessionBundle) -> tuple[str, str]:
        risk = self.risk.get(s.session_id, RiskLevel.WARNING)
        if risk is RiskLevel.DANGER:
            pid = self.active_pid.get(s.session_id)
            return "danger", f"Đang chạy · PID {pid}" if pid else "Đang chạy"
        if risk is RiskLevel.WARNING:
            if self.activity.get(s.session_id) is Activity.MAYBE_ACTIVE:
                return "warning", "Có thể active"
            return "warning", "Mới dùng (<24h)"
        return "safe", "An toàn"

    def _update_buttons(self) -> None:
        p = self.selected
        checked = self.session_tree.checked_ids()
        n = len(checked)
        size = sum(self._session_by_id[sid].size_bytes for sid in checked
                   if sid in self._session_by_id)
        self.delete_checked_btn.configure(
            text=f"Xoá đã chọn ({n} · {human_size(size)})" if n else "Xoá đã chọn",
            state="normal" if n else "disabled")
        self.delete_all_btn.configure(
            state="normal" if p is not None and (p.sessions or p.worktrees) else "disabled")

    # --------------------------------------------------------------- actions

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
