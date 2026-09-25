# CLAUDE.md — tests/

Scope-specific guidance for this directory. Falls back to the
[root CLAUDE.md](../CLAUDE.md) and [.claude/rules/code-rules.md](../.claude/rules/code-rules.md)
(testing rules) for anything not covered here.

## The env-isolation fixture is load-bearing

`conftest.py`'s `_isolate_env` fixture is `autouse=True` and redirects
`USERPROFILE`/`HOME`/`APPDATA`/`LOCALAPPDATA`/`TEMP`/`TMP` plus every
`CLAUDE_TIDY_*` override into a per-test tmp sandbox, then asserts
`ClaudePaths.from_env()` landed inside it. This is the only thing preventing
this suite — whose entire job is exercising deletion — from ever touching a
developer's real `~/.claude`. Never write a test that constructs `ClaudePaths`
by hand pointing at a real path, and never disable or monkeypatch around this
fixture.

## `tests/fixtures/fake_claude.py`

`fake_claude.build(tmp_path)` builds one shared, realistic fake tree per test
(not static checked-in files — the tests destroy what they run against, so it
has to be regenerated fresh each time). It returns a `FakeClaude` with
`.paths`, `.probe` (a deterministic `FakeProbe` standing in for `psutil`), and
a list of `.protected` paths that must survive any "delete all" test.

The fixture pre-wires named session-id constants for each activity case —
reuse them instead of inventing new UUIDs:

| Constant | Case |
|---|---|
| `S_LIVE` / `PID_LIVE` | PID alive, `create_time()` matches `procStart` → `ACTIVE` |
| `S_REUSED` / `PID_REUSED` | PID alive but reused by a different process → not a match |
| `S_DEAD` / `PID_DEAD` | PID no longer exists |
| `S_DENIED` / `PID_DENIED` | `psutil.AccessDenied` on probe → `MAYBE_ACTIVE` |
| `PID_CORRUPT` | `sessions/<pid>.json` has invalid JSON |
| `S_OLD` / `S_RECENT` / `S_FRESH` | Vary `last_write` age for risk-badge / mtime-fallback tests |
| `S_WORKTREE` | Project slug encodes a worktree (`--claude-worktrees-`) for `grouping` tests |

`fixture.protected` includes `memory/`, `settings*.json`, `.credentials.json`,
`CLAUDE.md`, `commands/`, `skills/`, `agents/`, Desktop's non-cache dirs
(`Local Storage`, `IndexedDB`, config json), and a junction (`vm_bundles`)
pointing outside the tree entirely — any new denylist/allowlist behavior in
`core/scanner.py` should add its counter-example here, not in an ad-hoc
per-test fixture.

`make_junction()` falls back from a Windows directory junction to a symlink,
and returns `False` if neither is supported on the current machine/permissions
— guard tests that depend on the link actually existing.

## What to add when extending `core/`

- New activity states or process-probe edge cases → extend `FakeProbe`'s
  table and add a named constant, following the existing pattern, rather than
  hardcoding a bare PID number in the test.
- New protected/denylisted paths → add to `fake_claude.build()`'s `protected`
  list so every "delete all" test automatically covers it.
- Anything touching disk space, zip corruption, or partial writes in
  `backup.py` → use `tmp_path` directly (not `fake_claude`), since those are
  about the zip mechanics, not the `~/.claude` shape.
