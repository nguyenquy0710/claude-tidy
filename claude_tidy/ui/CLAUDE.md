# CLAUDE.md — claude_tidy/ui/

Scope-specific guidance for this directory. Falls back to
[claude_tidy/CLAUDE.md](../CLAUDE.md) and the [root CLAUDE.md](../../CLAUDE.md)
for anything not covered here.

## Module map

| Module | Responsibility |
|---|---|
| `app.py` | `main(page)` — builds the `NavigationRail` and wires the four views (`ExplorerView`, `CacheView`, `IndexView`, `SettingsView`); `run()` is the `ft.run()` entry point. |
| `state.py` | `AppState` — loads `ClaudePaths`/`Settings` once at startup; `new_detector()` builds a fresh `ActivityDetector` (call this, don't cache a detector across a scan — state can go stale). |
| `explorer.py` | `ExplorerView` — master-detail project/session browser, the single/multi/all delete actions. |
| `other_views.py` | `CacheView`, `IndexView` (orphaned `sessions/<pid>.json`), `SettingsView`. |
| `delete_flow.py` | `run_delete_flow()` — the **only** way any view triggers a deletion. |

## The one delete entry point

Every delete button, in every view, calls `delete_flow.run_delete_flow(page,
state, plan, on_done, typed_confirmation=...)`. It owns the whole UX:
build a `Preview` → render three sections (will-delete / needs-confirmation
checkboxes / skipped-with-reason) → optional typed-name confirmation for
destructive "all" plans → run `core.deleter.execute()` on a background thread
via `page.run_thread()` → show the result dialog. If you're adding a new
delete action anywhere in the UI, call this function — do not call
`core.deleter.execute()` directly from a view, and do not build a second
preview/confirm dialog. This is what keeps the UI from ever growing a path
that skips the dry-run or the core safety checks.

## Threading and progress

Scanning and deleting both run on `page.run_thread()`, never inline in an
event handler — `ExplorerView._scan_worker`, `CacheView._worker`, and
`delete_flow._run_with_progress` are the patterns to copy. Progress callbacks
(`on_progress`) mutate Flet controls and then call `page.update()`; do this
from the callback the core layer invokes, not by polling.

Cancellation (`delete_flow`'s cancel button) sets a `threading.Event` that
`deleter.execute()` only checks *between* targets — never assume a cancel
takes effect mid-target. Don't add a cancellation path that could interrupt a
single target half-deleted.

## UI conventions

- User-facing strings are Vietnamese; keep new ones consistent with the
  existing tone (short, imperative for actions, e.g. "Xoá đã chọn").
- Risk badges use the shared `BADGE` color map in `explorer.py` keyed by
  `core.models.RiskLevel` — don't invent a parallel color scheme elsewhere.
- Every view exposes a `rescan()` method called after any successful delete
  (`on_done` callback) so the list never shows a session that was just
  removed.
