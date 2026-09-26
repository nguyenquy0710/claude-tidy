# CLAUDE.md

Guidance for Claude Code (and other AI agents) working in this repository.

## Project

**claude-tidy** — a Windows desktop app that safely cleans up Claude Code session
data and Claude Desktop cache, with backup, active-session detection, and
per-project session management.

The MVP core (`claude_tidy/core/`) and pytest suite (`tests/`) exist and are
UI-framework-independent. **The UI has been through two rewrites in one day
(2026-09-25):** Flet → ttkbootstrap (superseded) → **pywebview +
HTML/Bootstrap 5/Alpine.js**, now the sole UI in `claude_tidy/webui/`.
`claude_tidy/ui/` (ttkbootstrap) was deleted outright in task T40 once
`webui/` reached parity — this repo keeps exactly one UI at a time, never two
in parallel long-term. The only work left on the current UI is `T42` (E2E
Playwright coverage + a clean-machine/no-WebView2 smoke test). Setup:
`python -m venv .venv && .venv/Scripts/pip install -e .[dev]` (or
`.bin/py-requirements.bat --install`), then `.venv/Scripts/python -m pytest` /
`ruff check .` / `python -m claude_tidy` (or `.bin/run_webapp.bat`). The
committed `requirements.txt` at repo root is an empty stub, not the real
dependency source — `pyproject.toml` is (see `.bin/py-requirements.bat`'s own
comment to this effect).

Read, in order: `plans/2026-09-25-session-cleaner-mvp-roadmap.md` (original
scope/architecture, T01–T21, §6 all resolved), then
[plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](plans/2026-09-25-ttkbootstrap-ui-migration-planning.md)
(T22–T32 — **superseded**, kept as a historical work log; its Jira issues
QUYIT-763..773 were transitioned to Rejected on 2026-09-26, same precedent as
T01/T16 when Flet was superseded), then
[plans/2026-09-25-pywebview-ui-migration-planning.md](plans/2026-09-25-pywebview-ui-migration-planning.md)
(T33–T43 — **current**, source of truth for the UI; all done except `T42`).
Do not re-derive the architecture from scratch; it is already designed there.

## Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.11+ |
| GUI framework | **pywebview** (WebView2/`edgechromium`) + static HTML/Bootstrap 5/Alpine.js — replaced ttkbootstrap, which replaced Flet |
| Packaging | PyInstaller, `--onedir` (not `--onefile` — measured cold-start regression) |
| Safe deletion | Backup to timestamped `.zip` + manifest (not `send2trash`/Recycle Bin — see rationale below) |
| Process detection | `psutil` (PID liveness + `create_time()` to defeat PID reuse) |
| Testing | `pytest`, with fixtures simulating a fake `~/.claude` tree |
| Linting | `ruff` |

Out of scope: macOS/Linux builds, code-signing/installer, auto-update.

## Architecture

Two-layer design, core logic independent of the UI so the dangerous parts
(active-session detection, deletion) are unit-testable without launching a GUI:

```
claude_tidy/
  core/       # filesystem + safety logic — no UI framework import anywhere in here
  webui/      # pywebview + HTML/Bootstrap 5/Alpine.js — the UI
tests/
  fixtures/   # fake ~/.claude tree, regenerated per test
```

See [claude_tidy/CLAUDE.md](claude_tidy/CLAUDE.md) for the package-level
conventions, [claude_tidy/core/CLAUDE.md](claude_tidy/core/CLAUDE.md) for the
deletion-pipeline internals, [claude_tidy/webui/CLAUDE.md](claude_tidy/webui/CLAUDE.md)
for the pywebview/JS trust boundary, and [tests/CLAUDE.md](tests/CLAUDE.md)
for the test harness — each is scoped to that directory and takes precedence
over this file for anything specific to it.

## Safety-critical rules (non-negotiable)

This app deletes user data. Every rule below exists because a mistake here
destroys a Claude Code session the user may still be using.

1. **One deletion pipeline.** All three delete modes (single / multi-select /
   whole-project) MUST go through the same `execute(plan, on_progress)`
   function in `core/deleter.py`. Never add a second code path with different
   safety guarantees.
2. **Backup before delete, always.** No path skips the zip+manifest backup
   step, and deletion only proceeds if the backup verifies.
3. **Never trust `psutil.pid_exists()` alone.** PIDs get reused by the OS.
   Always compare `psutil.Process(pid).create_time()` against the `procStart`
   recorded in `sessions/<pid>.json`.
4. **A "session" is a bundle, not a file.** Deleting the `.jsonl` alone
   orphans `file-history/<sessionId>/`, `session-env/<sessionId>/`,
   `tasks/<sessionId>/`, and the `*.jsonl.wakatime` sidecar. The Scan Engine
   must group all of these by `sessionId` before any delete plan is built.
5. **Hard denylist, not best-effort.** `memory/`, `settings*.json`,
   `.credentials.json`, `CLAUDE.md`, `commands/`, `skills/`, `agents/` are
   never eligible for deletion under any mode, including "delete all sessions
   for project." This must be enforced in the Scan Engine, not left to UI
   confirmation dialogs.
6. **Re-check activity immediately before deleting**, not just at plan-build
   time — state can change between preview and execution.
7. **"Delete all" requires double-confirmation** (e.g. typing the project
   name) with no bypass for the active check.
8. **Resolved policy for `ACTIVE`/`MAYBE_ACTIVE` in a selection** (roadmap §6,
   implemented in `core/deleter.preview`): `ACTIVE` sessions are always
   soft-skipped and reported after the fact — there is no force-delete option
   anywhere, including "delete all." `MAYBE_ACTIVE` sessions are held back
   pending an explicit per-item confirmation (checkbox in the dry-run
   dialog); they are deleted only if the caller passes their id back in
   `confirmed`. Don't add a way to bypass either check.
9. **`psutil.AccessDenied` counts as `MAYBE_ACTIVE`, not dead.** If the app
   can't read a process's start time, treat it as possibly-active rather than
   assuming it's gone — see `ProcessState.UNKNOWN` in `core/activity.py`.
10. **The JS frontend is not a trust boundary.** It sends only opaque ids
    (`project_id`/`session_id`/etc.), never a filesystem path; every delete
    goes through a server-side `preview_delete(spec)` → `execute_delete(token,
    confirmed_ids, typed_name)` pair that re-validates everything in Python
    (`webui/api.py`), so a compromised or buggy frontend still can't delete
    an `ACTIVE` session or bypass the typed-name check. See
    [claude_tidy/webui/CLAUDE.md](claude_tidy/webui/CLAUDE.md) for the full
    contract.

## Testing requirements

- `tests/conftest.py` has an **autouse** fixture (`_isolate_env`) that
  redirects every env var `ClaudePaths.from_env()` reads into a per-test tmp
  sandbox. Never write a test that constructs `ClaudePaths` from real
  environment variables outside that fixture's control — this is the one
  thing standing between this test suite and deleting the developer's actual
  `~/.claude`.
- Every function in `core/` that touches the filesystem must be tested
  against the fixture tree in `tests/fixtures/fake_claude.py`, not the real
  `~/.claude`.
- Active-session detection tests must cover: PID alive, PID dead, PID reused
  by an unrelated process, `AccessDenied`, and a corrupt/missing
  `sessions/*.json` — see `tests/CLAUDE.md` for the fixture's fixed PID
  constants that already encode each case.
- "Delete all" tests must assert `memory/` and denylisted files survive.
- No test may write outside a fixture/tmp directory.

See [tests/CLAUDE.md](tests/CLAUDE.md) for fixture-level detail.

## Coding conventions

- Python 3.11+, `from __future__ import annotations` in every module,
  `StrEnum` for closed sets of string states (`Activity`, `RiskLevel`,
  `TargetKind`, `PlanMode`), `@dataclass` for the models in `core/models.py`.
- Type hints throughout `core/` (these are the modules most in need of
  static-analysis confidence given the safety rules above). External
  dependencies that are hard to fake in tests (`psutil`) are wrapped behind a
  small `Protocol` (see `ProcessProbe` / `PsutilProbe` / `FakeProbe` in
  `core/activity.py`) — follow that pattern for any new OS-level dependency.
- `ruff` for linting (`select = ["E", "F", "W", "I", "B", "UP", "SIM"]`); keep
  it clean before committing.
- Comments: only for non-obvious *why* (e.g. why PID reuse checking exists,
  why zip+manifest was chosen over Recycle Bin). Don't restate what
  well-named code already says.

## Repo layout today

- `docs/claude-tidy-plan.md` — current product spec (Vietnamese, pywebview +
  Bootstrap 5, verified consistent with the code as of `T43`). It has been
  overwritten in place twice now (Flet version, then ttkbootstrap version);
  each earlier version is only reachable via
  `git log --follow -- docs/claude-tidy-plan.md`, not as a separate file. See
  [docs/CLAUDE.md](docs/CLAUDE.md).
- `docs/claude-tidy — UI.html` — a bundler-exported HTML prototype; markup is
  compressed inside `<script type="__bundler/...">` tags and self-inflates via
  JS on open. Not directly reusable as source — `webui/static/index.html` was
  hand-written to match it, not extracted from it (see `T34`).
- `plans/*.md` — execution plans / task breakdowns, including superseded ones
  kept as historical log (frontmatter `status: superseded`). See
  [plans/CLAUDE.md](plans/CLAUDE.md).
- `claude_tidy/` — the package; see [claude_tidy/CLAUDE.md](claude_tidy/CLAUDE.md),
  [claude_tidy/core/CLAUDE.md](claude_tidy/core/CLAUDE.md), and
  [claude_tidy/webui/CLAUDE.md](claude_tidy/webui/CLAUDE.md).
- `tests/` — pytest suite; see [tests/CLAUDE.md](tests/CLAUDE.md).
- `main.py` — entry point PyInstaller bundles; `claude-tidy.spec` is the
  version-controlled build spec (`--onedir`, with `collect_all()` for
  `webview`/`clr_loader`/`pythonnet` so `Python.Runtime.dll` and
  `WebView2Loader.dll` get bundled, not just their data files).
- `.bin/*.bat` + `.bin/bump_version.py` — dev/build scripts (install deps, run
  the app, build the `.exe`); see each script's own comments before assuming
  what it does, they resolve the repo root themselves and are meant to be run
  from anywhere.
- `requirements.txt` at repo root is an empty, unused stub — don't treat it as
  the dependency list; `pyproject.toml` is.
- No `.rtk/` runtime directory: this repo has no build/runtime artifacts that
  land inside the repo tree itself (the app's own backups/logs live under the
  end user's `%LOCALAPPDATA%`, not here; `build/`/`dist/` from PyInstaller are
  gitignored), so it was skipped.
