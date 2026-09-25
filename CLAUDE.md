# CLAUDE.md

Guidance for Claude Code (and other AI agents) working in this repository.

## Project

**claude-tidy** — a Windows desktop app that safely cleans up Claude Code session
data and Claude Desktop cache, with backup, active-session detection, and
per-project session management.

The MVP core (`claude_tidy/core/`), Flet UI (`claude_tidy/ui/`) and pytest
suite (`tests/`) exist; packaging (`flet build windows`, T16) is not done yet.
Setup: `python -m venv .venv && .venv/Scripts/pip install -e .[dev]`, then
`.venv/Scripts/python -m pytest` / `ruff check .` / `python -m claude_tidy`.
Treat `docs/claude-session-cleaner-idea.md`
(the product spec) and `plans/2026-09-25-session-cleaner-mvp-roadmap.md` (the task
breakdown, including §6 "Questions / Dependencies" — all resolved as of
2026-09-25) as the source of truth for scope, architecture, and prior
decisions — read both before implementing anything. Do not re-derive the
architecture from scratch; it is already designed there. Remaining open work
is just `T01` (verify `flet build windows` — the dev machine doesn't have the
Flutter SDK / VS C++ workload installed yet) and `T16` (packaging + smoke
test on a clean machine).

## Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.11+ |
| GUI framework | Flet |
| Packaging | `flet build windows` → `.exe` |
| Safe deletion | Backup to timestamped `.zip` + manifest (not `send2trash`/Recycle Bin — see rationale below) |
| Process detection | `psutil` (PID liveness + `create_time()` to defeat PID reuse) |
| Testing | `pytest`, with fixtures simulating a fake `~/.claude` tree |
| Linting | `ruff` |

Out of scope: macOS/Linux builds, code-signing/installer, auto-update.

## Architecture

Two-layer design, core logic independent of the UI so the dangerous parts
(active-session detection, deletion) are unit-testable without launching Flet:

```
claude_tidy/
  core/       # filesystem + safety logic — no Flet import anywhere in here
  ui/         # Flet views; every delete goes through ui/delete_flow.py
tests/
  fixtures/   # fake ~/.claude tree, regenerated per test
```

See [claude_tidy/CLAUDE.md](claude_tidy/CLAUDE.md) for the package-level
conventions, [claude_tidy/core/CLAUDE.md](claude_tidy/core/CLAUDE.md) for the
deletion-pipeline internals, [claude_tidy/ui/CLAUDE.md](claude_tidy/ui/CLAUDE.md)
for the Flet layer, and [tests/CLAUDE.md](tests/CLAUDE.md) for the test
harness — each is scoped to that directory and takes precedence over this
file for anything specific to it.

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

- `docs/claude-session-cleaner-idea.md` — product spec (Vietnamese). See [docs/CLAUDE.md](docs/CLAUDE.md).
- `plans/*.md` — execution plans / task breakdowns. See [plans/CLAUDE.md](plans/CLAUDE.md).
- `claude_tidy/` — the package; see [claude_tidy/CLAUDE.md](claude_tidy/CLAUDE.md),
  [claude_tidy/core/CLAUDE.md](claude_tidy/core/CLAUDE.md), and
  [claude_tidy/ui/CLAUDE.md](claude_tidy/ui/CLAUDE.md).
- `tests/` — pytest suite; see [tests/CLAUDE.md](tests/CLAUDE.md).
- `main.py` — entry point for `flet build windows`; `pyproject.toml` has the
  `[tool.flet]` build config and the `claude-tidy` console script.
- No `.rtk/` runtime directory: this repo has no build/runtime artifacts that
  land inside the repo tree itself (the app's own backups/logs live under the
  end user's `%LOCALAPPDATA%`, not here), so it was skipped.
