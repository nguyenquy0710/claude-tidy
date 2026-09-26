from __future__ import annotations

import threading
import time

import pytest

from claude_tidy.webui import api as api_module
from claude_tidy.webui.api import Api
from claude_tidy.webui.state import AppState
from tests.fixtures import fake_claude as fc


@pytest.fixture
def events():
    log = []
    return log


@pytest.fixture
def app_state(fake):
    return AppState(paths=fake.paths, settings=_settings(fake), probe=fake.probe)


def _settings(fake):
    from claude_tidy.core.settings import Settings

    return Settings.defaults(fake.paths)


@pytest.fixture
def app(app_state, events):
    return Api(app_state, notify=lambda name, payload: events.append((name, payload)))


def _wait_for_job(events, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for name, payload in events:
            if payload.get("job_id") == job_id and name in ("job_done", "job_error"):
                return name, payload
        time.sleep(0.02)
    raise TimeoutError(f"job {job_id} did not finish in time")


def test_list_projects_and_sessions(app, fake):
    projects = app.list_projects()
    alpha = next(p for p in projects if p["worktrees"])
    assert alpha["session_count"] == 7
    detail = app.list_sessions(alpha["id"])
    ids = {s["id"] for s in detail["sessions"]}
    assert fc.S_OLD in ids
    live = next(s for s in detail["sessions"] if s["id"] == fc.S_OLD)
    assert live["message_count"] == 2


def test_scan_cache_and_orphan_index(app):
    cache = app.scan_cache()
    assert len(cache["groups"]) == 4
    orphans = app.list_orphan_index()
    # Matches tests/test_activity.py::test_orphans_are_dead_or_reused_pids:
    # PID_REUSED, PID_DEAD, PID_CORRUPT — PID_LIVE and PID_DENIED are not orphans.
    assert len(orphans) == 3
    reasons = {o["id"]: o["reason"] for o in orphans}
    assert "tái sử dụng" in reasons[f"{fc.PID_REUSED}.json"]
    assert "đã tắt" in reasons[f"{fc.PID_DEAD}.json"]
    assert "hỏng" in reasons[f"{fc.PID_CORRUPT}.json"]


def test_single_delete_happy_path(app, fake, events):
    app.list_projects()
    alpha = next(p for p in app._projects if p.worktrees)
    old_path = fake.paths.claude_home / "projects" / alpha.slug / f"{fc.S_OLD}.jsonl"
    assert old_path.exists()

    pv = app.preview_delete({"mode": "single", "project_id": alpha.slug,
                             "session_ids": [fc.S_OLD]})
    assert pv["will_delete"][0]["id"] == fc.S_OLD
    token = pv["token"]

    resp = app.execute_delete(token, confirmed_ids=[])
    assert "job_id" in resp
    _name, payload = _wait_for_job(events, resp["job_id"])
    assert payload["result"]["deleted"][0]["id"] == fc.S_OLD
    assert not old_path.exists()
    assert payload["result"]["backup_path"]


def test_token_is_one_time_use(app, fake, events):
    app.list_projects()
    alpha = next(p for p in app._projects if p.worktrees)
    pv = app.preview_delete({"mode": "single", "project_id": alpha.slug,
                             "session_ids": [fc.S_RECENT]})
    token = pv["token"]

    resp1 = app.execute_delete(token, confirmed_ids=[])
    assert "job_id" in resp1
    _wait_for_job(events, resp1["job_id"])  # isolate "reused token" from "still busy"

    resp2 = app.execute_delete(token, confirmed_ids=[])
    assert "error" in resp2
    assert "Token" in resp2["error"]


def test_active_session_is_never_deleted_even_if_confirmed(app, fake, events):
    """Mirrors core/test_deleter.py's safety guarantee, end-to-end through the
    API boundary: JS marking an ACTIVE session's id as "confirmed" must not
    delete it — deleter.execute() enforces this regardless of what the API
    layer forwards."""
    app.list_projects()
    alpha = next(p for p in app._projects if p.worktrees)
    live_path = fake.paths.claude_home / "projects" / alpha.slug / f"{fc.S_LIVE}.jsonl"

    pv = app.preview_delete({"mode": "single", "project_id": alpha.slug,
                             "session_ids": [fc.S_LIVE]})
    token = pv["token"]
    assert pv["skipped"][0]["target"]["id"] == fc.S_LIVE

    resp = app.execute_delete(token, confirmed_ids=[fc.S_LIVE])  # malicious/buggy JS
    _name, payload = _wait_for_job(events, resp["job_id"])
    assert payload["result"]["deleted"] == []
    assert payload["result"]["skipped"][0]["target"]["id"] == fc.S_LIVE
    assert live_path.exists()


def test_delete_all_requires_matching_typed_name(app, fake, events):
    app.list_projects()
    alpha = next(p for p in app._projects if p.worktrees)
    old_path = fake.paths.claude_home / "projects" / alpha.slug / f"{fc.S_OLD}.jsonl"

    pv = app.preview_delete({"mode": "all", "project_id": alpha.slug})
    token = pv["token"]
    assert pv["typed_name_required"] == "alpha"

    wrong = app.execute_delete(token, confirmed_ids=[], typed_name="not-alpha")
    assert "error" in wrong
    assert old_path.exists()  # nothing happened

    # Token survives a failed name check — the user can retry.
    ok = app.execute_delete(token, confirmed_ids=[], typed_name="alpha")
    assert "job_id" in ok
    _wait_for_job(events, ok["job_id"])
    assert not old_path.exists()


def test_concurrent_delete_is_rejected(app, fake, events, monkeypatch):
    app.list_projects()
    alpha = next(p for p in app._projects if p.worktrees)

    real_execute = api_module.execute
    started = threading.Event()
    release = threading.Event()

    def slow_execute(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(api_module, "execute", slow_execute)

    pv1 = app.preview_delete({"mode": "single", "project_id": alpha.slug,
                              "session_ids": [fc.S_RECENT]})
    resp1 = app.execute_delete(pv1["token"], confirmed_ids=[])
    assert "job_id" in resp1
    assert started.wait(timeout=5)  # first delete is now mid-flight

    pv2 = app.preview_delete({"mode": "single", "project_id": alpha.slug,
                              "session_ids": [fc.S_DEAD]})
    resp2 = app.execute_delete(pv2["token"], confirmed_ids=[])
    assert "error" in resp2
    assert "khác" in resp2["error"]

    release.set()
    _wait_for_job(events, resp1["job_id"])

    # Now that the first job finished, a fresh delete is accepted again.
    resp3 = app.execute_delete(pv2["token"], confirmed_ids=[])
    assert "job_id" in resp3
    _wait_for_job(events, resp3["job_id"])


def test_rescan_project_picks_up_new_session_without_full_rescan(app, fake):
    projects = app.list_projects()
    alpha = next(p for p in projects if p["worktrees"])
    before_count = alpha["session_count"]

    new_sid = "99999999-9999-9999-9999-999999999999"
    fc._session(fake.paths.claude_home, alpha["id"], new_sid, fc.ALPHA_CWD, "Brand new", age=1)

    detail = app.rescan_project(alpha["id"])
    assert new_sid in {s["id"] for s in detail["sessions"]}
    assert detail["project"]["session_count"] == before_count + 1


def test_rescan_project_unknown_id_returns_error(app, fake):
    app.list_projects()
    assert "error" in app.rescan_project("no-such-project")


def test_open_project_folder_missing_cwd_returns_error(app, fake, monkeypatch):
    app.list_projects()
    alpha = next(p for p in app._projects if p.worktrees)

    def fail_if_called(_path):
        raise AssertionError("must not call os.startfile for a missing cwd")

    monkeypatch.setattr(api_module.os, "startfile", fail_if_called)
    resp = app.open_project_folder(alpha.slug)  # ALPHA_CWD isn't a real dir on this machine
    assert "error" in resp


def test_open_project_folder_opens_existing_cwd(app, fake, monkeypatch):
    app.list_projects()
    alpha = next(p for p in app._projects if p.worktrees)
    alpha.cwd = str(fake.root)  # a directory that really exists, for this test only

    opened = {}
    monkeypatch.setattr(api_module.os, "startfile", lambda p: opened.setdefault("path", p))
    resp = app.open_project_folder(alpha.slug)
    assert resp == {"ok": True}
    assert opened["path"] == str(fake.root)


def test_invalid_mode_and_missing_project_are_rejected(app):
    resp = app.preview_delete({"mode": "bogus"})
    assert "error" in resp

    resp = app.preview_delete({"mode": "single", "project_id": "does-not-exist",
                               "session_ids": ["x"]})
    assert "error" in resp
