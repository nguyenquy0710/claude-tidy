# CLAUDE.md — docs/

Scope-specific guidance for this directory. Falls back to the [root CLAUDE.md](../CLAUDE.md)
for anything not covered here.

## Purpose

Product/design documentation — specs, idea write-ups, architecture rationale.
Currently: `claude-tidy-plan.md`, the current product spec (ttkbootstrap +
PyInstaller). It's a rename of the original `claude-session-cleaner-idea.md`
(the Flet-based spec `plans/2026-09-25-session-cleaner-mvp-roadmap.md` was
derived from) — that filename doesn't exist on disk anymore; find its old
content with `git log --follow -- docs/claude-tidy-plan.md`, not by looking
for the old path.

## Conventions

- Written in Vietnamese, matching the existing doc — keep new docs in the same
  language unless the user asks otherwise.
- Structure mirrors `claude-tidy-plan.md`: numbered sections
  (bối cảnh & mục tiêu, tech stack, UI, pipeline, module breakdown, risks,
  open questions). Keep an explicit "open questions" section — this project
  has real unresolved product decisions (see root CLAUDE.md's safety rules,
  item 8) and burying them in prose loses them.
- When a decision here is later confirmed or overturned in `plans/`, update
  this doc rather than leaving two sources of truth that disagree — the
  `plans/` roadmap already tracks a "Phát hiện" (findings) table for exactly
  this kind of drift between the original idea and reality.
- Don't duplicate the task breakdown / effort estimates here — that belongs
  in `plans/`, not `docs/`.
