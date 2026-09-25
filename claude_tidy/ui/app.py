from __future__ import annotations

import contextlib
import ctypes
import sys
import tkinter as tk

import ttkbootstrap as tb

from claude_tidy.ui.dispatch import Dispatcher, pump_forever
from claude_tidy.ui.explorer import ExplorerView
from claude_tidy.ui.other_views import CacheView, IndexView, SettingsView
from claude_tidy.ui.state import AppState
from claude_tidy.ui.theme import apply_global_style
from claude_tidy.ui.theme import font_family as ff

APP_VERSION = "v0.1 · MVP"


def _enable_dpi_awareness() -> None:
    # Without this, ttkbootstrap/Tk renders blurry text on any Windows display
    # scaled above 100% — a real default on most laptops.
    if sys.platform != "win32":
        return
    # older Windows without shcore falls back to blurry-but-working
    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shcore.SetProcessDpiAwareness(1)


def build_app() -> tb.Window:
    _enable_dpi_awareness()
    root = tb.Window(themename="cosmo", title="Claude Tidy", size=(1200, 800))
    root.minsize(900, 600)
    # Must run before any other widget is created — Style.colors.set() only
    # retints bootstyle-generated styles made *after* the call.
    apply_global_style(root)
    # Applies to every Treeview in the app (project tree, session/cache/index
    # lists, the delete-flow preview) — the ttkbootstrap default is cramped.
    tb.Style().configure("Treeview", rowheight=28)
    dispatcher = Dispatcher()
    state = AppState.load()

    # App bar (icon + name + version badge). The reference design has a fully
    # custom title bar with its own minimize/maximize/close — replicating
    # that means dropping the native one (`overrideredirect`) and hand-
    # rolling window drag/resize/minimize, which is a real regression risk
    # for a utility that's meant to behave like a normal Windows app. This
    # app bar gets the same identity strip under the native, working title
    # bar instead — see claude_tidy/ui/CLAUDE.md.
    appbar = tb.Frame(root)
    appbar.pack(fill="x")
    tb.Label(appbar, text="📌 claude-tidy", font=(ff(), 11, "bold")
             ).pack(side="left", padx=(10, 6), pady=6)
    tb.Label(appbar, text=APP_VERSION, bootstyle="secondary").pack(side="left")
    tb.Separator(root).pack(fill="x")

    notebook = tb.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=(6, 0))

    status_left = tk.StringVar(value="Đang quét…")
    status_right = tk.StringVar(
        value=f"Backup → {state.settings.backup_dir} · giữ {state.settings.retention_days} ngày"
    )
    tb.Separator(root).pack(fill="x")
    statusbar = tb.Frame(root)
    statusbar.pack(fill="x")
    tb.Label(statusbar, textvariable=status_left, bootstyle="secondary", font=(ff(), 9)
             ).pack(side="left", padx=10, pady=4)
    tb.Label(statusbar, textvariable=status_right, bootstyle="secondary", font=(ff(), 9)
             ).pack(side="right", padx=10, pady=4)

    views = [
        ExplorerView(notebook, root, dispatcher, state, status_var=status_left),
        CacheView(notebook, root, dispatcher, state),
        IndexView(notebook, root, dispatcher, state),
        SettingsView(notebook, root, dispatcher, state),
    ]
    labels = ["Sessions", "Cache/Temp", "Index mồ côi", "Cài đặt"]
    for view, label in zip(views, labels, strict=True):
        notebook.add(view, text=label)

    scanned = {0}
    views[0].rescan()

    def on_tab_changed(_event) -> None:
        index = notebook.index(notebook.select())
        if index not in scanned:
            scanned.add(index)
            views[index].rescan()

    notebook.bind("<<NotebookTabChanged>>", on_tab_changed)
    pump_forever(root, dispatcher)
    return root


def run() -> None:
    build_app().mainloop()
