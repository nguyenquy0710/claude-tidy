# CLAUDE.md — claude_tidy/

Scope-specific guidance for this package. Falls back to the
[root CLAUDE.md](../CLAUDE.md) — read its "Safety-critical rules" section
first, it applies to everything under here.

## Layout

- `core/` — filesystem scanning, activity detection, risk classification,
  backup, and the single deletion pipeline. No `tkinter`/`ttkbootstrap` import
  belongs in this package; it must stay unit-testable without a GUI. See
  [core/CLAUDE.md](core/CLAUDE.md).
- `ui/` — ttkbootstrap views and the one delete-flow entry point. See [ui/CLAUDE.md](ui/CLAUDE.md).
- `__main__.py` — `python -m claude_tidy` entry point; just wires logging and
  calls `ui.app.run()`.

## Cross-cutting conventions

- `from __future__ import annotations` at the top of every module.
- Dataclasses (`core/models.py`) and `StrEnum` for the shared vocabulary
  (`Activity`, `RiskLevel`, `TargetKind`, `PlanMode`) — both layers import
  from `core.models`, never redefine their own parallel types.
- Anything in `core/` that talks to the OS (process info, disk usage) is
  reached through a small `Protocol` so tests can substitute a fake — see
  `ProcessProbe` in `core/activity.py` for the pattern to copy.
- Vietnamese is the UI's user-facing language (labels, dialogs, status text)
  — keep new UI strings in Vietnamese to match the existing views. Code
  identifiers, docstrings, and comments stay in English.
- `ui/` was rewritten from Flet to ttkbootstrap on 2026-09-25 — see
  [plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](../plans/2026-09-25-ttkbootstrap-ui-migration-planning.md).
  If you find a stray `flet` import or reference, it's a leftover to remove,
  not a second UI to maintain (root CLAUDE.md rule: one deletion pipeline,
  one UI).
