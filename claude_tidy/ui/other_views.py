from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as tb

from claude_tidy.core.activity import ActivityDetector, ProcessState, claude_desktop_pid
from claude_tidy.core.grouping import build_cache_plan, build_index_plan
from claude_tidy.core.models import CacheGroup, IndexEntry
from claude_tidy.core.scanner import scan_cache
from claude_tidy.core.settings import Settings, save_settings
from claude_tidy.core.usage import human_size
from claude_tidy.ui.delete_flow import run_delete_flow
from claude_tidy.ui.dispatch import Dispatcher, run_in_background
from claude_tidy.ui.state import AppState
from claude_tidy.ui.widgets import CheckTreeview

# Short, human descriptions for the fixed set of cache dir names claude_tidy
# ever scans (see scanner.DESKTOP_CACHE_DIRS) — purely cosmetic, UI-only.
CACHE_DESCRIPTIONS = {
    "Cache": "HTTP cache của Electron",
    "Code Cache": "V8 bytecode cache",
    "GPUCache": "Shader cache",
    "Crashpad": "Báo cáo crash",
    "logs": "Log ứng dụng & MCP",
    "Temp (%TEMP%\\claude)": "File tạm của Claude",
}


def _short_group_label(name: str) -> str:
    return name.removeprefix("Desktop: ")


class CacheView(tb.Frame):
    def __init__(self, master, root: tk.Misc, dispatcher: Dispatcher, state: AppState) -> None:
        super().__init__(master)
        self._root = root
        self._dispatcher = dispatcher
        self.state = state
        self.groups: list[CacheGroup] = []

        top = tb.Frame(self)
        top.pack(fill="x")
        titles = tb.Frame(top)
        titles.pack(side="left", anchor="w")
        tb.Label(titles, text="Cache & file tạm", font=("", 15, "bold")).pack(anchor="w")
        tb.Label(titles, text="Claude Desktop (%APPDATA%\\Claude) và %TEMP%\\claude",
                bootstyle="secondary").pack(anchor="w")
        stat = tb.Frame(top)
        stat.pack(side="right", anchor="e")
        self.total_var = tk.StringVar()
        tb.Label(stat, textvariable=self.total_var, font=("", 13, "bold")).pack(anchor="e")
        tb.Label(stat, text="tổng có thể dọn", bootstyle="secondary", font=("", 9)
                ).pack(anchor="e")
        self.busy_label = tb.Label(self, text="Đang quét…", bootstyle="secondary")
        self.busy_label.pack(anchor="w", pady=(4, 0))

        warn_body = tb.Frame(self)
        self.warning_title = tb.Label(warn_body, font=("", 10, "bold"), bootstyle="warning")
        self.warning_title.pack(anchor="w")
        tb.Label(warn_body, text="Một số file cache đang bị khoá. Đóng Claude Desktop trước "
                                 "khi xoá để tránh lỗi và dữ liệu dở dang.", bootstyle="secondary"
                ).pack(anchor="w")
        self.warning = tb.Frame(self, bootstyle="warning")
        warn_body.pack(in_=self.warning, side="left", fill="x", expand=True, padx=10, pady=8)
        tb.Button(self.warning, text="Kiểm tra lại", command=self.rescan, bootstyle="secondary"
                 ).pack(side="right", padx=10)

        self.tree = CheckTreeview(self, columns=("name", "path", "files", "size", "pct"),
                                  headings={"name": "Nhóm", "path": "Đường dẫn",
                                           "files": "File", "size": "Dung lượng",
                                           "pct": "Tỉ lệ"},
                                  on_change=lambda _iid, _v: self._sync())
        self.tree.pack(fill="both", expand=True, pady=(10, 0))
        for cid, width in ((3, 90), (4, 100), (5, 70)):
            self.tree.table.tablecolumns[cid].configure(width=width, stretch=False)

        footer = tb.Frame(self)
        footer.pack(fill="x", pady=(8, 0))
        self.summary_var = tk.StringVar()
        tb.Label(footer, textvariable=self.summary_var, bootstyle="secondary"
                ).pack(side="left")
        self.delete_btn = tb.Button(footer, text="Xem trước & xoá", state="disabled",
                                    command=self._delete, bootstyle="primary")
        self.delete_btn.pack(side="right")

    def rescan(self) -> None:
        self.busy_label.pack(anchor="w", pady=(4, 0))
        run_in_background(self._dispatcher, self._worker, on_done=self._apply)

    def _worker(self) -> tuple[list[CacheGroup], int | None]:
        return scan_cache(self.state.paths), claude_desktop_pid()

    def _apply(self, result: tuple[list[CacheGroup], int | None]) -> None:
        self.busy_label.pack_forget()
        self.groups, pid = result
        if pid is not None:
            self.warning_title.configure(text=f"Claude Desktop đang chạy (PID {pid})")
            self.warning.pack(fill="x", pady=(0, 8), before=self.tree)
        else:
            self.warning.pack_forget()

        self.tree.clear()
        total = sum(g.size_bytes for g in self.groups) or 1
        self.total_var.set(human_size(total))
        for g in self.groups:
            pct = g.size_bytes / total * 100
            label = _short_group_label(g.name)
            desc = CACHE_DESCRIPTIONS.get(label, "")
            self.tree.insert_row(
                "", g.name, "",
                (f"{label}  ·  {desc}", str(g.root), str(g.file_count),
                 human_size(g.size_bytes), f"{pct:.0f}%"))
        self.tree.render()
        self._sync()

    def _sync(self) -> None:
        checked = self.tree.checked_ids()
        size = sum(g.size_bytes for g in self.groups if g.name in checked)
        if checked:
            self.summary_var.set(
                f"Đã chọn {len(checked)} nhóm · {human_size(size)} · sẽ đi qua cùng pipeline: "
                "dry-run → backup .zip + sha256 → xoá")
        else:
            self.summary_var.set("Tick một nhóm cache để xem trước & xoá.")
        self.delete_btn.configure(state="normal" if checked else "disabled")

    def _delete(self) -> None:
        checked = self.tree.checked_ids()
        plan = build_cache_plan([g for g in self.groups if g.name in checked])
        run_delete_flow(self._root, self._dispatcher, self.state, plan, self.rescan)


class IndexView(tb.Frame):
    """Orphaned sessions/<pid>.json files — confirmed and deleted one at a time.

    Deliberately single-selection, not checkbox multi-select (roadmap decision
    6.5): there is no "select all" shortcut, and firing `run_delete_flow` for
    several entries at once would stack multiple modal dialogs on top of each
    other. One row, one dialog, one decision.
    """

    def __init__(self, master, root: tk.Misc, dispatcher: Dispatcher, state: AppState) -> None:
        super().__init__(master)
        self._root = root
        self._dispatcher = dispatcher
        self.state = state
        self.entries: dict[str, IndexEntry] = {}

        header = tb.Frame(self)
        header.pack(fill="x")
        tb.Label(header, text="Index mồ côi", font=("", 15, "bold")).pack(anchor="w")
        tb.Label(header, text="File ~/.claude/sessions/<pid>.json của process đã tắt, hoặc PID "
                              "đã bị hệ điều hành cấp lại cho process khác (create_time không "
                              "khớp procStart). Mỗi file cần được xác nhận riêng.",
                bootstyle="secondary", wraplength=900).pack(anchor="w")
        self.busy_label = tb.Label(self, text="Đang quét…", bootstyle="secondary")
        self.busy_label.pack(anchor="w", pady=(4, 0))

        self.tree = CheckTreeview(self, columns=("file", "pid", "procstart", "reason"),
                                  headings={"file": "File", "pid": "PID",
                                           "procstart": "procStart", "reason": "Lý do"},
                                  show_checkboxes=False,
                                  on_activate=self._delete_one)
        self.tree.tree.configure(selectmode="browse")  # one row at a time, no ctrl-click stacking
        self.tree.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync())
        self.tree.pack(fill="both", expand=True, pady=(8, 0))
        # 0=file 1=pid 2=procstart 3=reason(4=hidden iid) — pid/procstart get
        # fixed widths that fit their content; reason keeps its stretch=True
        # default so it gets the leftover space instead of being clipped.
        for cid, width in ((1, 60), (2, 155)):
            self.tree.table.tablecolumns[cid].configure(width=width, stretch=False)

        footer = tb.Frame(self)
        footer.pack(fill="x", pady=(8, 0))
        tb.Label(footer, text="ⓘ Không có nút \"xoá tất cả\" ở tab này — theo thiết kế.",
                bootstyle="secondary").pack(side="left")
        self.delete_btn = tb.Button(footer, text="Xoá file này…", state="disabled",
                                    command=self._delete_selected, bootstyle="danger")
        self.delete_btn.pack(side="right")

    def rescan(self) -> None:
        self.busy_label.pack(anchor="w", pady=(4, 0))
        run_in_background(self._dispatcher, self._worker, on_done=self._apply)

    def _worker(self) -> list[tuple[IndexEntry, str]]:
        detector = self.state.new_detector()
        return [(e, self._reason(detector, e)) for e in detector.orphan_entries()]

    @staticmethod
    def _reason(detector: ActivityDetector, entry: IndexEntry) -> str:
        state = detector.orphan_state(entry)
        if entry.corrupt:
            return "File index hỏng · không đọc được JSON"
        if state is ProcessState.REUSED:
            return "PID bị tái sử dụng · create_time hiện tại không khớp procStart"
        return "Process đã tắt · không còn process nào với PID này"

    def _apply(self, orphans: list[tuple[IndexEntry, str]]) -> None:
        self.busy_label.pack_forget()
        self.entries = {e.path.name: e for e, _ in orphans}
        self.tree.clear()
        for e, reason in orphans:
            proc_start = (datetime.fromtimestamp(e.proc_start).strftime("%Y-%m-%d %H:%M:%S")
                         if e.proc_start else "?")
            self.tree.insert_row("", e.path.name, "",
                                 (e.path.name, str(e.pid), proc_start, reason), checkable=False)
        self.tree.render()
        self._sync()

    def _sync(self) -> None:
        self.delete_btn.configure(state="normal" if self.tree.selected_id() else "disabled")

    def _delete_selected(self) -> None:
        key = self.tree.selected_id()
        if key:
            self._delete_one(key)

    def _delete_one(self, key: str) -> None:
        entry = self.entries[key]
        run_delete_flow(self._root, self._dispatcher, self.state,
                        build_index_plan(entry), self.rescan)


# ttkbootstrap themes offered in the picker below. Selecting one is
# cosmetic-only for now — the roadmap explicitly deferred live theme
# switching out of the MVP (plans/2026-09-25-ttkbootstrap-ui-migration-
# planning.md, question 5: "mặc định cosmo, chưa cho đổi trong MVP") — so
# this shows the template's control without wiring persistence/live-reload.
THEME_CHOICES = ("cosmo", "flatly", "litera", "darkly")


class SettingsView(tb.Frame):
    def __init__(self, master, root: tk.Misc, dispatcher: Dispatcher, state: AppState) -> None:
        super().__init__(master)
        self._root = root
        self.state = state
        s = state.settings

        tb.Label(self, text="Cài đặt", font=("", 15, "bold")).pack(anchor="w", pady=(0, 12))

        columns = tb.Frame(self)
        columns.pack(fill="x")
        columns.columnconfigure(0, weight=1, uniform="col")
        columns.columnconfigure(1, weight=1, uniform="col")
        backup_col = tb.Frame(columns)
        backup_col.grid(row=0, column=0, sticky="new", padx=(0, 24))
        detect_col = tb.Frame(columns)
        detect_col.grid(row=0, column=1, sticky="new")

        tb.Label(backup_col, text="Backup", font=("", 11, "bold")).pack(anchor="w")
        tb.Label(backup_col, text="Mọi thao tác xoá đều nén .zip + manifest sha256 trước.",
                bootstyle="secondary", wraplength=380).pack(anchor="w", pady=(0, 8))
        self.backup_dir_var = tk.StringVar(value=str(s.backup_dir))
        self._field_with_browse(backup_col, "Thư mục lưu backup", self.backup_dir_var)
        self.backup_stats_var = tk.StringVar(value=self._backup_stats_text())
        tb.Label(backup_col, textvariable=self.backup_stats_var, bootstyle="secondary"
                ).pack(anchor="w", pady=(2, 10))
        self.auto_prune_var = tk.BooleanVar(value=s.auto_prune_backups)
        self._switch_field(backup_col, "Tự xoá backup cũ",
                           "Xoá bản backup quá hạn khi khởi động app", self.auto_prune_var)
        self.retention_var = tk.StringVar(value=str(s.retention_days))
        self._spin_field(backup_col, "Giữ backup trong", self.retention_var, "ngày")

        tb.Label(detect_col, text="Phát hiện session", font=("", 11, "bold")).pack(anchor="w")
        tb.Label(detect_col, text="Quyết định badge rủi ro và mục nào cần xác nhận.",
                bootstyle="secondary", wraplength=380).pack(anchor="w", pady=(0, 8))
        self.maybe_active_var = tk.StringVar(value=str(s.maybe_active_minutes))
        self._spin_field(detect_col, "Ngưỡng “có thể đang active”", self.maybe_active_var,
                         "phút", hint="Session ghi file gần hơn mốc này → cần xác nhận")
        self.recent_var = tk.StringVar(value=str(s.recent_hours))
        self._spin_field(detect_col, "Ngưỡng “mới dùng”", self.recent_var, "giờ",
                         hint="Hiện badge cảnh báo cho session mới hơn mốc này")
        tb.Label(detect_col, text="Session có PID đang chạy (create_time khớp procStart) luôn "
                                  "bị bỏ qua — không có cài đặt nào tắt được.",
                bootstyle="secondary", wraplength=380).pack(anchor="w", pady=(8, 0))

        theme_row = tb.Frame(self)
        theme_row.pack(fill="x", pady=(16, 0))
        theme_labels = tb.Frame(theme_row)
        theme_labels.pack(side="left")
        tb.Label(theme_labels, text="Giao diện", font=("", 10, "bold")).pack(anchor="w")
        tb.Label(theme_labels, text="Theme ttkbootstrap", bootstyle="secondary").pack(anchor="w")
        self.theme_var = tk.StringVar(value="cosmo")
        tb.Combobox(theme_row, textvariable=self.theme_var, values=THEME_CHOICES,
                   state="disabled", width=12).pack(side="left", padx=12)

        actions = tb.Frame(self)
        actions.pack(fill="x", pady=(16, 0))
        self.status_var = tk.StringVar()
        self.status_label = tb.Label(actions, textvariable=self.status_var)
        self.status_label.pack(side="left")
        tb.Button(actions, text="Lưu", command=self._save, bootstyle="primary"
                 ).pack(side="right")
        tb.Button(actions, text="Khôi phục mặc định", command=self._restore_defaults,
                 bootstyle="secondary-outline").pack(side="right", padx=(0, 8))

        tb.Label(self, text=f"Cấu hình lưu tại {state.paths.settings_file}", bootstyle="secondary"
                ).pack(anchor="w", pady=(16, 0))

    def rescan(self) -> None:
        pass  # nothing to reload from disk; settings only change through Save

    def _backup_stats_text(self) -> str:
        try:
            zips = list(self.state.settings.backup_dir.glob("*.zip"))
        except OSError:
            return "Chưa có bản backup nào."
        if not zips:
            return "Chưa có bản backup nào."
        size = sum(z.stat().st_size for z in zips if z.is_file())
        return f"Hiện có {len(zips)} bản backup · {human_size(size)}"

    def _field_with_browse(self, parent, label: str, var: tk.StringVar) -> None:
        tb.Label(parent, text=label, bootstyle="secondary", font=("", 9)).pack(anchor="w")
        row = tb.Frame(parent)
        row.pack(fill="x", pady=(2, 0))
        tb.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tb.Button(row, text="Chọn thư mục…", command=lambda: self._browse(var),
                 bootstyle="secondary-outline").pack(side="left")

    def _switch_field(self, parent, label: str, hint: str, var: tk.BooleanVar) -> None:
        row = tb.Frame(parent)
        row.pack(fill="x", pady=6)
        texts = tb.Frame(row)
        texts.pack(side="left", fill="x", expand=True)
        tb.Label(texts, text=label).pack(anchor="w")
        tb.Label(texts, text=hint, bootstyle="secondary", font=("", 9)).pack(anchor="w")
        tb.Checkbutton(row, variable=var, bootstyle="round-toggle").pack(side="right")

    def _spin_field(self, parent, label: str, var: tk.StringVar, unit: str,
                    hint: str | None = None) -> None:
        row = tb.Frame(parent)
        row.pack(fill="x", pady=6)
        texts = tb.Frame(row)
        texts.pack(side="left", fill="x", expand=True)
        tb.Label(texts, text=label).pack(anchor="w")
        if hint:
            tb.Label(texts, text=hint, bootstyle="secondary", font=("", 9), wraplength=260
                    ).pack(anchor="w")
        spin = tb.Frame(row)
        spin.pack(side="right")
        tb.Spinbox(spin, textvariable=var, from_=0, to=100000, width=6).pack(side="left")
        tb.Label(spin, text=unit, bootstyle="secondary").pack(side="left", padx=(4, 0))

    def _browse(self, var: tk.StringVar) -> None:
        chosen = filedialog.askdirectory(parent=self._root, initialdir=var.get() or None)
        if chosen:
            var.set(chosen)

    def _restore_defaults(self) -> None:
        defaults = Settings.defaults(self.state.paths)
        self.backup_dir_var.set(str(defaults.backup_dir))
        self.retention_var.set(str(defaults.retention_days))
        self.auto_prune_var.set(defaults.auto_prune_backups)
        self.maybe_active_var.set(str(defaults.maybe_active_minutes))
        self.recent_var.set(str(defaults.recent_hours))
        self._set_status("Đã khôi phục mặc định — bấm Lưu để áp dụng.", "warning")

    def _save(self) -> None:
        try:
            values = {
                "retention_days": int(self.retention_var.get()),
                "maybe_active_minutes": int(self.maybe_active_var.get()),
                "recent_hours": int(self.recent_var.get()),
            }
        except ValueError:
            self._set_status("Các ngưỡng phải là số nguyên.", "danger")
            return
        if min(values.values()) < 0 or not self.backup_dir_var.get():
            self._set_status("Giá trị không hợp lệ.", "danger")
            return
        s = self.state.settings
        s.backup_dir = Path(self.backup_dir_var.get())
        s.auto_prune_backups = bool(self.auto_prune_var.get())
        for k, v in values.items():
            setattr(s, k, v)
        save_settings(self.state.paths, s)
        self.backup_stats_var.set(self._backup_stats_text())
        self._set_status("Đã lưu.", "success")

    def _set_status(self, text: str, style: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(bootstyle=style)
