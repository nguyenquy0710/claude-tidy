# CLAUDE.md — claude_tidy/ui/

Scope-specific guidance for this directory. Falls back to
[claude_tidy/CLAUDE.md](../CLAUDE.md) and the [root CLAUDE.md](../../CLAUDE.md)
for anything not covered here.

Built with **ttkbootstrap** (Tkinter + Bootstrap-style theming), not Flet —
see [plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](../../plans/2026-09-25-ttkbootstrap-ui-migration-planning.md)
for why and what changed.

## Module map

| Module | Responsibility |
|---|---|
| `app.py` | `build_app()` — creates the `tb.Window`, DPI awareness, `Dispatcher`, a 4-tab `Notebook` (`ExplorerView`, `CacheView`, `IndexView`, `SettingsView`), lazy-scans a tab the first time it's selected, starts `pump_forever`. `run()` calls `.mainloop()`. |
| `dispatch.py` | `Dispatcher` (thread-safe callable queue), `pump_forever(root, dispatcher)` (drains it on a `root.after` tick), `run_in_background(dispatcher, work, on_done, on_error)`. |
| `state.py` | `AppState` — loads `ClaudePaths`/`Settings` once at startup; `new_detector()` builds a fresh `ActivityDetector` (call this, don't cache a detector across a scan — state can go stale). No Tk import; stays reusable if the UI changes again. |
| `widgets.py` | `CheckTreeview` — the one checkbox-in-a-Treeview widget shared by Explorer's session list, Cache, and the delete-flow preview dialog. |
| `explorer.py` | `ExplorerView` — master-detail project/session browser (`ttk.Treeview` project tree with native parent/child nesting for worktrees; `CheckTreeview` session list), the single/multi/all delete actions. |
| `other_views.py` | `CacheView` (`CheckTreeview`), `IndexView` (orphaned `sessions/<pid>.json` — single-selection by design, see below), `SettingsView`. |
| `delete_flow.py` | `run_delete_flow()` — the **only** way any view triggers a deletion. |

## The one delete entry point

Every delete button, in every view, calls `delete_flow.run_delete_flow(root,
dispatcher, state, plan, on_done, typed_confirmation=...)`. It owns the whole
UX: build a `Preview` → render three sections (will-delete / needs-confirmation
`CheckTreeview` / skipped-with-reason) → optional typed-name confirmation for
destructive "all" plans → run `core.deleter.execute()` on a background thread
via `dispatch.run_in_background` → show the result dialog. If you're adding a
new delete action anywhere in the UI, call this function — do not call
`core.deleter.execute()` directly from a view, and do not build a second
preview/confirm dialog. This is what keeps the UI from ever growing a path
that skips the dry-run or the core safety checks.

**`tb.Toplevel`'s first positional argument is `title`, not the parent** —
unlike stock `tkinter.Toplevel`. Always construct it as
`tb.Toplevel(title="...", transient=root)`; passing `root` positionally
collides with the `title=` keyword (`TypeError: multiple values for
argument 'title'`) — this exact bug shipped once during the migration and was
only caught by the scripted UI smoke test, not by `pytest`.

## Threading and progress

Tkinter is not thread-safe: only the thread running `mainloop()` may touch a
widget. Scanning and deleting both run via `dispatch.run_in_background`,
**never** inline in an event handler — `ExplorerView.rescan`/`_scan_worker`,
`CacheView.rescan`/`_worker`, and `delete_flow._run_with_progress` are the
patterns to copy. `core.deleter.execute()` calls `on_progress` synchronously
from the worker thread it's running on; that callback must do nothing but
`dispatcher.post(lambda: ...)` — never mutate a widget directly from it. The
posted callback only actually runs later, when `pump_forever`'s `root.after`
tick drains the dispatcher on the main thread.

Cancellation (`delete_flow`'s cancel button) sets a `threading.Event` that
`deleter.execute()` only checks *between* targets — never assume a cancel
takes effect mid-target. Don't add a cancellation path that could interrupt a
single target half-deleted.

## `CheckTreeview`

`ttk.Treeview` has no native checkbox column; `widgets.CheckTreeview` fakes
one with a Unicode glyph (☐/☑) in a dedicated first column, toggled by
clicking that column or pressing Space on a selection. `checked_ids()` /
`check_all()` / `uncheck_all()` / `set_checked()` are the public API — don't
reach into `.tree` (the underlying `ttk.Treeview`) to flip a row's state by
hand, or `on_change` won't fire and callers relying on it (e.g. the preview
dialog's confirm-button gating) will silently desync.

There is intentionally **no built-in "check all" affordance** (no header-click
handler) — a caller wires `check_all()` to an explicit button only where a
bulk shortcut is wanted. `IndexView` doesn't wire one at all, and in fact uses
`show_checkboxes=False` (plain single-selection) rather than checkboxes,
specifically so a `_delete` action can never fire `run_delete_flow` for
several orphan entries at once — stacking multiple modal `Toplevel`s that way
is broken (only the most recent grab is interactive) and contradicts roadmap
decision 6.5 ("each orphan file confirmed individually").

## UI conventions

- User-facing strings are Vietnamese; keep new ones consistent with the
  existing tone (short, imperative for actions, e.g. "Xoá đã chọn").
- Risk badges use the shared `BADGE` / `_TAG_FG` maps in `explorer.py` keyed
  by `core.models.RiskLevel` — don't invent a parallel color scheme elsewhere.
- Every view exposes a `rescan()` method; `app.py` calls it lazily the first
  time a tab is selected, and `delete_flow` calls it again via `on_done` after
  any successful delete, so the list never shows a session that was just
  removed. `SettingsView.rescan()` is a no-op (nothing to reload from disk).
