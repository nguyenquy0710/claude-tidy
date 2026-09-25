from __future__ import annotations

import time

import pytest

from claude_tidy.ui.dispatch import Dispatcher, run_in_background


def test_drain_runs_queued_callables_in_order():
    d = Dispatcher()
    calls = []
    d.post(lambda: calls.append(1))
    d.post(lambda: calls.append(2))
    assert d.drain() == 2
    assert calls == [1, 2]
    assert d.drain() == 0  # queue is empty now


def test_drain_runs_every_callback_even_if_one_raises():
    d = Dispatcher()
    calls = []
    d.post(lambda: (_ for _ in ()).throw(ValueError("boom")))
    d.post(lambda: calls.append("still ran"))
    with pytest.raises(ValueError, match="boom"):
        d.drain()
    # first callback's exception surfaces, but it was still counted and the
    # queue moves on — nothing is left stuck behind a bad callback forever
    assert d.drain() == 1
    assert calls == ["still ran"]


def test_run_in_background_delivers_result_only_through_dispatcher():
    d = Dispatcher()
    results = []

    thread = run_in_background(d, work=lambda: 42, on_done=lambda r: results.append(r))
    thread.join(timeout=2)
    # The whole point of routing through the dispatcher: on_done must not run
    # on the worker thread — only draining on the main thread delivers it.
    assert results == []
    assert d.drain() == 1
    assert results == [42]


def test_run_in_background_posts_result_only_after_drain():
    d = Dispatcher()
    calls = []
    thread = run_in_background(d, work=lambda: (time.sleep(0.05), "ok")[1],
                               on_done=lambda r: calls.append(r))
    # Work is still running / just posted; drain() before join may see nothing yet.
    thread.join(timeout=2)
    assert calls == []  # posted to the queue, but nothing has drained it
    assert d.drain() == 1
    assert calls == ["ok"]


def test_run_in_background_reports_errors_via_on_error():
    d = Dispatcher()
    errors = []

    def boom():
        raise RuntimeError("nope")

    thread = run_in_background(d, work=boom, on_error=lambda e: errors.append(str(e)))
    thread.join(timeout=2)
    d.drain()
    assert errors == ["nope"]


def test_run_in_background_without_on_error_does_not_crash_the_thread():
    d = Dispatcher()
    thread = run_in_background(d, work=lambda: 1 / 0)
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert d.drain() == 0  # nothing was posted; nothing to marshal
