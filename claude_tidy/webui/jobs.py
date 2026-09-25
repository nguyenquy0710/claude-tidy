"""Runs long operations (scan, delete) off the pywebview UI thread and pushes
progress back to JS by event name + JSON-safe payload.

Decoupled from `webview.evaluate_js` on purpose — `JobRunner` takes a plain
`notify(event_name, payload)` callable. `api.py` wires that to
`window.evaluate_js(f"onJobEvent({json.dumps(payload)})")`; tests wire it to
a list.append, so this whole module (and everything built on it) is
testable without ever opening a webview window.
"""

from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from typing import Any

NotifyFn = Callable[[str, dict], None]
WorkFn = Callable[[Callable[[dict], None], threading.Event], Any]


class JobRunner:
    def __init__(self, notify: NotifyFn) -> None:
        self._notify = notify
        self._cancels: dict[str, threading.Event] = {}

    def start(self, work: WorkFn) -> str:
        """Run `work(on_progress, cancel_event)` in a background thread.

        `work` must return a JSON-safe dict (already run through `dto.py`) —
        that's pushed as a "job_done" event. Any exception becomes a
        "job_error" event instead of crashing the thread silently.
        """
        job_id = secrets.token_urlsafe(8)
        cancel = threading.Event()
        self._cancels[job_id] = cancel

        def on_progress(payload: dict) -> None:
            self._notify("job_progress", {"job_id": job_id, **payload})

        def run() -> None:
            try:
                result = work(on_progress, cancel)
                self._notify("job_done", {"job_id": job_id, "result": result})
            except Exception as exc:  # surfaced to the UI, never a silent thread death
                self._notify("job_error", {"job_id": job_id, "error": str(exc)})
            finally:
                self._cancels.pop(job_id, None)

        threading.Thread(target=run, daemon=True).start()
        return job_id

    def cancel(self, job_id: str) -> bool:
        cancel = self._cancels.get(job_id)
        if cancel is None:
            return False
        cancel.set()
        return True
