"""Entry point for the pywebview UI. See claude_tidy/webui/CLAUDE.md.

No `tkinter` import anywhere in this package — the WebView2-missing dialog
uses a raw `MessageBoxW` call instead, so `claude_tidy/ui/` can be deleted
without leaving a stray Tk dependency behind.
"""

from __future__ import annotations

import ctypes
import json
import logging
import winreg
from pathlib import Path

import webview

from claude_tidy.webui.api import Api
from claude_tidy.webui.state import AppState

logger = logging.getLogger(__name__)

# Evergreen WebView2 Runtime client GUID — present under one of these keys
# once the runtime (bundled with Windows 10 1803+/11, or the standalone
# Evergreen installer) is registered. Checked before `webview.start()` so a
# missing runtime gets a clear message instead of pywebview silently
# falling back to the MSHTML/IE engine, which cannot render Bootstrap 5.
_WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
_WEBVIEW2_KEY_SUFFIX = rf"Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_CLIENT_GUID}"
_WEBVIEW2_REGISTRY_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE, f"SOFTWARE\\WOW6432Node\\{_WEBVIEW2_KEY_SUFFIX}"),
    (winreg.HKEY_LOCAL_MACHINE, f"SOFTWARE\\{_WEBVIEW2_KEY_SUFFIX}"),
    (winreg.HKEY_CURRENT_USER, f"SOFTWARE\\{_WEBVIEW2_KEY_SUFFIX}"),
)
_WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"


def _webview2_installed() -> bool:
    for hive, subkey in _WEBVIEW2_REGISTRY_KEYS:
        try:
            with winreg.OpenKey(hive, subkey):
                return True
        except FileNotFoundError:
            continue
    return False


def _show_webview2_missing_dialog() -> None:
    message = (
        "claude-tidy cần Microsoft Edge WebView2 Runtime để chạy giao diện, "
        "nhưng máy này chưa cài.\n\n"
        f"Tải tại: {_WEBVIEW2_DOWNLOAD_URL}"
    )
    MB_ICONERROR = 0x10
    ctypes.windll.user32.MessageBoxW(None, message, "claude-tidy", MB_ICONERROR)


def run() -> None:
    if not _webview2_installed():
        logger.error("WebView2 Runtime not found; see %s", _WEBVIEW2_DOWNLOAD_URL)
        _show_webview2_missing_dialog()
        return

    state = AppState.load()

    def notify(event_name: str, payload: dict) -> None:
        window.evaluate_js(f"onJobEvent({json.dumps(event_name)}, {json.dumps(payload)})")

    api = Api(state, notify=notify)
    index_html = Path(__file__).parent / "static" / "index.html"
    window = webview.create_window(
        "claude-tidy", str(index_html), js_api=api, width=1280, height=800, min_size=(960, 600),
    )
    webview.start(gui="edgechromium")
