# CLAUDE.md — claude_tidy/

Scope-specific guidance for this package. Falls back to the
[root CLAUDE.md](../CLAUDE.md) — read its "Safety-critical rules" section
first, it applies to everything under here.

## Layout

- `core/` — filesystem scanning, activity detection, risk classification,
  backup, and the single deletion pipeline. No UI framework import belongs
  in this package; it must stay unit-testable without a GUI. See
  [core/CLAUDE.md](core/CLAUDE.md).
- `webui/` — pywebview + HTML/Bootstrap 5, the UI. See
  [webui/CLAUDE.md](webui/CLAUDE.md).
- `__main__.py` — `python -m claude_tidy` entry point; wires logging and
  calls `webui.app.run()`.

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
- The UI went through two rewrites in one day (2026-09-25): Flet →
  ttkbootstrap ([plans/2026-09-25-ttkbootstrap-ui-migration-planning.md](../plans/2026-09-25-ttkbootstrap-ui-migration-planning.md),
  now superseded) → pywebview
  ([plans/2026-09-25-pywebview-ui-migration-planning.md](../plans/2026-09-25-pywebview-ui-migration-planning.md),
  current). `claude_tidy/ui/` (ttkbootstrap) was deleted outright in task T40
  once `webui/` reached parity — this repo keeps exactly one UI at a time
  (root CLAUDE.md rule: one deletion pipeline, one UI), never two in
  parallel long-term.
