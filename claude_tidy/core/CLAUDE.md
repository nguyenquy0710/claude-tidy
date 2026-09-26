# CLAUDE.md — claude_tidy/core/

Scope-specific guidance for this directory. Falls back to
[claude_tidy/CLAUDE.md](../CLAUDE.md) and the [root CLAUDE.md](../../CLAUDE.md)
(safety-critical rules) for anything not covered here.

This package is the safety boundary of the whole app. UI code is not trusted
to enforce any of the rules below on its own — everything here is re-checked
at the point of deletion, not just when a plan is built.

## Module map

| Module | Responsibility |
|---|---|
| `paths.py` | `ClaudePaths` — resolves `~/.claude`, Claude Desktop's data dir(s) (including the MSIX `Packages\Claude_*\LocalCache\...` location), `%TEMP%\claude`, and this app's own `%LOCALAPPDATA%\ClaudeTidy`. Every root is overridable via `CLAUDE_TIDY_*` env vars — that's what makes the test suite safe. |
| `models.py` | All shared dataclasses/enums: `Project`, `SessionBundle`, `IndexEntry`, `CacheGroup`, `DeleteTarget`, `DeletePlan`, `Preview`, `Progress`, `DeleteResult`. Add new cross-module state here, not as ad-hoc dicts. |
| `scanner.py` | `check_deletable()` (the allowlist+denylist gate — see below), `scan_projects()` (groups session artifacts into `SessionBundle` by `sessionId`), `scan_cache()`, `count_messages()` (line count per session transcript — UI's "Tin nhắn" column). |
| `grouping.py` | Nests worktree projects under their parent (`group_projects`), and builds `DeletePlan`s (`build_session_plan`, `build_index_plan`, `build_cache_plan`). |
| `usage.py` | `is_link()` (symlink/junction detection — used everywhere to avoid following links), disk usage helpers, `count_files()` (per-cache-group file count for the UI). |
| `activity.py` | `ActivityDetector` — the active-session/PID-reuse logic; `orphan_state()` exposes *why* an index entry is orphaned (GONE vs REUSED) for the Index tab's "Lý do" column; `claude_desktop_pid()` for the Cache tab's lock warning. |
| `risk.py` | Pure function mapping `(Activity, last_write, now)` → `RiskLevel` for UI badges only; never used to gate deletion (activity is, in `deleter.py`). |
| `backup.py` | `create_backup()` — zip with per-file sha256 manifest, verified before the caller may delete; `prune_backups()` for retention. |
| `deleter.py` | `preview()` / `execute()` — the one deletion pipeline. |
| `oplog.py` | Append-only JSON-lines operation log, input for the Phase 2 Restore feature. |
| `settings.py` | `Settings` dataclass, `load_settings()`/`save_settings()` — tolerant of a corrupt/partial settings file (falls back to defaults per-field, never crashes). |

## The one deletion pipeline

`deleter.execute()` is called by every delete action in the UI, no exceptions.
Its shape is fixed: `detector.refresh()` (state may be stale since the
preview) → `preview()` again → back up exactly what will be deleted →
`create_backup()` must verify before anything is removed → delete only the
files/dirs/links the backup actually captured → append one `oplog` record. If
you're adding a new delete mode (a new `PlanMode`), it goes through this same
function — build a `DeletePlan` for it in `grouping.py`, don't write a second
`execute`-like function.

`preview()` and `execute()` share one activity policy, encoded in
`deleter.preview()`: `Activity.ACTIVE` → always skipped (`SKIP_ACTIVE`), no
force option; `Activity.MAYBE_ACTIVE` → moved to `needs_confirmation` unless
its target id is already in the caller's `confirmed` set. Don't add a path
that deletes an `ACTIVE` target.

## `check_deletable()` — the allowlist/denylist gate

`scanner.check_deletable()` is called from two independent places
(`scanner.scan_project` when building bundles, and `deleter.preview` right
before backup/delete) so nothing can reach deletion by skipping the scanner.
It works by **allowlisting exact shapes** relative to each managed root
(`projects/<slug>/<sessionId-named-thing>`, `file-history|session-env|tasks/<uuid>`,
`sessions/<pid>.json` or `<pid>.<hash>.key`, one specific set of cache dir
names under each Desktop data dir, or anything one level under `%TEMP%\claude`)
— nothing outside those shapes is deletable, full stop. On top of that, every
path component is checked against `PROTECTED_PATTERNS`
(`memory`, `settings*.json`, `.credentials.json`, `CLAUDE.md`, `commands`,
`skills`, `agents`, `plugins`, `hooks`, `rules`) as a second, independent
guard. If you add a new deletable location, extend the allowlist function for
that root — do not weaken `PROTECTED_PATTERNS` to make something deletable.

Symlinks/junctions (`usage.is_link()`) are never followed for sizing or
recursive collection — `~/.claude/agents`, `skills`, and Desktop's
`vm_bundles` are real examples of links pointing outside anything this app
may touch.

## Process/activity detection

`procStart` in `sessions/<pid>.json` is a **Windows FILETIME string**
(100ns ticks since 1601-01-01), not epoch seconds — always go through
`filetime_to_epoch()`. `psutil.pid_exists()` alone is insufficient: PIDs get
reused, so `probe_process()` compares `psutil.Process(pid).create_time()`
against the recorded `procStart` within `PROC_START_TOLERANCE_SECONDS`.
`ProcessAccessDenied` maps to `ProcessState.UNKNOWN` → treated as
`Activity.MAYBE_ACTIVE`, never as dead. When you can't prove a process is
gone, the safe default is "maybe still running," not "safe to delete."

## Backup invariants

- `create_backup()` checks free disk space (`SPACE_MARGIN` + a fixed reserve)
  before writing anything.
- The zip is written to a `.zip.partial` path and only `replace()`d onto the
  final name after `_verify()` (testzip + per-file sha256 recheck) passes. A
  crash mid-write leaves only an orphaned `.partial`, never a corrupt backup
  masquerading as good.
- `deleter._delete_captured` only removes what `backup.captured[target.id]`
  actually recorded — if a file appeared after the backup snapshot, it's left
  alone rather than deleted unbacked-up.
- A target that can't be fully read (`OSError` during backup) is marked
  `unreadable` and excluded from `captured`, so it is never deleted.
- `_verify()` re-hashes every backed-up file from inside the zip rather than
  trusting `testzip()`'s CRC32 alone — that full re-read is what "deletion
  only proceeds if the backup verifies" actually rests on. It's also the
  slowest part of a large delete, so it reports its own progress via
  `on_verify_progress` — `Progress.phase` is `"backup"` → `"verify"` →
  `"delete"`, not just the first and third; a UI reading `phase` needs to
  handle all three.

## Adding a test for this package

New logic here needs a case in `tests/` using `tests/fixtures/fake_claude.py`
— see [tests/CLAUDE.md](../../tests/CLAUDE.md). Don't hand-roll a fixture tree
inline in a test module; extend `fake_claude.build()` instead so every test
shares the same known-good tree.
