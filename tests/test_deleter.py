from __future__ import annotations

import json
import threading
import zipfile
from collections import namedtuple

import pytest

from claude_tidy.core import backup as backup_mod
from claude_tidy.core import deleter, oplog
from claude_tidy.core.backup import MANIFEST_NAME, prune_backups
from claude_tidy.core.deleter import SKIP_ACTIVE, SKIP_INDEX_LIVE, execute, preview
from claude_tidy.core.grouping import (
    build_cache_plan,
    build_index_plan,
    build_session_plan,
    group_projects,
)
from claude_tidy.core.models import PlanMode
from claude_tidy.core.scanner import scan_cache, scan_projects
from tests.fixtures import fake_claude as fc


@pytest.fixture
def alpha(fake):
    return next(p for p in group_projects(scan_projects(fake.paths)) if p.slug == "D--work-alpha")


def _run(fake, detector, plan, **kw):
    return execute(plan, paths=fake.paths, detector=detector,
                   backup_dir=fake.root / "backups", clock=lambda: fc.NOW, **kw)


def _exists(paths):
    return [p for p in paths if p.exists()]


def test_single_delete_leaves_no_orphans_and_backs_up(fake, detector, alpha):
    artifacts = fake.bundle_artifacts(fc.S_OLD, "D--work-alpha")
    result = _run(fake, detector, build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD]))

    assert [t.id for t in result.deleted] == [fc.S_OLD]
    assert _exists(artifacts) == []
    assert result.failed_files == []
    with zipfile.ZipFile(result.backup_path) as zf:
        manifest = json.loads(zf.read(MANIFEST_NAME))
        (target,) = manifest["targets"]
        assert target["id"] == fc.S_OLD and target["status"] == "ok"
        backed_up = {f["path"] for f in target["files"]}
        assert str(artifacts[0]) in backed_up  # the .jsonl
        assert any("file-history" in p for p in backed_up)
        for f in target["files"]:
            assert len(f["sha256"]) == 64
            zf.read(f["arcname"])


def test_delete_all_keeps_protected_active_and_unconfirmed(fake, detector, alpha):
    result = _run(fake, detector, build_session_plan(PlanMode.ALL, alpha))

    deleted = {t.id for t in result.deleted}
    assert deleted == {fc.S_OLD, fc.S_RECENT, fc.S_REUSED, fc.S_DEAD}
    assert {t.id: r for t, r in result.skipped} == {fc.S_LIVE: SKIP_ACTIVE}
    assert {t.id for t in result.needs_confirmation} == {fc.S_FRESH, fc.S_DENIED}

    for p in fake.protected:
        assert p.exists(), f"protected file was deleted: {p}"
    for sid in (fc.S_LIVE, fc.S_FRESH, fc.S_DENIED):
        assert all(p.exists() for p in fake.bundle_artifacts(sid, "D--work-alpha"))
    # worktree sessions are not included unless asked for
    assert all(p.exists() for p in fake.bundle_artifacts(
        fc.S_WORKTREE, "D--work-alpha--claude-worktrees-feat-x"))
    assert (fake.paths.projects_dir / "D--work-alpha" / "memory" / "MEMORY.md").exists()


def test_confirmed_maybe_active_is_deleted_but_active_never(fake, detector, alpha):
    plan = build_session_plan(PlanMode.MULTI, alpha, [fc.S_FRESH, fc.S_LIVE])
    result = _run(fake, detector, plan, confirmed={fc.S_FRESH, fc.S_LIVE})
    assert [t.id for t in result.deleted] == [fc.S_FRESH]
    assert [t.id for t, _ in result.skipped] == [fc.S_LIVE]


def test_activity_is_rechecked_at_execute_time(fake, detector, alpha):
    plan = build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD])
    assert [t.id for t in preview(plan, fake.paths, detector).will_delete] == [fc.S_OLD]

    # The session gets resumed between preview and clicking "Delete".
    fc._index(fake.paths.claude_home, 4300, fc.S_OLD, fc.ALPHA_CWD, fc.NOW - 5)
    fake.probe.table[4300] = fc.NOW - 5

    result = _run(fake, detector, plan)
    assert result.deleted == []
    assert [r for _, r in result.skipped] == [SKIP_ACTIVE]
    assert all(p.exists() for p in fake.bundle_artifacts(fc.S_OLD, "D--work-alpha"))


def test_backup_failure_deletes_nothing(fake, detector, alpha, monkeypatch):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(backup_mod.shutil, "disk_usage", lambda _p: Usage(1, 1, 0))
    result = _run(fake, detector, build_session_plan(PlanMode.ALL, alpha))
    assert result.deleted == []
    assert "backup failed" in result.error
    assert all(p.exists() for p in fake.bundle_artifacts(fc.S_OLD, "D--work-alpha"))
    assert list((fake.root / "backups").glob("*.partial")) == []


def test_verification_failure_deletes_nothing(fake, detector, alpha, monkeypatch):
    def broken_verify(_zip, _manifest):
        raise backup_mod.BackupError("checksum mismatch")

    monkeypatch.setattr(backup_mod, "_verify", broken_verify)
    result = _run(fake, detector, build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD]))
    assert result.deleted == [] and result.backup_path is None
    assert all(p.exists() for p in fake.bundle_artifacts(fc.S_OLD, "D--work-alpha"))


def test_locked_file_skips_whole_bundle(fake, detector, alpha, monkeypatch):
    real_write = backup_mod._write_file
    locked = fake.paths.claude_home / "file-history" / fc.S_OLD / "abc@v1"

    def write(zf, src, arc):
        if src == locked:
            raise PermissionError("file is locked by another process")
        return real_write(zf, src, arc)

    monkeypatch.setattr(backup_mod, "_write_file", write)
    plan = build_session_plan(PlanMode.MULTI, alpha, [fc.S_OLD, fc.S_RECENT])
    result = _run(fake, detector, plan)

    assert [t.id for t in result.deleted] == [fc.S_RECENT]
    assert [t.id for t, _ in result.skipped] == [fc.S_OLD]
    assert all(p.exists() for p in fake.bundle_artifacts(fc.S_OLD, "D--work-alpha"))


def test_file_created_after_backup_is_not_lost(fake, detector, alpha):
    late = fake.paths.claude_home / "file-history" / fc.S_OLD / "late@v2"

    def on_progress(p):
        if p.phase == "delete" and p.done == 0:
            late.write_text("written after backup")

    plan = build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD])
    result = _run(fake, detector, plan, on_progress=on_progress)
    assert late.exists()
    assert not (fake.paths.projects_dir / "D--work-alpha" / f"{fc.S_OLD}.jsonl").exists()
    assert any(p == late.parent for p, _ in result.failed_files)  # dir not empty


def test_cancel_stops_between_bundles(fake, detector, alpha):
    cancel = threading.Event()

    def on_progress(p):
        if p.phase == "delete" and p.done == 1:
            cancel.set()  # user clicks Cancel while the 2nd bundle is being deleted

    plan = build_session_plan(PlanMode.MULTI, alpha, [fc.S_OLD, fc.S_RECENT, fc.S_DEAD])
    result = _run(fake, detector, plan, on_progress=on_progress, cancel=cancel)
    assert result.cancelled
    assert [t.id for t in result.deleted] == [fc.S_OLD, fc.S_RECENT]
    assert _exists(fake.bundle_artifacts(fc.S_RECENT, "D--work-alpha")) == []
    assert all(p.exists() for p in fake.bundle_artifacts(fc.S_DEAD, "D--work-alpha"))


def test_link_inside_bundle_is_removed_without_touching_target(fake, detector, alpha):
    link = fake.paths.claude_home / "session-env" / fc.S_OLD / "linked"
    if not fc.make_junction(link, fake.outside_dir):
        pytest.skip("cannot create links on this system")
    result = _run(fake, detector, build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD]))
    assert [t.id for t in result.deleted] == [fc.S_OLD]
    assert not link.exists()
    assert (fake.outside_dir / "precious.bin").read_text() == "do not delete"


def test_protected_path_injected_into_plan_is_refused(fake, detector, alpha):
    plan = build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD])
    plan.targets[0].paths.append(fake.paths.projects_dir / "D--work-alpha" / "memory")
    result = _run(fake, detector, plan)
    assert result.deleted == []
    assert "protected" in result.skipped[0][1]
    assert all(p.exists() for p in fake.bundle_artifacts(fc.S_OLD, "D--work-alpha"))


def test_orphan_index_deleted_with_key_live_one_refused(fake, detector):
    entries = {e.pid: e for e in detector.index_entries()}
    dead = entries[fc.PID_DEAD]
    result = _run(fake, detector, build_index_plan(dead))
    assert len(result.deleted) == 1
    assert not dead.path.exists() and not any(k.exists() for k in dead.key_files)

    live = entries[fc.PID_LIVE]
    result = _run(fake, detector, build_index_plan(live))
    assert result.deleted == [] and result.skipped[0][1] == SKIP_INDEX_LIVE
    assert live.path.exists()


def test_cache_delete_keeps_non_cache_and_link_target(fake, detector):
    result = _run(fake, detector, build_cache_plan(scan_cache(fake.paths)))
    assert len(result.deleted) == 4
    desktop = fake.paths.desktop_dirs[0]
    assert not (desktop / "GPUCache").exists()
    assert (desktop / "Local Storage" / "leveldb" / "000.log").exists()
    assert (fake.outside_dir / "precious.bin").exists()
    assert list(fake.paths.temp_dir.iterdir()) == []


def test_every_execute_writes_one_oplog_line(fake, detector, alpha):
    _run(fake, detector, build_session_plan(PlanMode.SINGLE, alpha, [fc.S_OLD]))
    _run(fake, detector, build_session_plan(PlanMode.SINGLE, alpha, [fc.S_LIVE]))
    records = oplog.read_records(fake.paths)
    assert len(records) == 2
    assert records[0]["deleted"][0]["id"] == fc.S_OLD and records[0]["backup"]
    assert records[1]["deleted"] == [] and records[1]["backup"] is None


def test_prune_only_touches_own_old_backups(tmp_path):
    import os

    old = tmp_path / "20260101-000000_alpha.zip"
    new = tmp_path / "20260920-000000_alpha.zip"
    foreign = tmp_path / "photos.zip"
    for f in (old, new, foreign):
        f.write_text("z")
    os.utime(old, (fc.NOW - 30 * fc.DAY,) * 2)
    os.utime(foreign, (fc.NOW - 30 * fc.DAY,) * 2)
    assert prune_backups(tmp_path, 14, clock=lambda: fc.NOW) == [old]
    assert new.exists() and foreign.exists()


def test_deleter_is_the_only_module_that_removes_files():
    # Guard against a second deletion path creeping into core/ or ui/.
    import pathlib

    root = pathlib.Path(deleter.__file__).parent.parent
    offenders = []
    for py in root.rglob("*.py"):
        if py.name in ("deleter.py", "backup.py"):
            continue
        text = py.read_text(encoding="utf-8")
        for needle in ("os.unlink", "os.remove", "rmtree", ".unlink(", "os.rmdir", ".rmdir("):
            if needle in text:
                offenders.append((py.name, needle))
    assert offenders == []
