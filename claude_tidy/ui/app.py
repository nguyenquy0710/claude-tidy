from __future__ import annotations

import contextlib
import ctypes
import sys

import ttkbootstrap as tb

from claude_tidy.ui.dispatch import Dispatcher, pump_forever
from claude_tidy.ui.explorer import ExplorerView
from claude_tidy.ui.other_views import CacheView, IndexView, SettingsView
from claude_tidy.ui.state import AppState


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
    # Applies to every Treeview in the app (project tree, session/cache/index
    # lists, the delete-flow preview) — the ttkbootstrap default is cramped.
    tb.Style().configure("Treeview", rowheight=28)
    dispatcher = Dispatcher()
    state = AppState.load()

    notebook = tb.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    views = [
        ExplorerView(notebook, root, dispatcher, state),
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
