# CLAUDE.md — claude_tidy/webui/static/

Scope-specific guidance for the frontend (HTML/JS/CSS). Falls back to
[claude_tidy/webui/CLAUDE.md](../CLAUDE.md) (the Python ↔ JS trust boundary —
read it first, none of that is re-litigated here) and the
[root CLAUDE.md](../../../CLAUDE.md) for anything not covered.

## Files

| File | Role |
|---|---|
| `index.html` | Bootstrap 5 markup, the 4 tabs (Sessions/Cache/Index/Settings) and the shared delete-flow modals. |
| `app.js` | Alpine.js `app()` component — all client-side state and the `window.pywebview.api.*` calls into `webui/api.py`. |
| `app.css` | Small addenda on top of Bootstrap utilities (e.g. `.ct-badge-danger/warning/safe` risk pills). |
| `vendor/` | Bootstrap 5 + Alpine.js, downloaded and committed as static files — never fetched from a CDN, because the app must run fully offline and package with PyInstaller. |

## Alpine + Bootstrap gotcha: `x-show` vs. `!important` display utilities

**`x-show` combined with a Bootstrap `!important` display utility (`.d-flex`,
`.d-none`, `.d-block`, `.d-grid`) on the *same element* silently breaks.**
Bootstrap's utility sets `display: X !important`, which beats Alpine's plain
(non-`!important`) inline `display: none` — the element never actually
hides, even though the DOM's internal state looks correct on inspection. Use
the `x-show.important` modifier on any element that also carries one of
those classes. Two real instances of this shipped and were only caught by
Playwright screenshot verification, not by reading the code: the
Sessions-tab wrapper and the Claude-Desktop-running alert in Cache/Temp —
see both in `index.html`.

## Project sidebar context menu

The right-click context menu (`app.js`'s `projectMenu` state —
`openProjectMenu`/`openProjectFolder`/`copyProjectPath`/`rescanProjectMenu`/
`deleteAllProjectMenu`) is plain Alpine state, not a Bootstrap component — it
is positioned at the click coordinates and closed by setting
`projectMenu = null`. `rescanProjectMenu` patches just the one changed
project back into `projects`/`worktrees` in place (`replaceProjectEverywhere`)
rather than re-fetching the whole list via `list_projects()`; keep that
patch-in-place pattern for any future per-item refresh instead of a full
re-fetch.

## Selection UX conventions

- Index mồ côi has **no "select all"**, only per-row single selection — a
  deliberate carry-over from the removed ttkbootstrap UI (roadmap decision
  6.5: each orphan file is confirmed individually, never bulk). Don't add a
  bulk-select control here without revisiting that decision explicitly.
- Risk badges are real rounded pills (`.ct-badge-danger/warning/safe` in
  `app.css`), not flat-text — HTML doesn't have the single-color-per-row
  limitation the ttkbootstrap UI had, so don't reintroduce that limitation.

## `vendor/` is hand-updated, not built

There is no npm/webpack step in this project. If you bump Bootstrap or
Alpine, replace the files under `vendor/` directly and re-verify (Playwright
against a stub `window.pywebview.api`, or a real `webview` window — see the
T33 spike pattern in
[plans/2026-09-25-pywebview-ui-migration-planning.md](../../../plans/2026-09-25-pywebview-ui-migration-planning.md)
for how to do the latter without touching a real `~/.claude`).

## Consuming the DTO contract

Every dict `app.js` reads over `window.pywebview.api` is assembled in
`webui/dto.py`, never ad hoc in JS — `app.js` reads dict keys with no other
type checking, so a field renamed on the Python side silently breaks here
with no error. See the DTO contract table in
[claude_tidy/webui/CLAUDE.md](../CLAUDE.md#dto-contract-dtopy) for which
`dto.py` function backs which UI element.

## Language

User-facing strings are Vietnamese, short and imperative for actions (e.g.
"Xoá đã chọn") — matches the removed ttkbootstrap UI's tone. Code
identifiers and comments in `app.js` stay in English.
