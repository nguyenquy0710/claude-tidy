"""Bump claude-tidy's patch version in pyproject.toml.

Run before a desktop build so every build ships a distinct version:
  python .bin\\bump_version.py

pyproject.toml's `version = "X.Y.Z"` is the only place the version is
recorded in this repo — there's no separate settings/config module to keep
in sync (unlike other projects that also embed a version fallback in code).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PATTERN = r'(?m)(^version = ")(\d+)\.(\d+)\.(\d+)(")'


def bump(match: re.Match) -> str:
    prefix, major, minor, patch, suffix = match.groups()
    return f"{prefix}{major}.{minor}.{int(patch) + 1}{suffix}"


def main() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    new_text, count = re.subn(PATTERN, bump, text, count=1)
    if count != 1:
        raise SystemExit(f"[bump_version] version pattern not found in {PYPROJECT}")
    PYPROJECT.write_text(new_text, encoding="utf-8")
    print(re.search(PATTERN, new_text).group(0).split('"')[1])


if __name__ == "__main__":
    main()
