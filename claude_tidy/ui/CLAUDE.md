# CLAUDE.md — claude_tidy/ui/

Scope-specific guidance for this directory. Falls back to
[claude_tidy/CLAUDE.md](../CLAUDE.md) and the [root CLAUDE.md](../../CLAUDE.md)
for anything not covered here.

> ⚠️ **This directory is being phased out (2026-09-26).** The UI is migrating
> to `claude_tidy/webui/` (pywebview + HTML/Bootstrap 5) — see
> [plans/2026-09-25-pywebview-ui-migration-planning.md](../../plans/2026-09-25-pywebview-ui-migration-planning.md).
> `ui/` still runs and is still the shipped UI until that migration reaches
> parity, but **don't add features here** — put new UI work in `webui/`.
> Task T40 of the migration plan deletes this directory outright once parity
> is confirmed. The content below (built with ttkbootstrap, not Flet — see
> [plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](../../plans/2026-09-25-ttkbootstrap-ui-migration-planning.md),
> now superseded) still describes how the current code works in the
> meantime.

## Visual design source of truth

`docs/claude-tidy — UI.html` is a self-contained design mockup (open it in a
browser — the raw HTML source is an obfuscated asset bundle, not readable
markup) showing all 4 tabs plus the preview and delete-all dialogs. The
current UI was built to match it, with three deliberate, disclosed
deviations forced by Tk/ttkbootstrap limits — don't try to "fix" these later
without re-reading why:

1. **No custom title bar.** The mockup has its own icon/version/minimize/
   maximize/close bar. Replicating that means `overrideredirect(True)` (drops
   the native title bar entirely) plus hand-rolled drag/resize/minimize —
   real regression risk for a utility app. Instead, `app.py` adds a plain
   app-bar strip (icon + name + version) *below* the native, working OS
   title bar.
2. **Risk badges are colored text, not pills.** `ttk.Treeview`/`Tableview`
   can only tag a whole row's foreground/background, never a single cell —
   there's no way to draw a rounded, colored badge inside one cell. See
   `DANGER_FG`/`WARNING_FG`/`MUTED_FG` in `explorer.py` — same hex colors as
   the mockup's badge text, sampled from its actual CSS, just flat instead
   of pill-shaped.
3. **The "Session" column is one line**, `"<title>  ·  <sid>.jsonl"`, not the
   mockup's two-line (bold title, gray filename below) layout — a Treeview
   cell can't render two font weights/sizes.

## Module map

| Module | Responsibility |
|---|---|
| `app.py` | `build_app()` — creates the `tb.Window`, DPI awareness, the app-bar strip, a 4-tab `Notebook` (`ExplorerView`, `CacheView`, `IndexView`, `SettingsView`), a bottom status bar (scan stats left, backup policy right — `ExplorerView` updates the left `StringVar` after every scan), `Dispatcher`, lazy-scans a tab the first time it's selected, starts `pump_forever`. `run()` calls `.mainloop()`. |
| `dispatch.py` | `Dispatcher` (thread-safe callable queue), `pump_forever(root, dispatcher)` (drains it on a `root.after` tick), `run_in_background(dispatcher, work, on_done, on_error)`. |
| `state.py` | `AppState` — loads `ClaudePaths`/`Settings` once at startup; `new_detector()` builds a fresh `ActivityDetector` (call this, don't cache a detector across a scan — state can go stale). No Tk import; stays reusable if the UI changes again. |
| `widgets.py` | `CheckTreeview` — the one checkbox-in-a-datatable widget shared by Explorer's session list, Cache, Index, and the delete-flow preview dialog. Built on `ttkbootstrap.Tableview` (see below), not a bare `ttk.Treeview`. |
| `explorer.py` | `ExplorerView` — master-detail project/session browser. Left: plain `ttk.Treeview` project tree with a search filter and native parent/child nesting for worktrees (kept as a real `ttk.Treeview`, not `CheckTreeview` — `Tableview` has no hierarchy concept, and this is the one place that genuinely needs one). Right: risk-filter chips, action row, and a `CheckTreeview` session list with a real message count (`SessionBundle.message_count`) and relative last-write time (`_relative_time`). |
| `other_views.py` | `CacheView` (`CheckTreeview` with file count + share-of-total %), `IndexView` (orphaned `sessions/<pid>.json` — single-selection by design, see below; shows `procStart` and a specific GONE-vs-REUSED reason via `ActivityDetector.orphan_state()`), `SettingsView` (two-column layout matching the mockup; the theme `Combobox` is display-only — live theme switching stayed out of the MVP, see the migration plan's question 5). |
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

Built on `ttkbootstrap.Tableview` — a real datatable (click-column-header
sort, optional search box, striping that survives a re-sort) — not a bare
`ttk.Treeview`, but `Tableview` has **no native checkbox column**, so this
fakes one exactly like the pre-Tableview version did: a Unicode glyph (☐/☑)
in a dedicated first column, toggled by clicking that column or pressing
Space on a selection. This works because `Tableview` is itself built on a
plain `ttk.Treeview` internally (its public `.view` attribute) — `.tree` on
`CheckTreeview` is an alias for that, kept so code that reaches into it
directly (`selectmode`, extra bindings) didn't need to change.

**Never write a checked glyph via `self.tree.item(iid, values=...)`
directly.** `Tableview`'s `TableRow` caches its own `.values` in Python and
stamps them back onto the live `Treeview` the next time anything calls
`row.refresh()` (a search, a filter, a reload) — a raw `.item()` write
would get silently reverted later. Always go through `TableRow.values = [...]`
(see `CheckTreeview._set_checked`), which updates the cache *and* refreshes
the widget in one call. This was verified empirically, not assumed — see the
commit that switched `widgets.py` from `ttk.Treeview` to `Tableview`.

Because `insert_row()` defaults to `reload=False` (inserting one-by-one with
Tableview's own `reload=True` default would re-layout the whole table after
*every single row*), every caller must call **`render()` once** after its
insert loop — `ExplorerView._render_sessions`, `CacheView._apply`,
`IndexView._apply`, and `delete_flow.run_delete_flow`'s `confirm_tree` all do
this; don't add a new insert loop that forgets it (rows silently won't show).

There is intentionally **no built-in "check all" affordance** (no header-click
handler) — a caller wires `check_all()` to an explicit button only where a
bulk shortcut is wanted. `IndexView` doesn't wire one at all, and in fact uses
`show_checkboxes=False` (plain single-selection, `LOCKED` glyph reserved for
individually non-checkable rows within a checkbox-enabled widget — see
Explorer's `ACTIVE` sessions) rather than checkboxes, specifically so a
`_delete` action can never fire `run_delete_flow` for several orphan entries
at once — stacking multiple modal `Toplevel`s that way is broken (only the
most recent grab is interactive) and contradicts roadmap decision 6.5 ("each
orphan file confirmed individually").

## UI conventions

- User-facing strings are Vietnamese; keep new ones consistent with the
  existing tone (short, imperative for actions, e.g. "Xoá đã chọn").
- Risk colors are `DANGER_FG`/`WARNING_FG`/`MUTED_FG` in `explorer.py`,
  sampled from the mockup's actual badge CSS — reuse these constants, don't
  invent a parallel palette. `CheckTreeview` itself sets no color/heading
  bootstyle (plain, neutral heading, no zebra) — that's a deliberate match to
  the mockup, not an oversight; don't re-add `bootstyle="primary"` or a
  `stripecolor` default.
- Every view exposes a `rescan()` method; `app.py` calls it lazily the first
  time a tab is selected, and `delete_flow` calls it again via `on_done` after
  any successful delete, so the list never shows a session that was just
  removed. `SettingsView.rescan()` is a no-op (nothing to reload from disk).
