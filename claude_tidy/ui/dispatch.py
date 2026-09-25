"""Marshals work from background threads onto the Tk main thread.

Tkinter widgets may only be touched from the thread running ``mainloop()``.
The core deletion pipeline calls its progress/completion callbacks from a
worker thread, so every one of those callbacks must go through here before
touching a widget — never call a Tk method directly from `work()`.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class Dispatcher:
    """A thread-safe inbox of callables, drained on the main thread.

    Decoupled from any Tk object on purpose: `drain()` can be unit-tested
    without a display (see tests/test_ui_dispatch.py). `pump_forever()` below
    is the only piece that actually touches `root`.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()

    def post(self, fn: Callable[[], None]) -> None:
        self._queue.put(fn)

    def drain(self) -> int:
        """Run every callable queued so far; return how many ran.

        One callback raising must not stop the rest — a bad progress update
        shouldn't also kill the completion callback queued behind it.
        """
        ran = 0
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                return ran
            try:
                fn()
            finally:
                ran += 1


def pump_forever(root, dispatcher: Dispatcher, interval_ms: int = 50) -> None:
    """Drain `dispatcher` on a recurring `root.after` tick."""
    dispatcher.drain()
    root.after(interval_ms, pump_forever, root, dispatcher, interval_ms)


def run_in_background(
    dispatcher: Dispatcher,
    work: Callable[[], T],
    on_done: Callable[[T], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> threading.Thread:
    """Run `work()` off the main thread; deliver the result via `dispatcher`."""

    def runner() -> None:
        try:
            result = work()
        except Exception as exc:  # surfaced to the UI instead of dying silently
            # `exc` is unbound once the `except` block ends, so it must be
            # captured into an ordinary local before the deferred lambda runs.
            error = exc
            if on_error is not None:
                dispatcher.post(lambda: on_error(error))
            return
        if on_done is not None:
            dispatcher.post(lambda: on_done(result))

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread
