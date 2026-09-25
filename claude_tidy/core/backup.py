from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from claude_tidy.core.models import DeleteTarget
from claude_tidy.core.usage import is_link

BACKUP_NAME_RE = re.compile(r"^\d{8}-\d{6}_.+\.zip$")
MANIFEST_NAME = "manifest.json"
SPACE_MARGIN = 1.1
SPACE_RESERVE_BYTES = 50 * 1024 * 1024
CHUNK = 1024 * 1024


class BackupError(Exception):
    pass


@dataclass
class TargetFiles:
    """What was actually captured for a target — the deleter removes exactly this."""

    files: list[Path] = field(default_factory=list)
    links: list[Path] = field(default_factory=list)
    dirs: list[Path] = field(default_factory=list)


@dataclass
class BackupOutcome:
    zip_path: Path
    captured: dict[str, TargetFiles]
    unreadable: list[tuple[DeleteTarget, str]]


def create_backup(
    targets: list[DeleteTarget],
    backup_dir: Path,
    label: str,
    mode: str,
    clock: Callable[[], float] = time.time,
    on_target_done: Callable[[int], None] | None = None,
) -> BackupOutcome:
    backup_dir.mkdir(parents=True, exist_ok=True)
    needed = sum(t.size_bytes for t in targets) * SPACE_MARGIN + SPACE_RESERVE_BYTES
    free = shutil.disk_usage(backup_dir).free
    if free < needed:
        raise BackupError(
            f"not enough free space in {backup_dir}: need {needed:.0f} B, have {free} B"
        )

    zip_path = _unique_zip_path(backup_dir, label, clock())
    partial = zip_path.with_suffix(".zip.partial")
    manifest: dict = {"created_at": clock(), "mode": mode, "label": label, "targets": []}
    captured: dict[str, TargetFiles] = {}
    unreadable: list[tuple[DeleteTarget, str]] = []

    try:
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, target in enumerate(targets):
                entry, files, error = _backup_target(zf, i, target)
                manifest["targets"].append(entry)
                if error:
                    unreadable.append((target, error))
                else:
                    captured[target.id] = files
                if on_target_done:
                    on_target_done(i + 1)
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        _verify(partial, manifest)
        partial.replace(zip_path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return BackupOutcome(zip_path=zip_path, captured=captured, unreadable=unreadable)


def _unique_zip_path(backup_dir: Path, label: str, now: float) -> Path:
    stamp = datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^\w.-]+", "_", label).strip("_")[:60] or "backup"
    path = backup_dir / f"{stamp}_{safe}.zip"
    n = 1
    while path.exists():
        path = backup_dir / f"{stamp}_{safe}_{n}.zip"
        n += 1
    return path


def _arcname(index: int, path: Path) -> str:
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    parts = [p for p in re.split(r"[\\/]+", rest) if p]
    return "/".join([f"t{index:04d}", drive.rstrip(":\\/").replace(":", "") or "root", *parts])


def _backup_target(zf: zipfile.ZipFile, index: int, target: DeleteTarget):
    files = TargetFiles()
    entry = {"id": target.id, "kind": target.kind.value, "label": target.label,
             "roots": [str(p) for p in target.paths], "files": [], "links": [], "dirs": [],
             "status": "ok"}
    try:
        for root in target.paths:
            _collect(root, files)
        for f in files.files:
            arc = _arcname(index, f)
            digest, size = _write_file(zf, f, arc)
            entry["files"].append({"path": str(f), "arcname": arc, "size": size, "sha256": digest})
        for link in files.links:
            entry["links"].append({"path": str(link), "target": _readlink(link)})
        entry["dirs"] = [str(d) for d in files.dirs]
    except OSError as exc:
        # A locked/unreadable file means this target can't be fully restored, so
        # none of it is deleted — never leave a half-deleted bundle behind.
        entry["status"] = "unreadable"
        entry["error"] = str(exc)
        return entry, files, f"cannot back up: {exc}"
    return entry, files, None


def _collect(root: Path, out: TargetFiles) -> None:
    if is_link(root):
        out.links.append(root)
        return
    if not root.exists():
        return
    if root.is_file():
        out.files.append(root)
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_raise):
        base = Path(dirpath)
        out.dirs.append(base)
        for d in list(dirnames):
            if is_link(base / d):
                out.links.append(base / d)
                dirnames.remove(d)
        for name in filenames:
            p = base / name
            (out.links if is_link(p) else out.files).append(p)


def _raise(exc: OSError) -> None:
    raise exc


def _readlink(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def _write_file(zf: zipfile.ZipFile, src: Path, arcname: str) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with src.open("rb") as fin, zf.open(arcname, "w", force_zip64=True) as fout:
        while chunk := fin.read(CHUNK):
            h.update(chunk)
            fout.write(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _verify(zip_path: Path, manifest: dict) -> None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise BackupError(f"corrupt entry in backup: {bad}")
            for target in manifest["targets"]:
                if target["status"] != "ok":
                    continue
                for f in target["files"]:
                    h = hashlib.sha256()
                    with zf.open(f["arcname"]) as fin:
                        while chunk := fin.read(CHUNK):
                            h.update(chunk)
                    if h.hexdigest() != f["sha256"]:
                        raise BackupError(f"checksum mismatch for {f['path']}")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise BackupError(f"backup verification failed: {exc}") from exc


def prune_backups(
    backup_dir: Path, retention_days: int, clock: Callable[[], float] = time.time
) -> list[Path]:
    """Delete this app's own backups older than the retention window.

    Only files matching our naming scheme are considered, so pointing the
    backup dir at a folder with other zips can't cost the user those files.
    """
    if not backup_dir.is_dir():
        return []
    cutoff = clock() - retention_days * 86400
    removed = []
    for f in backup_dir.iterdir():
        if f.is_file() and BACKUP_NAME_RE.match(f.name) and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed.append(f)
            except OSError:
                pass
    return removed
