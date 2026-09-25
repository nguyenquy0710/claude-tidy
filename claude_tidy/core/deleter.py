"""The single deletion pipeline shared by every delete mode.

single / multi / all / orphan-index / cache all go through ``execute`` so they
share one set of safety guarantees: location check -> fresh activity check ->
verified backup -> delete exactly what was backed up -> operation log.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from collections.abc import Callable, Collection
from pathlib import Path

from claude_tidy.core import oplog
from claude_tidy.core.activity import ActivityDetector
from claude_tidy.core.backup import BackupError, TargetFiles, create_backup
from claude_tidy.core.models import (
    Activity,
    DeletePlan,
    DeleteResult,
    DeleteTarget,
    Preview,
    Progress,
    TargetKind,
)
from claude_tidy.core.paths import ClaudePaths
from claude_tidy.core.scanner import check_deletable

SKIP_ACTIVE = "session is active"
SKIP_INDEX_LIVE = "process is still running"

ProgressCallback = Callable[[Progress], None]


def preview(
    plan: DeletePlan,
    paths: ClaudePaths,
    detector: ActivityDetector,
    confirmed: Collection[str] = (),
) -> Preview:
    result = Preview()
    for target in plan.targets:
        refusal = _refusal(target, paths)
        if refusal:
            result.skipped.append((target, refusal))
            continue
        if target.kind is TargetKind.SESSION:
            status = detector.status(target.session)
            if status is Activity.ACTIVE:
                # No force option exists by design, not even for "delete all".
                result.skipped.append((target, SKIP_ACTIVE))
                continue
            if status is Activity.MAYBE_ACTIVE and target.id not in confirmed:
                result.needs_confirmation.append(target)
                continue
        elif target.kind is TargetKind.INDEX and not detector.is_orphan(target.index_entry):
            result.skipped.append((target, SKIP_INDEX_LIVE))
            continue
        result.will_delete.append(target)
    return result


def _refusal(target: DeleteTarget, paths: ClaudePaths) -> str | None:
    for p in target.paths:
        reason = check_deletable(p, paths)
        if reason:
            return f"refused {p}: {reason}"
    return None


def execute(
    plan: DeletePlan,
    *,
    paths: ClaudePaths,
    detector: ActivityDetector,
    backup_dir: Path,
    confirmed: Collection[str] = (),
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    clock: Callable[[], float] = time.time,
) -> DeleteResult:
    progress = on_progress or (lambda _p: None)

    # State may have changed since the preview the user saw (a session resumed,
    # a PID got reused), so activity is re-read from disk right before deleting.
    detector.refresh()
    checked = preview(plan, paths, detector, confirmed)
    result = DeleteResult(skipped=list(checked.skipped),
                          needs_confirmation=list(checked.needs_confirmation))

    if checked.will_delete:
        _backup_and_delete(plan, checked.will_delete, backup_dir, result, progress, cancel, clock)

    _log(paths, plan, result, clock)
    return result


def _backup_and_delete(plan, targets, backup_dir, result, progress, cancel, clock) -> None:
    total = len(targets)
    progress(Progress("backup", 0, total))
    try:
        backup = create_backup(
            targets, backup_dir, plan.label, plan.mode.value, clock,
            on_target_done=lambda n: progress(Progress("backup", n, total)),
        )
    except (BackupError, OSError) as exc:
        result.error = f"backup failed, nothing was deleted: {exc}"
        return
    result.backup_path = backup.zip_path
    result.skipped.extend(backup.unreadable)

    to_delete = [t for t in targets if t.id in backup.captured]
    for done, target in enumerate(to_delete):
        if cancel is not None and cancel.is_set():
            # Checked only between targets so a bundle is never left half-deleted.
            result.cancelled = True
            break
        progress(Progress("delete", done, len(to_delete), target.label))
        errors = _delete_captured(backup.captured[target.id])
        result.failed_files.extend(errors)
        result.deleted.append(target)
    else:
        progress(Progress("delete", len(to_delete), len(to_delete)))


def _delete_captured(captured: TargetFiles) -> list[tuple[Path, str]]:
    # Only what the backup captured is removed; files that appeared after the
    # backup keep their directory alive instead of being lost unbacked-up.
    errors: list[tuple[Path, str]] = []
    for f in captured.files:
        _remove(f, os.unlink, errors)
    for link in captured.links:
        # Remove the link itself, never what it points to.
        _remove(link, _unlink_link, errors)
    for d in sorted(captured.dirs, key=lambda p: len(p.parts), reverse=True):
        _remove(d, os.rmdir, errors)
    return errors


def _unlink_link(path: Path) -> None:
    try:
        os.unlink(path)
    except (IsADirectoryError, PermissionError):
        os.rmdir(path)  # directory symlinks/junctions on Windows


def _remove(path: Path, op: Callable[[Path], None], errors: list[tuple[Path, str]]) -> None:
    try:
        op(path)
    except FileNotFoundError:
        pass
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE)
            op(path)
        except OSError as exc:
            errors.append((path, str(exc)))
    except OSError as exc:
        errors.append((path, str(exc)))


def _log(paths: ClaudePaths, plan: DeletePlan, result: DeleteResult, clock) -> None:
    oplog.append_record(paths, {
        "time": clock(),
        "mode": plan.mode.value,
        "label": plan.label,
        "backup": str(result.backup_path) if result.backup_path else None,
        "deleted": [
            {"kind": t.kind.value, "id": t.id, "size": t.size_bytes} for t in result.deleted
        ],
        "skipped": [{"id": t.id, "reason": r} for t, r in result.skipped],
        "needs_confirmation": [t.id for t in result.needs_confirmation],
        "failed_files": [{"path": str(p), "error": e} for p, e in result.failed_files],
        "cancelled": result.cancelled,
        "error": result.error,
    })
