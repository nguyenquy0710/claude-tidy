# CLAUDE.md — claude_tidy/webui/

Scope-specific guidance for this directory. Falls back to
[claude_tidy/CLAUDE.md](../CLAUDE.md) and the [root CLAUDE.md](../../CLAUDE.md)
for anything not covered here — read the root file's "Safety-critical rules"
first, they apply to everything below.

This is the current UI: pywebview (WebView2/`edgechromium`) hosting a static
HTML/Bootstrap 5/Alpine.js frontend, replacing the ttkbootstrap `claude_tidy/ui/`
package removed in task T40 — see
[plans/2026-09-25-pywebview-ui-migration-planning.md](../../plans/2026-09-25-pywebview-ui-migration-planning.md).

## Module map

| Module | Responsibility |
|---|---|
| `app.py` | `run()` — checks the WebView2 Runtime registry key before doing anything else (missing → `MessageBoxW`, not a Tk dialog — this package imports no `tkinter`), then `webview.create_window(..., js_api=Api(...))` + `webview.start(gui="edgechromium")`. Always force `gui="edgechromium"`; letting pywebview fall back to MSHTML/IE breaks Bootstrap 5. |
| `state.py` | `AppState` — loads `ClaudePaths`/`Settings` once at startup; `new_detector()` builds a fresh `ActivityDetector` per call (state can go stale across a scan, don't cache one). `probe` is injectable so tests can pass a `FakeProbe` instead of hitting real `psutil`. |
| `api.py` | `Api` — the entire `js_api` surface. Every method returns a JSON-safe dict via `dto.py`. Includes read/refresh helpers alongside the delete pair: `rescan_project(project_id)` re-scans one project directory only (`core.scanner.scan_project`, the same function `scan_projects` calls per-entry) instead of the whole `~/.claude/projects` tree, for a cheap right-click "refresh"; `open_project_folder(project_id)` resolves the id server-side same as everything else and calls `os.startfile(cwd)` — read-only, so it doesn't go through `preview_delete`/`execute_delete`, but still never trusts a path coming from JS. `list_backups()`/`preview_restore(backup_id)`/`execute_restore(token, confirmed_ids)` are the restore-from-backup pair (T17) — see "Trust boundary" below for the token shape and `_resolve_backup`. |
| `dto.py` | `core/models.py` dataclasses → JSON-safe dicts (paths become display strings, enums become `.value`). |
| `jobs.py` | `JobRunner` — runs scan/delete work on a background thread, pushes `job_progress`/`job_done`/`job_error` events through a plain `notify(name, payload)` callable (decoupled from `evaluate_js` so it's testable without a window). |
| `static/index.html` + `static/app.js` + `static/app.css` | Alpine.js `app()` component bound to the 4 tabs (Sessions/Cache/Index/Settings) and the shared delete-flow modals. `static/vendor/` has Bootstrap 5 + Alpine.js **downloaded locally**, never CDN — the app must run offline and package with PyInstaller. |

## Trust boundary: safety logic lives in Python, never in JS

This is the one rule everything else here exists to protect (root `CLAUDE.md`
rules 1–9 apply in full):

- **JS never sends a filesystem path.** It sends `project_id`/`session_id`/
  `group_id`/`entry_id` strings, resolved server-side against the *last scan*
  (`Api._find_project`, `Api._cache_groups`, `Api._index_entries`) — never
  trusted as a raw path. A `DeletePlan` is always built in Python
  (`Api._build_plan`) from that resolved data.
- **Every delete goes through exactly one token-based pair:**
  `preview_delete(spec)` → runs `core.deleter.preview`, stores the plan under
  a one-time `secrets.token_urlsafe` token, returns a DTO with `will_delete`/
  `needs_confirmation`/`skipped` + the token. `execute_delete(token,
  confirmed_ids, typed_name)` re-validates everything server-side — token
  exists and hasn't been used, `typed_name` matches the project name for
  "delete all" — **before** calling `core.deleter.execute()`. A malicious or
  buggy frontend passing an `ACTIVE` session's id in `confirmed_ids` still
  can't delete it; `deleter.execute()` enforces that regardless of what the
  API layer forwards (see `test_active_session_is_never_deleted_even_if_confirmed`
  in `tests/test_webui_api.py`).
- **One delete at a time.** `Api._deleting` (guarded by `Api._delete_lock`)
  stays `True` for the *entire* background job, not just the synchronous
  part of `execute_delete()` — a second `execute_delete()` call while one is
  still running is rejected. Don't "simplify" this back to holding the lock
  only around the initial dispatch; that was a real bug caught by
  `test_concurrent_delete_is_rejected` (a slow-fake `execute()` monkeypatch
  proves the second call is rejected mid-job, not just at the exact instant
  of the first call).
- **Token consumption order matters.** The token is only popped from
  `Api._pending` *after* the `typed_name` check passes — a typo on "delete
  all" must not permanently burn the one-time token before the user can
  retry.
- **Restore mirrors the same token shape** (`core/restore.py`, T17):
  `preview_restore(backup_id)` resolves `backup_id` (a bare filename, never a
  path) through `Api._resolve_backup` — joined onto the configured backup dir
  and re-checked with `Path.relative_to()` so a crafted `"..\\..\\x.zip"`
  can't escape it — then runs `core.restore.preview_restore`, which
  re-validates every target's original backup `roots` against
  `scanner.check_deletable()` before offering it, so a hand-edited or foreign
  zip in the backup dir can't be used to plant files outside the managed
  session/index/cache locations. `execute_restore(token, confirmed_ids)`
  re-runs that same check server-side and only writes files whose
  destination doesn't already exist, unless the target's id is in
  `confirmed_ids`. `Api._restoring`/`Api._restore_lock` guard one restore at a
  time, same pattern as `_deleting`/`_delete_lock` — kept as a separate flag
  because restore and delete are independent operations, not cross-locked
  against each other.

## `evaluate_js` and Promises

`window.evaluate_js(script)` (Python → JS) does **not** auto-resolve a
Promise unless you pass `callback=`. Calling it without `callback` on a
script that returns a Promise gets you `{}` (the unresolved Promise object
serialized with no own properties) — not an exception, so this fails
silently if you don't know to look for it. Confirmed against a live
`edgechromium` window during the T33 spike (see the migration plan's T33
entry). This doesn't affect `jobs.py`'s `notify` → `onJobEvent` calls (Python
never reads a return value from those), but matters for any future code that
needs Python to read a value back out of JS.

## DTO contract (`dto.py`)

Every dict returned to JS is built here, never assembled ad hoc in `api.py`
or written directly in JS. Keep both sides in sync when a field is added —
`static/app.js` reads dict keys with no other type checking:

| Function | Consumed by (app.js) |
|---|---|
| `project_to_dict` | `list_projects()`, project sidebar + worktree tree |
| `session_to_dict` | `list_sessions()`, the session table (`risk`/`activity`/`active_pid` drive `riskBadge()`) |
| `cache_group_to_dict` | `scan_cache()`, the Cache/Temp table |
| `index_entry_to_dict` | `list_orphan_index()`, the Index mồ côi table |
| `target_to_dict` | one row inside `will_delete`/`needs_confirmation`/`skipped` |
| `preview_to_dict` | the dry-run preview modal — `size_bytes` on the `Preview` model is `will_delete` only, *not* `needs_confirmation`; `app.js`'s `previewConfirmedSizeBytes` getter adds the confirmed `needs_confirmation` targets' sizes back in for the confirm-button total |
| `result_to_dict` | the result modal after `execute_delete` finishes |
| `backup_file_to_dict` | `list_backups()`, the "Khôi phục từ backup" table in Settings |
| `restore_item_to_dict` | one row inside `will_restore`/`needs_confirmation`/`refused` |
| `restore_preview_to_dict` | the restore dry-run preview modal |
| `restore_result_to_dict` | the restore result modal after `execute_restore` finishes |

## Frontend conventions

- User-facing strings are Vietnamese, short and imperative for actions (e.g.
  "Xoá đã chọn") — matches the removed ttkbootstrap UI's tone.
- **Alpine `x-show` + a Bootstrap `!important` display utility (`.d-flex`,
  `.d-none`, `.d-block`, `.d-grid`) on the *same element* silently breaks.**
  Bootstrap's utility sets `display: X !important`, which beats Alpine's
  plain (non-`!important`) inline `display: none` — the element never
  actually hides, even though the DOM's internal state looks correct on
  inspection. Use the `x-show.important` modifier on any element that also
  carries one of those classes. Two real instances of this shipped and were
  caught by Playwright screenshot verification, not by reading the code: the
  Sessions-tab wrapper and the Claude-Desktop-running alert in Cache/Temp —
  see both in `static/index.html`.
- The project sidebar's right-click context menu (`app.js`'s `projectMenu`
  state, `openProjectMenu`/`openProjectFolder`/`copyProjectPath`/
  `rescanProjectMenu`/`deleteAllProjectMenu`) is plain Alpine state, not a
  Bootstrap component — it's positioned at the click coordinates and closed by
  setting `projectMenu = null`. `rescanProjectMenu` patches just the one
  changed project back into `projects`/`worktrees` in place
  (`replaceProjectEverywhere`) rather than re-fetching the whole list; keep
  that pattern for any future per-item refresh instead of calling
  `list_projects()` again.
- Index mồ côi has **no "select all"**, only per-row single selection — a
  deliberate carry-over from the ttkbootstrap UI (roadmap decision 6.5: each
  orphan file is confirmed individually, never bulk).
- Risk badges are real rounded pills (`.ct-badge-danger/warning/safe` in
  `app.css`) — the ttkbootstrap UI could only tag a whole row's color, not a
  single cell; HTML doesn't have that limitation, so don't reintroduce a
  flat-text badge.
- `static/vendor/` assets are committed as downloaded files, not fetched at
  build time — there is no npm/webpack step in this project. If you bump
  Bootstrap or Alpine, replace the files in `static/vendor/` directly and
  re-verify (Playwright against a stub `window.pywebview.api`, or a real
  `webview` window — see the T33 spike pattern in the migration plan for how
  to do the latter without touching a real `~/.claude`).
