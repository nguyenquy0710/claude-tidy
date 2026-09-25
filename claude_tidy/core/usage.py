from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Iterable
from pathlib import Path


def is_link(path: Path) -> bool:
    """True for symlinks *and* Windows junctions/reparse points.

    ``Path.is_symlink()`` misses junctions on Python 3.11, and ``~/.claude``
    commonly contains linked dirs (``agents``, ``skills``, ``vm_bundles``) whose
    targets live outside anything this app is allowed to touch.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def path_size(path: Path) -> int:
    if is_link(path):
        return 0
    try:
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if not is_link(Path(dirpath, d))]
        for name in filenames:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, name)).st_size
    return total


def total_size(paths: Iterable[Path]) -> int:
    return sum(path_size(p) for p in paths)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
