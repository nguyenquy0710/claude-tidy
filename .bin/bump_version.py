"""Bump the project's patch version everywhere it is hardcoded.

Run before a desktop build so every build ships a distinct version:
  python .bin\\bump_version.py

Keeps pyproject.toml, app/core/config.py's Settings.VERSION fallback, and
src/py_restream/config/settings.py's APP_VERSION in sync (they all start
from the same "1.2.6" baseline).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    (ROOT / "pyproject.toml", r'(?m)(^version = ")(\d+)\.(\d+)\.(\d+)(")'),
    (
        ROOT / "app" / "core" / "config.py",
        r'(db\.get_setting\("VERSION"\) or ")(\d+)\.(\d+)\.(\d+)(")',
    ),
    (
        ROOT / "src" / "py_restream" / "config" / "settings.py",
        r'(APP_VERSION = ")(\d+)\.(\d+)\.(\d+)(")',
    ),
]


def bump(match: re.Match) -> str:
    prefix, major, minor, patch, suffix = match.groups()
    return f"{prefix}{major}.{minor}.{int(patch) + 1}{suffix}"


def main() -> None:
    new_version = None
    for path, pattern in TARGETS:
        text = path.read_text(encoding="utf-8")
        new_text, count = re.subn(pattern, bump, text, count=1)
        if count != 1:
            raise SystemExit(f"[bump_version] pattern not found in {path}")
        path.write_text(new_text, encoding="utf-8")
        new_version = re.search(r"\d+\.\d+\.\d+", re.search(pattern, new_text).group(0)).group(0)

    print(new_version)


if __name__ == "__main__":
    main()
