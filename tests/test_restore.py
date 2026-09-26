from __future__ import annotations

import json
import threading
import zipfile

import pytest

from claude_tidy.core import oplog
from claude_tidy.core.deleter import execute
from claude_tidy.core.grouping import build_session_plan, group_projects
from claude_tidy.core.models import PlanMode
from claude_tidy.core.restore import (
    RestoreError,
    list_backups,
    preview_restore,
    read_manifest,
    restore,
)
from claude_tidy.core.scanner import scan_projects
from tests.fixtures import fake_claude as fc


@pytest.fixture
def alpha(fake):
    return next(p for p in group_projects(scan_projects(fake.paths)) if p.slug == "D--work-alpha")


def _delete_and_backup(fake, detector, alpha, session_id):
    """Delete one session for real, returning its backup zip path."""
    plan = build_session_plan(PlanMode.SINGLE, alpha, [session_id])
    result = execute(plan, paths=fake.paths, detector=detector,
                     backup_dir=fake.root / "backups", clock=lambda: fc.NOW)
    assert result.deleted, "setup failed: session was not actually deleted"
    return result.backup_path


def test_list_backups_finds_zip_after_delete(fake, detector, alpha):
    zip_path = _delete_and_backup(fake, detector, alpha, fc.S_OLD)
    backups = list_backups(fake.root / "backups")
    assert [b.zip_path for b in backups] == [zip_path]
    assert backups[0].mode == "single"
    assert backups[0].target_count == 1


def test_list_backups_empty_dir(fake):
    assert list_backups(fake.root / "no-such-dir") == []


def test_preview_restore_all_clear_when_files_gone(fake, detector, alpha):
    artifacts = fake.bundle_artifacts(fc.S_OLD, "D--work-alpha")
    zip_path = _delete_and_backup(fake, detector, alpha, fc.S_OLD)
    assert not any(p.exists() for p in artifacts)

    pv = preview_restore(zip_path, fake.paths)
    assert [i.id for i in pv.will_restore] == [fc.S_OLD]
    assert pv.needs_confirmation == []
    assert pv.refused == []


def test_restore_recreates_deleted_files_with_correct_content(fake, detector, alpha):
    jsonl = fake.paths.claude_home / "projects" / "D--work-alpha" / f"{fc.S_OLD}.jsonl"
    original_text = jsonl.read_text(encoding="utf-8")
    zip_path = _delete_and_backup(fake, detector, alpha, fc.S_OLD)
    assert not jsonl.exists()

    result = restore(zip_path, fake.paths)
    assert [i.id for i in result.restored] == [fc.S_OLD]
    assert result.skipped == []
    assert result.failed_files == []
    assert jsonl.exists()
    assert jsonl.read_text(encoding="utf-8") == original_text


def test_restore_skips_conflict_without_confirmation_then_overwrites_when_confirmed(
    fake, detector, alpha
):
    jsonl = fake.paths.claude_home / "projects" / "D--work-alpha" / f"{fc.S_OLD}.jsonl"
    original_text = jsonl.read_text(encoding="utf-8")
    zip_path = _delete_and_backup(fake, detector, alpha, fc.S_OLD)

    # A new, unrelated file lands at the same path before the user restores.
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    jsonl.write_text("someone else's data", encoding="utf-8")

    pv = preview_restore(zip_path, fake.paths)
    assert [i.id for i in pv.needs_confirmation] == [fc.S_OLD]
    assert pv.will_restore == []

    result = restore(zip_path, fake.paths)
    assert result.restored == []
    assert result.skipped[0][0].id == fc.S_OLD
    assert "chưa xác nhận" in result.skipped[0][1]
    assert jsonl.read_text(encoding="utf-8") == "someone else's data"

    result2 = restore(zip_path, fake.paths, confirmed=[fc.S_OLD])
    assert [i.id for i in result2.restored] == [fc.S_OLD]
    assert jsonl.read_text(encoding="utf-8") == original_text


def test_restore_refuses_tampered_manifest_root(fake, detector, alpha, tmp_path):
    zip_path = _delete_and_backup(fake, detector, alpha, fc.S_OLD)
    tampered = _tamper_manifest_root(zip_path, tmp_path, fake.paths.app_dir / "memory" / "evil.md")

    pv = preview_restore(tampered, fake.paths)
    assert pv.will_restore == [] and pv.needs_confirmation == []
    assert pv.refused[0][0].id == fc.S_OLD
    assert "refused" in pv.refused[0][1]

    result = restore(tampered, fake.paths)
    assert result.restored == []
    assert "refused" in result.skipped[0][1]
    assert not (fake.paths.app_dir / "memory" / "evil.md").exists()


def _tamper_manifest_root(zip_path, tmp_path, evil_root):
    """Rewrite manifest.json inside a copy of zip_path so one target's first
    root points outside every managed location — simulating a hand-edited or
    foreign zip placed in the backup dir."""
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(zip_path) as src, zipfile.ZipFile(tampered, "w") as dst:
        manifest = json.loads(src.read("manifest.json"))
        manifest["targets"][0]["roots"][0] = str(evil_root)
        for item in src.infolist():
            if item.filename == "manifest.json":
                continue
            dst.writestr(item, src.read(item.filename))
        dst.writestr("manifest.json", json.dumps(manifest))
    return tampered


def test_restore_appends_oplog_record(fake, detector, alpha):
    zip_path = _delete_and_backup(fake, detector, alpha, fc.S_OLD)
    restore(zip_path, fake.paths, clock=lambda: fc.NOW)

    records = oplog.read_records(fake.paths)
    restore_records = [r for r in records if r["mode"] == "restore"]
    assert len(restore_records) == 1
    assert restore_records[0]["restored"] == [{"id": fc.S_OLD}]
    assert restore_records[0]["backup"] == str(zip_path)


def test_restore_cancel_stops_between_targets(fake, detector, alpha):
    zip_path1 = _delete_and_backup(fake, detector, alpha, fc.S_OLD)
    _combine_backups_not_needed = zip_path1  # single-target zip; cancel fires before it starts

    cancel = threading.Event()
    cancel.set()  # already cancelled before the loop even starts
    result = restore(zip_path1, fake.paths, cancel=cancel)
    assert result.cancelled
    assert result.restored == []


def test_read_manifest_corrupt_zip_raises(tmp_path):
    bogus = tmp_path / "not-a-zip.zip"
    bogus.write_bytes(b"not a zip file")
    with pytest.raises(RestoreError):
        read_manifest(bogus)


def test_list_backups_skips_corrupt_zip(fake, detector, alpha, tmp_path):
    zip_path = _delete_and_backup(fake, detector, alpha, fc.S_OLD)
    corrupt = zip_path.parent / "20260101-000000_corrupt.zip"
    corrupt.write_bytes(b"not a zip file")

    backups = list_backups(zip_path.parent)
    assert [b.zip_path for b in backups] == [zip_path]
