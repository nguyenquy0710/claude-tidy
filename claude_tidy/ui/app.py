from __future__ import annotations

import flet as ft

from claude_tidy.ui.explorer import ExplorerView
from claude_tidy.ui.other_views import CacheView, IndexView, SettingsView
from claude_tidy.ui.state import AppState


def main(page: ft.Page) -> None:
    page.title = "Claude Tidy"
    page.window.width = 1200
    page.window.height = 800
    page.padding = 0

    state = AppState.load()
    views = [ExplorerView(page, state), CacheView(page, state), IndexView(page, state),
             SettingsView(page, state)]
    body = ft.Container(views[0], expand=True, padding=10)

    def on_nav(e) -> None:
        view = views[e.control.selected_index]
        body.content = view
        page.update()
        if hasattr(view, "rescan") and not isinstance(view, ExplorerView):
            view.rescan()

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        destinations=[
            ft.NavigationRailDestination(icon=ft.Icons.FOLDER_OUTLINED, label="Sessions"),
            ft.NavigationRailDestination(icon=ft.Icons.CLEANING_SERVICES_OUTLINED,
                                         label="Cache/Temp"),
            ft.NavigationRailDestination(icon=ft.Icons.LINK_OFF, label="Index mồ côi"),
            ft.NavigationRailDestination(icon=ft.Icons.SETTINGS_OUTLINED, label="Cài đặt"),
        ],
        on_change=on_nav,
    )
    page.add(ft.Row([rail, ft.VerticalDivider(width=1), body], expand=True))
    views[0].rescan()


def run() -> None:
    ft.run(main)
