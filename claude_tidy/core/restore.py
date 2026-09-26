"""Restore from a backup zip created by ``core.backup``.

Mirrors the delete pipeline's shape: a dry-run ``preview_restore()`` splits
targets into will-restore / needs-confirmation (destination file already
exists) / refused, then ``restore()`` re-checks the same things right before
writing. A backup zip is data this app wrote itself, but a tampered or
foreign zip placed in the backup dir could still claim any destination path
in its manifest — every target's original roots are re-validated against
``scanner.check_deletable()`` (the same allowlist the delete pipeline uses)
before any file from it is written back, so restore can't be used to plant
files outside the managed session/index/cache locations.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
import zipfile
from collections.abc import Callable, Collection
from pathlib import Path

from claude_tidy.core import oplog
from claude_tidy.core.backup import BACKUP_NAME_RE, CHUNK, MANIFEST_NAME
from claude_tidy.core.models import (
    BackupFile,
    Progress,
    RestoreItem,
    RestorePreview,
    RestoreResult,
)
from claude_tidy.core.paths import ClaudePaths
from claude_tidy.core.scanner import check_deletable

ProgressCallback = Callable[[Progress], None]


class RestoreError(Exception):
    pass


def read_manifest(zip_path: Path) -> dict:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return json.loads(zf.read(MANIFEST_NAME))
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise RestoreError(f"cannot read manifest from {zip_path}: {exc}") from exc


def list_backups(backup_dir: Path) -> list[BackupFile]:
    if not backup_dir.is_dir():
        return []
    out = []
    for f in sorted(backup_dir.iterdir(), reverse=True):
        if not (f.is_file() and BACKUP_NAME_RE.match(f.name)):
            continue
        try:
            out.append(_backup_file(f))
        except RestoreError:
            continue  # unreadable/corrupt zip — not offered for restore
    return out


def _backup_file(zip_path: Path) -> BackupFile:
    manifest = read_manifest(zip_path)
    return BackupFile(
        zip_path=zip_path,
        created_at=manifest.get("created_at", 0.0),
        mode=manifest.get("mode", "?"),
        label=manifest.get("label", zip_path.stem),
        target_count=len(manifest.get("targets", [])),
        size_bytes=zip_path.stat().st_size,
    )


def _item(target: dict) -> RestoreItem:
    files = target.get("files", [])
    return RestoreItem(
        id=target["id"], label=target["label"],
        file_count=len(files), size_bytes=sum(f["size"] for f in files),
    )


def _refuse_target_roots(target: dict, paths: ClaudePaths) -> str | None:
    for root in target.get("roots", []):
        reason = check_deletable(Path(root), paths)
        if reason:
            return f"refused {root}: {reason}"
    return None


def preview_restore(zip_path: Path, paths: ClaudePaths) -> RestorePreview:
    manifest = read_manifest(zip_path)
    pv = RestorePreview(backup=_backup_file(zip_path))
    for target in manifest.get("targets", []):
        item = _item(target)
        if target.get("status") != "ok":
            pv.refused.append((item, "backup không đọc được target này lúc tạo (unreadable)"))
            continue
        refusal = _refuse_target_roots(target, paths)
        if refusal:
            pv.refused.append((item, refusal))
            continue
        conflicts = [f for f in target["files"] if Path(f["path"]).exists()]
        if conflicts:
            pv.needs_confirmation.append(item)
        else:
            pv.will_restore.append(item)
    return pv


def restore(
    zip_path: Path,
    paths: ClaudePaths,
    *,
    confirmed: Collection[str] = (),
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    clock: Callable[[], float] = time.time,
) -> RestoreResult:
    manifest = read_manifest(zip_path)
    progress = on_progress or (lambda _p: None)
    result = RestoreResult()
    targets = manifest.get("targets", [])
    total = len(targets)

    with zipfile.ZipFile(zip_path) as zf:
        for done, target in enumerate(targets):
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                break
            item = _item(target)
            progress(Progress("restore", done, total, target["label"]))

            if target.get("status") != "ok":
                result.skipped.append(
                    (item, "backup không đọc được target này lúc tạo (unreadable)"))
                continue
            refusal = _refuse_target_roots(target, paths)
            if refusal:
                result.skipped.append((item, refusal))
                continue
            conflicts = [f for f in target["files"] if Path(f["path"]).exists()]
            if conflicts and target["id"] not in confirmed:
                result.skipped.append(
                    (item, f"{len(conflicts)} file đích đã tồn tại, chưa xác nhận ghi đè"))
                continue
            try:
                _restore_target(zf, target)
                result.restored.append(item)
            except (OSError, RestoreError) as exc:
                result.failed_files.append((Path(target["label"]), str(exc)))
        else:
            progress(Progress("restore", total, total))

    oplog.append_record(paths, {
        "time": clock(),
        "mode": "restore",
        "label": manifest.get("label"),
        "backup": str(zip_path),
        "restored": [{"id": i.id} for i in result.restored],
        "skipped": [{"id": i.id, "reason": r} for i, r in result.skipped],
        "failed_files": [{"path": str(p), "error": e} for p, e in result.failed_files],
        "cancelled": result.cancelled,
    })
    return result


def _restore_target(zf: zipfile.ZipFile, target: dict) -> None:
    for d in target.get("dirs", []):
        Path(d).mkdir(parents=True, exist_ok=True)
    for f in target.get("files", []):
        dest = Path(f["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling temp name first — a checksum mismatch (corrupt
        # backup entry) must not leave a half-written file at the real path.
        tmp = dest.with_name(dest.name + ".restoring")
        h = hashlib.sha256()
        with zf.open(f["arcname"]) as src, tmp.open("wb") as out:
            while chunk := src.read(CHUNK):
                h.update(chunk)
                out.write(chunk)
        if h.hexdigest() != f["sha256"]:
            tmp.unlink(missing_ok=True)
            raise RestoreError(f"checksum mismatch restoring {dest}")
        tmp.replace(dest)
    for link in target.get("links", []):
        dest = Path(link["path"])
        tgt = link.get("target")
        if dest.exists() or not tgt:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(tgt, dest)
        except OSError:
            # best-effort; a missing symlink shouldn't fail the whole target
            with contextlib.suppress(OSError):
                os.symlink(tgt, dest, target_is_directory=True)
