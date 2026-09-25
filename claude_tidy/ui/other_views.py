from __future__ import annotations

from datetime import datetime
from pathlib import Path

import flet as ft

from claude_tidy.core.activity import is_claude_desktop_running
from claude_tidy.core.grouping import build_cache_plan, build_index_plan
from claude_tidy.core.models import CacheGroup, IndexEntry
from claude_tidy.core.scanner import scan_cache
from claude_tidy.core.settings import save_settings
from claude_tidy.core.usage import human_size
from claude_tidy.ui.delete_flow import run_delete_flow
from claude_tidy.ui.state import AppState


class CacheView(ft.Column):
    def __init__(self, page: ft.Page, state: AppState) -> None:
        super().__init__(expand=True)
        self._page = page
        self.state = state
        self.groups: list[CacheGroup] = []
        self.checked: set[str] = set()
        self.warning = ft.Container(
            ft.Text("Claude Desktop đang chạy — một số file cache có thể bị khoá và sẽ được "
                    "bỏ qua. Nên tắt Claude Desktop trước khi dọn.", color=ft.Colors.BLACK),
            bgcolor=ft.Colors.AMBER_100, padding=10, border_radius=6, visible=False)
        self.list = ft.ListView(expand=True, spacing=4)
        self.delete_btn = ft.FilledButton(content="Xoá mục đã chọn", disabled=True,
                                          on_click=self._delete)
        self.controls = [
            ft.Row([ft.Text("Cache Claude Desktop & file tạm", size=18,
                            weight=ft.FontWeight.BOLD),
                    ft.IconButton(ft.Icons.REFRESH, on_click=lambda _e: self.rescan())]),
            self.warning, self.delete_btn, ft.Divider(), self.list,
        ]

    def rescan(self) -> None:
        self._page.run_thread(self._worker)

    def _worker(self) -> None:
        self.groups = scan_cache(self.state.paths)
        self.warning.visible = is_claude_desktop_running()
        self.checked.clear()
        self.list.controls = [
            ft.Checkbox(label=f"{g.name} — {human_size(g.size_bytes)}  ({g.root})",
                        on_change=lambda e, n=g.name: self._toggle(n, e.control.value))
            for g in self.groups
        ] or [ft.Text("Không có cache nào để dọn.")]
        self._sync()

    def _toggle(self, name: str, value: bool) -> None:
        (self.checked.add if value else self.checked.discard)(name)
        self._sync()

    def _sync(self) -> None:
        self.delete_btn.disabled = not self.checked
        self._page.update()

    def _delete(self, _e) -> None:
        plan = build_cache_plan([g for g in self.groups if g.name in self.checked])
        run_delete_flow(self._page, self.state, plan, self.rescan)


class IndexView(ft.Column):
    """Orphaned sessions/<pid>.json files — confirmed and deleted one at a time, by design."""

    def __init__(self, page: ft.Page, state: AppState) -> None:
        super().__init__(expand=True)
        self._page = page
        self.state = state
        self.list = ft.ListView(expand=True, spacing=4)
        self.controls = [
            ft.Row([ft.Text("Index session mồ côi", size=18, weight=ft.FontWeight.BOLD),
                    ft.IconButton(ft.Icons.REFRESH, on_click=lambda _e: self.rescan())]),
            ft.Text("File sessions/<pid>.json của process đã tắt hoặc PID đã bị tái sử dụng. "
                    "Mỗi file cần xác nhận riêng.", size=12),
            ft.Divider(), self.list,
        ]

    def rescan(self) -> None:
        self._page.run_thread(self._worker)

    def _worker(self) -> None:
        orphans = self.state.new_detector().orphan_entries()
        self.list.controls = [self._row(e) for e in orphans] or [
            ft.Text("Không có index mồ côi.")]
        self._page.update()

    def _row(self, e: IndexEntry) -> ft.Control:
        updated = (datetime.fromtimestamp(e.updated_at).strftime("%Y-%m-%d %H:%M")
                   if e.updated_at else "?")
        title = e.name or ("(file hỏng)" if e.corrupt else "(không tên)")
        return ft.ListTile(
            title=ft.Text(f"{title} — PID {e.pid}"),
            subtitle=ft.Text(f"{e.cwd or '?'} · cập nhật {updated} · {e.path.name}", size=11),
            trailing=ft.IconButton(
                ft.Icons.DELETE_OUTLINE, tooltip="Xoá file index này",
                on_click=lambda _e, e=e: run_delete_flow(
                    self._page, self.state, build_index_plan(e), self.rescan)),
        )


class SettingsView(ft.Column):
    def __init__(self, page: ft.Page, state: AppState) -> None:
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._page = page
        self.state = state
        s = state.settings
        self.backup_dir = ft.TextField(label="Thư mục backup", value=str(s.backup_dir))
        self.retention = ft.TextField(label="Số ngày giữ backup", value=str(s.retention_days),
                                      width=240)
        self.auto_prune = ft.Switch(label="Tự xoá backup quá hạn", value=s.auto_prune_backups)
        self.maybe_active = ft.TextField(label="Ngưỡng 'có thể đang dùng' (phút)",
                                         value=str(s.maybe_active_minutes), width=240)
        self.recent = ft.TextField(label="Ngưỡng 'mới dùng' cho badge cảnh báo (giờ)",
                                   value=str(s.recent_hours), width=240)
        self.status = ft.Text("")
        self.controls = [
            ft.Text("Cài đặt", size=18, weight=ft.FontWeight.BOLD),
            self.backup_dir, self.retention, self.auto_prune, self.maybe_active, self.recent,
            ft.Row([ft.FilledButton(content="Lưu", on_click=self._save), self.status]),
            ft.Text(f"Dữ liệu Claude: {state.paths.claude_home}", size=11),
            ft.Text(f"Nhật ký thao tác: {state.paths.oplog_file}", size=11),
        ]

    def _save(self, _e) -> None:
        try:
            values = {
                "retention_days": int(self.retention.value),
                "maybe_active_minutes": int(self.maybe_active.value),
                "recent_hours": int(self.recent.value),
            }
        except (TypeError, ValueError):
            self.status.value = "Các ngưỡng phải là số nguyên."
            self.status.color = ft.Colors.RED_700
            self._page.update()
            return
        if min(values.values()) < 0 or not self.backup_dir.value:
            self.status.value = "Giá trị không hợp lệ."
            self.status.color = ft.Colors.RED_700
            self._page.update()
            return
        s = self.state.settings
        s.backup_dir = Path(self.backup_dir.value)
        s.auto_prune_backups = bool(self.auto_prune.value)
        for k, v in values.items():
            setattr(s, k, v)
        save_settings(self.state.paths, s)
        self.status.value = "Đã lưu."
        self.status.color = ft.Colors.GREEN_700
        self._page.update()
