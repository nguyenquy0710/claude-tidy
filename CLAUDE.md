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
breakdown) as the source of truth for scope, architecture, and open decisions —
read both before implementing anything. Do not re-derive the architecture from
scratch; it is already designed there.

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
8. Two currently **open product decisions** gate `T10`/`T12` — soft-skip vs.
   block when an active session is caught in a multi/all selection, and the
   default backup retention policy. Check `plans/2026-09-25-session-cleaner-mvp-roadmap.md`
   §6 before implementing those tasks; don't guess an answer that contradicts
   a decision the project owner later makes there.

## Testing requirements

- Every function in `core/` that touches the filesystem must be tested
  against the fixture tree in `tests/fixtures/`, not the real `~/.claude`.
- Active-session detection tests must cover: PID alive, PID dead, PID reused
  by an unrelated process, and a corrupt/missing `sessions/*.json`.
- "Delete all" tests must assert `memory/` and denylisted files survive.
- No test may write outside a fixture/tmp directory — this app's own test
  suite must not risk touching a real `~/.claude`.

## Coding conventions

- Python 3.11+, type hints throughout `core/` (these are the modules most in
  need of static-analysis confidence given the safety rules above).
- `ruff` for linting; keep it clean before committing.
- Comments: only for non-obvious *why* (e.g. why PID reuse checking exists,
  why zip+manifest was chosen over Recycle Bin). Don't restate what
  well-named code already says.

## Repo layout today

- `docs/claude-session-cleaner-idea.md` — product spec (Vietnamese). See [docs/CLAUDE.md](docs/CLAUDE.md).
- `plans/*.md` — execution plans / task breakdowns. See [plans/CLAUDE.md](plans/CLAUDE.md).
- `claude_tidy/core/` — scan, activity, risk, backup, the single `deleter.execute`
  pipeline. `check_deletable()` in `scanner.py` is the allowlist+denylist gate.
- `claude_tidy/ui/` — Flet views; every delete button goes through
  `ui/delete_flow.run_delete_flow` (preview → confirm → `execute`).
- `tests/fixtures/fake_claude.py` builds the fake `~/.claude` tree per test;
  `tests/conftest.py` redirects all env-derived paths into tmp.
- `main.py` — entry point for `flet build windows`.
- No `.rtk/` runtime directory: this repo has no build/runtime artifacts that
  land inside the repo tree itself (the app's own backups/logs live under the
  end user's `%LOCALAPPDATA%`, not here), so it was skipped.
