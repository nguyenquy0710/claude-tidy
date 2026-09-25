"""The one UI entry point for deleting anything: preview -> confirm -> execute -> report.

Every view calls ``run_delete_flow`` so the UI can't grow a second path that
skips the dry-run or the core pipeline's checks.
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable

import ttkbootstrap as tb

from claude_tidy.core.backup import prune_backups
from claude_tidy.core.deleter import execute, preview
from claude_tidy.core.models import DeletePlan, DeleteResult, Progress
from claude_tidy.core.usage import human_size
from claude_tidy.ui.dispatch import Dispatcher, run_in_background
from claude_tidy.ui.state import AppState
from claude_tidy.ui.widgets import CheckTreeview

RISK_COLORS = {"danger": "#dc3545", "warning": "#fd7e14"}


def run_delete_flow(
    root: tk.Misc,
    dispatcher: Dispatcher,
    state: AppState,
    plan: DeletePlan,
    on_done: Callable[[], None],
    typed_confirmation: str | None = None,
) -> None:
    detector = state.new_detector()
    pv = preview(plan, state.paths, detector)
    confirmed: set[str] = set()

    dialog = tb.Toplevel(title=f"Xem trước: {plan.label}", transient=root)
    dialog.grab_set()
    dialog.geometry("640x480")

    total_var = tk.StringVar()
    tb.Label(dialog, textvariable=total_var, wraplength=600).pack(fill="x", padx=10, pady=(10, 4))

    body = tb.Frame(dialog)
    body.pack(fill="both", expand=True, padx=10)

    if pv.will_delete:
        tb.Label(body, text="Sẽ xoá", bootstyle="success").pack(anchor="w")
        for t in pv.will_delete:
            tb.Label(body, text=f"• {t.label}  ({human_size(t.size_bytes)})",
                    font=("", 9)).pack(anchor="w")

    confirm_tree: CheckTreeview | None = None
    if pv.needs_confirmation:
        tb.Label(body, text="Có thể đang dùng — tick để vẫn xoá",
                bootstyle="warning").pack(anchor="w", pady=(8, 2))
        confirm_tree = CheckTreeview(body, columns=("label", "size"),
                                     headings={"label": "Mục", "size": "Dung lượng"},
                                     height=min(6, len(pv.needs_confirmation)))
        confirm_tree.tree.column("#0", width=0, stretch=False)
        confirm_tree.pack(fill="x", pady=(0, 4))
        for t in pv.needs_confirmation:
            confirm_tree.insert_row("", t.id, "", (t.label, human_size(t.size_bytes)))

    if pv.skipped:
        tb.Label(body, text="Sẽ bỏ qua", bootstyle="danger").pack(anchor="w", pady=(8, 2))
        for t, reason in pv.skipped:
            tb.Label(body, text=f"• {t.label} — {reason}", font=("", 9)).pack(anchor="w")

    name_var = tk.StringVar()
    if typed_confirmation is not None:
        tb.Label(dialog, text=f'Nhập "{typed_confirmation}" để xác nhận xoá tất cả'
                ).pack(anchor="w", padx=10, pady=(8, 0))
        tb.Entry(dialog, textvariable=name_var).pack(fill="x", padx=10)

    actions = tb.Frame(dialog)
    actions.pack(fill="x", padx=10, pady=10)
    confirm_btn = tb.Button(actions, text="Xoá", bootstyle="danger")
    tb.Button(actions, text="Huỷ", command=dialog.destroy, bootstyle="secondary"
             ).pack(side="right", padx=(0, 6))
    confirm_btn.pack(side="right")

    def refresh_summary(*_args) -> None:
        confirmed.clear()
        if confirm_tree is not None:
            confirmed.update(confirm_tree.checked_ids())
        size = pv.size_bytes + sum(t.size_bytes for t in pv.needs_confirmation
                                   if t.id in confirmed)
        count = len(pv.will_delete) + len(confirmed)
        total_var.set(f"Sẽ xoá {count} mục — giải phóng {human_size(size)} (có backup zip)")
        typed_ok = typed_confirmation is None or name_var.get() == typed_confirmation
        confirm_btn.configure(state="normal" if count and typed_ok else "disabled")

    if confirm_tree is not None:
        confirm_tree.on_change = refresh_summary
    name_var.trace_add("write", refresh_summary)
    refresh_summary()

    def start() -> None:
        dialog.destroy()
        _run_with_progress(root, dispatcher, state, plan, set(confirmed), on_done)

    confirm_btn.configure(command=start)


def _run_with_progress(root, dispatcher, state, plan, confirmed, on_done) -> None:
    cancel = threading.Event()
    dialog = tb.Toplevel(title="Đang xoá", transient=root)
    dialog.grab_set()
    dialog.geometry("480x140")

    status_var = tk.StringVar(value="Đang chuẩn bị…")
    tb.Label(dialog, textvariable=status_var).pack(padx=10, pady=(14, 6), anchor="w")
    bar = tb.Progressbar(dialog, mode="determinate", maximum=100)
    bar.pack(fill="x", padx=10)

    def on_cancel() -> None:
        cancel.set()
        cancel_btn.configure(state="disabled")
        status_var.set("Đang dừng sau mục hiện tại…")

    cancel_btn = tb.Button(dialog, text="Huỷ (dừng sau mục hiện tại)", command=on_cancel,
                           bootstyle="secondary")
    cancel_btn.pack(pady=10)

    def on_progress(p: Progress) -> None:
        # Called from the worker thread inside execute(); must only touch Tk
        # via the dispatcher, never directly.
        dispatcher.post(lambda: _apply_progress(status_var, bar, p))

    def work() -> DeleteResult:
        try:
            result = execute(plan, paths=state.paths, detector=state.new_detector(),
                             backup_dir=state.settings.backup_dir, confirmed=confirmed,
                             on_progress=on_progress, cancel=cancel)
        except Exception as exc:  # surface instead of leaving the dialog frozen
            result = DeleteResult(error=f"Lỗi không mong đợi: {exc}")
        if state.settings.auto_prune_backups:
            prune_backups(state.settings.backup_dir, state.settings.retention_days)
        return result

    def done(result: DeleteResult) -> None:
        dialog.destroy()
        _show_report(root, result)
        on_done()

    run_in_background(dispatcher, work, on_done=done)


def _apply_progress(status_var: tk.StringVar, bar: tb.Progressbar, p: Progress) -> None:
    bar.configure(value=(p.done / p.total * 100) if p.total else 0)
    label = "Đang backup" if p.phase == "backup" else "Đang xoá"
    status_var.set(f"{label} {p.done}/{p.total} {p.current}")


def _show_report(root: tk.Misc, result: DeleteResult) -> None:
    dialog = tb.Toplevel(title="Kết quả", transient=root)
    dialog.grab_set()
    dialog.geometry("640x420")
    body = tb.Frame(dialog)
    body.pack(fill="both", expand=True, padx=10, pady=10)

    if result.error:
        tb.Label(body, text=result.error, bootstyle="danger", wraplength=600).pack(anchor="w")
    tb.Label(body, text=f"Đã xoá {len(result.deleted)} mục, giải phóng "
                        f"{human_size(result.freed_bytes)}.").pack(anchor="w", pady=(4, 0))
    if result.cancelled:
        tb.Label(body, text="Đã dừng theo yêu cầu — các mục còn lại chưa bị động tới."
                ).pack(anchor="w")
    if result.backup_path:
        entry = tb.Entry(body)
        entry.insert(0, str(result.backup_path))
        entry.configure(state="readonly")
        tb.Label(body, text="Backup:").pack(anchor="w", pady=(6, 0))
        entry.pack(fill="x")
    if result.skipped:
        tb.Label(body, text="Đã bỏ qua", bootstyle="danger").pack(anchor="w", pady=(8, 2))
        for t, r in result.skipped:
            tb.Label(body, text=f"• {t.label} — {r}", font=("", 9)).pack(anchor="w")
    if result.needs_confirmation:
        tb.Label(body, text="Không xoá (chưa xác nhận)", bootstyle="warning"
                ).pack(anchor="w", pady=(8, 2))
        for t in result.needs_confirmation:
            tb.Label(body, text=f"• {t.label}", font=("", 9)).pack(anchor="w")
    if result.failed_files:
        tb.Label(body, text=f"{len(result.failed_files)} file không xoá được",
                bootstyle="danger").pack(anchor="w", pady=(8, 2))
        for p, e in result.failed_files[:50]:
            tb.Label(body, text=f"• {p}: {e}", font=("", 8)).pack(anchor="w")

    tb.Button(dialog, text="Đóng", command=dialog.destroy, bootstyle="primary"
             ).pack(pady=10)
