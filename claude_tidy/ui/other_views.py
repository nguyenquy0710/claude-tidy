from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import ttkbootstrap as tb

from claude_tidy.core.activity import is_claude_desktop_running
from claude_tidy.core.grouping import build_cache_plan, build_index_plan
from claude_tidy.core.models import CacheGroup, IndexEntry
from claude_tidy.core.scanner import scan_cache
from claude_tidy.core.settings import save_settings
from claude_tidy.core.usage import human_size
from claude_tidy.ui.delete_flow import run_delete_flow
from claude_tidy.ui.dispatch import Dispatcher, run_in_background
from claude_tidy.ui.state import AppState
from claude_tidy.ui.widgets import CheckTreeview


class CacheView(tb.Frame):
    def __init__(self, master, root: tk.Misc, dispatcher: Dispatcher, state: AppState) -> None:
        super().__init__(master)
        self._root = root
        self._dispatcher = dispatcher
        self.state = state
        self.groups: list[CacheGroup] = []

        header = tb.Frame(self)
        header.pack(fill="x")
        tb.Label(header, text="Cache Claude Desktop & file tạm", font=("", 13, "bold")
                ).pack(side="left")
        tb.Button(header, text="⟳", width=3, command=self.rescan, bootstyle="link"
                 ).pack(side="right")
        self.busy_label = tb.Label(header, text="Đang quét…", bootstyle="secondary")

        self.warning = tb.Label(
            self, bootstyle="inverse-warning", wraplength=700,
            text="Claude Desktop đang chạy — một số file cache có thể bị khoá và sẽ được bỏ "
                 "qua. Nên tắt Claude Desktop trước khi dọn.")

        self.delete_btn = tb.Button(self, text="Xoá mục đã chọn", state="disabled",
                                    command=self._delete, bootstyle="danger")
        self.delete_btn.pack(anchor="w", pady=6)

        self.tree = CheckTreeview(self, columns=("name", "path", "size"),
                                  headings={"name": "Nhóm", "path": "Vị trí",
                                           "size": "Dung lượng"},
                                  on_change=lambda _iid, _v: self._sync())
        self.tree.pack(fill="both", expand=True)

    def rescan(self) -> None:
        self.busy_label.pack(side="right", padx=(0, 6))
        run_in_background(self._dispatcher, self._worker, on_done=self._apply)

    def _worker(self) -> tuple[list[CacheGroup], bool]:
        return scan_cache(self.state.paths), is_claude_desktop_running()

    def _apply(self, result: tuple[list[CacheGroup], bool]) -> None:
        self.busy_label.pack_forget()
        self.groups, running = result
        if running:
            self.warning.pack(fill="x", pady=(0, 6), before=self.delete_btn)
        else:
            self.warning.pack_forget()
        self.tree.clear()
        for g in self.groups:
            self.tree.insert_row("", g.name, "", (g.name, str(g.root), human_size(g.size_bytes)))
        self.tree.render()
        self._sync()

    def _sync(self) -> None:
        n = len(self.tree.checked_ids())
        self.delete_btn.configure(state="normal" if n else "disabled")

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
        tb.Label(header, text="Index session mồ côi", font=("", 13, "bold")).pack(side="left")
        tb.Button(header, text="⟳", width=3, command=self.rescan, bootstyle="link"
                 ).pack(side="right")
        self.busy_label = tb.Label(header, text="Đang quét…", bootstyle="secondary")
        tb.Label(self, text="File sessions/<pid>.json của process đã tắt hoặc PID đã bị tái "
                            "sử dụng. Mỗi file cần xác nhận riêng.", bootstyle="secondary"
                ).pack(anchor="w", pady=(2, 6))

        self.delete_btn = tb.Button(self, text="Xoá mục đã chọn", state="disabled",
                                    command=self._delete_selected, bootstyle="danger")
        self.delete_btn.pack(anchor="w", pady=(0, 6))

        self.tree = CheckTreeview(self, columns=("name", "cwd", "updated"),
                                  headings={"name": "Tên / PID", "cwd": "Thư mục",
                                           "updated": "Cập nhật cuối"},
                                  show_checkboxes=False,
                                  on_activate=self._delete_one)
        self.tree.tree.configure(selectmode="browse")  # one row at a time, no ctrl-click stacking
        self.tree.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync())
        self.tree.pack(fill="both", expand=True)

    def rescan(self) -> None:
        self.busy_label.pack(side="right", padx=(0, 6))
        run_in_background(self._dispatcher, self._worker, on_done=self._apply)

    def _worker(self) -> list[IndexEntry]:
        return self.state.new_detector().orphan_entries()

    def _apply(self, orphans: list[IndexEntry]) -> None:
        self.busy_label.pack_forget()
        self.entries = {e.path.name: e for e in orphans}
        self.tree.clear()
        for e in orphans:
            updated = (datetime.fromtimestamp(e.updated_at).strftime("%Y-%m-%d %H:%M")
                      if e.updated_at else "?")
            title = e.name or ("(file hỏng)" if e.corrupt else "(không tên)")
            self.tree.insert_row("", e.path.name, "",
                                 (f"{title} — PID {e.pid}", e.cwd or "?", updated),
                                 checkable=False)
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


class SettingsView(tb.Frame):
    def __init__(self, master, root: tk.Misc, dispatcher: Dispatcher, state: AppState) -> None:
        super().__init__(master)
        self._root = root
        self.state = state
        s = state.settings

        tb.Label(self, text="Cài đặt", font=("", 13, "bold")).pack(anchor="w", pady=(0, 10))

        self.backup_dir_var = tk.StringVar(value=str(s.backup_dir))
        self._field_with_browse("Thư mục backup", self.backup_dir_var)
        self.retention_var = tk.StringVar(value=str(s.retention_days))
        self._field("Số ngày giữ backup", self.retention_var)
        self.auto_prune_var = tk.BooleanVar(value=s.auto_prune_backups)
        tb.Checkbutton(self, text="Tự xoá backup quá hạn", variable=self.auto_prune_var
                      ).pack(anchor="w", pady=4)
        self.maybe_active_var = tk.StringVar(value=str(s.maybe_active_minutes))
        self._field("Ngưỡng 'có thể đang dùng' (phút)", self.maybe_active_var)
        self.recent_var = tk.StringVar(value=str(s.recent_hours))
        self._field("Ngưỡng 'mới dùng' cho badge cảnh báo (giờ)", self.recent_var)

        row = tb.Frame(self)
        row.pack(anchor="w", pady=10)
        tb.Button(row, text="Lưu", command=self._save, bootstyle="primary"
                 ).pack(side="left", padx=(0, 8))
        self.status_var = tk.StringVar()
        self.status_label = tb.Label(row, textvariable=self.status_var)
        self.status_label.pack(side="left")

        tb.Label(self, text=f"Dữ liệu Claude: {state.paths.claude_home}", bootstyle="secondary"
                ).pack(anchor="w", pady=(10, 0))
        tb.Label(self, text=f"Nhật ký thao tác: {state.paths.oplog_file}", bootstyle="secondary"
                ).pack(anchor="w")

    def rescan(self) -> None:
        pass  # nothing to reload from disk; settings only change through Save

    def _field(self, label: str, var: tk.StringVar) -> None:
        row = tb.Frame(self)
        row.pack(fill="x", pady=3)
        tb.Label(row, text=label, width=40).pack(side="left")
        tb.Entry(row, textvariable=var, width=20).pack(side="left")

    def _field_with_browse(self, label: str, var: tk.StringVar) -> None:
        row = tb.Frame(self)
        row.pack(fill="x", pady=3)
        tb.Label(row, text=label, width=40).pack(side="left")
        tb.Entry(row, textvariable=var, width=40).pack(side="left", padx=(0, 4))
        tb.Button(row, text="Chọn…", command=lambda: self._browse(var), bootstyle="secondary"
                 ).pack(side="left")

    def _browse(self, var: tk.StringVar) -> None:
        chosen = filedialog.askdirectory(parent=self._root, initialdir=var.get() or None)
        if chosen:
            var.set(chosen)

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
        self._set_status("Đã lưu.", "success")

    def _set_status(self, text: str, style: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(bootstyle=style)
