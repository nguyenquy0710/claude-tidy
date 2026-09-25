# CLAUDE.md

Guidance for Claude Code (and other AI agents) working in this repository.

## Project

**claude-tidy** — a Windows desktop app that safely cleans up Claude Code session
data and Claude Desktop cache, with backup, active-session detection, and
per-project session management.

This repo is **greenfield**: as of now it contains only planning docs
(`docs/`, `plans/`) and no source code yet. Treat `docs/claude-session-cleaner-idea.md`
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

## Planned architecture

Two-layer design, core logic independent of the UI so the dangerous parts
(active-session detection, deletion) are unit-testable without launching Flet:

```
claude_tidy/
  core/
    paths.py       # resolve ~/.claude, %APPDATA%\Claude, %TEMP%\claude (injectable for tests)
    models.py       # Project, SessionBundle, RiskLevel, DeletePlan, OperationRecord
    scanner.py      # scan + group into SessionBundle by sessionId
    grouping.py      # list by project, build DeletePlan for single/multi/all
    usage.py         # disk usage calculation
    activity.py      # active-session detection
    risk.py          # safe/warning/danger badge logic
    backup.py         # zip + manifest
    deleter.py         # execute(plan, on_progress) — the one deletion pipeline
    oplog.py            # JSON-lines operation log, feeds Phase 2 Restore
    settings.py          # read/write config
  ui/                 # Flet views: explorer, settings, cache view, dialogs
tests/fixtures/       # fake ~/.claude tree for tests
```

Once `T01` (see the roadmap) scaffolds this package, re-run
`/nqdev-init-agents --sub-claude` so `claude_tidy/core/CLAUDE.md`,
`claude_tidy/ui/CLAUDE.md`, and `tests/CLAUDE.md` get generated against the
real files instead of this placeholder description.

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
- No `.rtk/` runtime directory: this repo has no build/runtime artifacts that
  land inside the repo tree itself (the app's own backups/logs live under the
  end user's `%LOCALAPPDATA%`, not here), so it was skipped.
