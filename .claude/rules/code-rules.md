# Code rules

## Testing rules

- Tests must run against `tests/fixtures/` (a fake `~/.claude` tree), never
  against the real `~/.claude`, `%APPDATA%\Claude`, or `%TEMP%\claude` on the
  machine running the suite. This app's core job is deleting files in those
  exact locations — a test that "accidentally" points at the real paths is
  the one bug class this repo cannot tolerate.
- Any path the code touches (`core/paths.py`) must be injectable/overridable
  so tests can redirect it into a fixture or `tmp_path`.
- Deletion-path tests (`deleter.py`, `activity.py`, `risk.py`) require
  explicit coverage for: PID alive, PID dead, PID reused by an unrelated
  process, corrupt/missing `sessions/*.json`, and denylisted paths
  (`memory/`, `settings*.json`, `.credentials.json`) surviving a "delete all."
- No network calls, no prompts, no interactive confirmation in unit tests —
  those belong in manual/UI smoke testing (`T16`).

## Comment cleanup rule

Self-documenting code > comments. Before adding a comment, prefer renaming a
variable/function or extracting a small function with a clear name.

Add a comment only when it explains a **non-obvious why**:
- A safety-critical decision (e.g. why `create_time()` is compared, not just
  `pid_exists()`; why a hard denylist exists instead of a UI-only warning).
- A workaround for a specific OS/library quirk (e.g. a file lock from Claude
  Desktop still running).
- A constraint that isn't visible from the code itself (e.g. "must not read
  the whole `.jsonl`, only head/tail — files can be large").

Don't add a comment that:
- Restates what the function/variable name already says.
- Describes *what* the code does step by step (that's what reading the code
  is for).
- References a task ID, PR, or "fix for issue #N" — that belongs in the
  commit message, not the source.

When touching existing code, remove comments that have gone stale (describe
behavior the code no longer has) rather than leaving them to rot.
