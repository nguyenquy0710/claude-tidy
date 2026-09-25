"""The one UI entry point for deleting anything: preview -> confirm -> execute -> report.

Every view calls ``run_delete_flow`` so the UI can't grow a second path that
skips the dry-run or the core pipeline's checks.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import flet as ft

from claude_tidy.core.backup import prune_backups
from claude_tidy.core.deleter import execute, preview
from claude_tidy.core.models import DeletePlan, DeleteResult, DeleteTarget, Progress
from claude_tidy.core.usage import human_size
from claude_tidy.ui.state import AppState


def run_delete_flow(
    page: ft.Page,
    state: AppState,
    plan: DeletePlan,
    on_done: Callable[[], None],
    typed_confirmation: str | None = None,
) -> None:
    detector = state.new_detector()
    pv = preview(plan, state.paths, detector)
    confirmed: set[str] = set()

    total_text = ft.Text()
    confirm_btn = ft.FilledButton(content="Xoá", bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE)

    def refresh_summary() -> None:
        size = pv.size_bytes + sum(t.size_bytes for t in pv.needs_confirmation
                                   if t.id in confirmed)
        count = len(pv.will_delete) + len(confirmed)
        total_text.value = f"Sẽ xoá {count} mục — giải phóng {human_size(size)} (có backup zip)"
        typed_ok = typed_confirmation is None or name_field.value == typed_confirmation
        confirm_btn.disabled = count == 0 or not typed_ok
        page.update()

    def toggle(target: DeleteTarget, value: bool) -> None:
        (confirmed.add if value else confirmed.discard)(target.id)
        refresh_summary()

    name_field = ft.TextField(
        label=f'Nhập "{typed_confirmation}" để xác nhận xoá tất cả',
        visible=typed_confirmation is not None,
        on_change=lambda _e: refresh_summary(),
    )

    body: list[ft.Control] = [total_text]
    if pv.will_delete:
        body.append(_section("Sẽ xoá", ft.Colors.GREEN_700))
        body += [_target_line(t) for t in pv.will_delete]
    if pv.needs_confirmation:
        body.append(_section("Có thể đang dùng — tick để vẫn xoá", ft.Colors.AMBER_800))
        body += [
            ft.Checkbox(label=f"{t.label}  ({human_size(t.size_bytes)})", value=False,
                        on_change=lambda e, t=t: toggle(t, bool(e.control.value)))
            for t in pv.needs_confirmation
        ]
    if pv.skipped:
        body.append(_section("Sẽ bỏ qua", ft.Colors.RED_700))
        body += [ft.Text(f"• {t.label} — {reason}", size=12) for t, reason in pv.skipped]
    body.append(name_field)

    def start(_e) -> None:
        page.pop_dialog()
        _run_with_progress(page, state, plan, set(confirmed), on_done)

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"Xem trước: {plan.label}"),
        content=ft.Container(ft.Column(body, scroll=ft.ScrollMode.AUTO, tight=True),
                             width=640, height=420),
        actions=[ft.TextButton(content="Huỷ", on_click=lambda _e: page.pop_dialog()),
                 confirm_btn],
    )
    confirm_btn.on_click = start
    page.show_dialog(dialog)
    refresh_summary()


def _section(title: str, color: str) -> ft.Control:
    return ft.Text(title, weight=ft.FontWeight.BOLD, color=color)


def _target_line(t: DeleteTarget) -> ft.Control:
    return ft.Text(f"• {t.label}  ({human_size(t.size_bytes)})", size=12)


def _run_with_progress(page, state, plan, confirmed, on_done) -> None:
    cancel = threading.Event()
    bar = ft.ProgressBar(value=0, width=480)
    status = ft.Text("Đang chuẩn bị…")
    cancel_btn = ft.TextButton(content="Huỷ (dừng sau mục hiện tại)")

    def on_cancel(_e) -> None:
        cancel.set()
        cancel_btn.disabled = True
        status.value = "Đang dừng sau mục hiện tại…"
        page.update()

    cancel_btn.on_click = on_cancel
    page.show_dialog(ft.AlertDialog(modal=True, title=ft.Text("Đang xoá"),
                                    content=ft.Column([status, bar], tight=True),
                                    actions=[cancel_btn]))

    def on_progress(p: Progress) -> None:
        bar.value = p.done / p.total if p.total else None
        label = "Đang backup" if p.phase == "backup" else "Đang xoá"
        status.value = f"{label} {p.done}/{p.total} {p.current}"
        page.update()

    def work() -> None:
        try:
            result = execute(plan, paths=state.paths, detector=state.new_detector(),
                             backup_dir=state.settings.backup_dir, confirmed=confirmed,
                             on_progress=on_progress, cancel=cancel)
        except Exception as exc:  # surface anything unexpected instead of a frozen dialog
            result = DeleteResult(error=f"Lỗi không mong đợi: {exc}")
        if state.settings.auto_prune_backups:
            prune_backups(state.settings.backup_dir, state.settings.retention_days)
        page.pop_dialog()
        _show_report(page, result)
        on_done()

    page.run_thread(work)


def _show_report(page: ft.Page, result: DeleteResult) -> None:
    lines: list[ft.Control] = []
    if result.error:
        lines.append(ft.Text(result.error, color=ft.Colors.RED_700))
    lines.append(ft.Text(f"Đã xoá {len(result.deleted)} mục, giải phóng "
                         f"{human_size(result.freed_bytes)}."))
    if result.cancelled:
        lines.append(ft.Text("Đã dừng theo yêu cầu — các mục còn lại chưa bị động tới."))
    if result.backup_path:
        lines.append(ft.Text(f"Backup: {result.backup_path}", selectable=True, size=12))
    if result.skipped:
        lines.append(_section("Đã bỏ qua", ft.Colors.RED_700))
        lines += [ft.Text(f"• {t.label} — {r}", size=12) for t, r in result.skipped]
    if result.needs_confirmation:
        lines.append(_section("Không xoá (chưa xác nhận)", ft.Colors.AMBER_800))
        lines += [ft.Text(f"• {t.label}", size=12) for t in result.needs_confirmation]
    if result.failed_files:
        lines.append(_section(f"{len(result.failed_files)} file không xoá được",
                              ft.Colors.RED_700))
        lines += [ft.Text(f"• {p}: {e}", size=11) for p, e in result.failed_files[:50]]
    page.show_dialog(ft.AlertDialog(
        title=ft.Text("Kết quả"),
        content=ft.Container(ft.Column(lines, scroll=ft.ScrollMode.AUTO, tight=True),
                             width=640, height=360),
        actions=[ft.TextButton(content="Đóng", on_click=lambda _e: page.pop_dialog())],
    ))
