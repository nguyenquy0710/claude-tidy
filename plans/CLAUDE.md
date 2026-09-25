# CLAUDE.md — plans/

Scope-specific guidance for this directory. Falls back to the [root CLAUDE.md](../CLAUDE.md)
for anything not covered here.

## Purpose

Execution plans and work logs — written before starting non-trivial work (to
lay out strategy/roadmap) or after finishing it (as a decision/rationale log).
Use the `nqdev-write-plan` skill to create these rather than writing them
free-hand, so format stays consistent.

## Conventions (established by the existing plan)

- Filename: `YYYY-MM-DD-short-slug.md`.
- Frontmatter: `type`, `complexity`, `status`, `related_issues`,
  `related_prs`, `estimated_hours` — keep `status` current
  (`planning` → `in-progress` → `done`) as work progresses rather than only
  setting it once.
- Body sections: Phân tích/Bối cảnh, Approach/Strategy, Công việc cần thực
  hiện (Todo, as checkboxes with task IDs like `T01`), Risks & Unknowns,
  Success Criteria, Questions/Dependencies.
- Effort is tracked in person-days per task, with a "Gốc" (original) vs.
  "Điều chỉnh" (adjusted) column when re-estimating after new findings —
  don't silently overwrite the original estimate.
- Task IDs (`T01`, `T02`, ...) are referenced elsewhere (e.g. root
  `CLAUDE.md`'s safety rules reference `T10`/`T12`) — keep them stable once
  assigned; don't renumber tasks across revisions.
- Open product decisions belong in a "Questions / Dependencies" section with
  an explicit recommendation, not left implicit — see §6 of the current
  roadmap for the pattern.
