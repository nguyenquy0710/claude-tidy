# CLAUDE.md — docs/

Scope-specific guidance for this directory. Falls back to the [root CLAUDE.md](../CLAUDE.md)
for anything not covered here.

## Purpose

Product/design documentation — specs, idea write-ups, architecture rationale.
Currently: `claude-tidy-plan.md`, the current product spec (pywebview +
Bootstrap 5, PyInstaller `--onedir`). It's a rename of the original
`claude-session-cleaner-idea.md` (the Flet-based spec
`plans/2026-09-25-session-cleaner-mvp-roadmap.md` was derived from) — that
filename doesn't exist on disk anymore; find its old content, and the
intermediate ttkbootstrap-era version, with
`git log --follow -- docs/claude-tidy-plan.md`, not by looking for an old path.

Also here: `claude-tidy — UI.html`, a bundler-exported prototype (not
reusable source — see root `CLAUDE.md`'s repo-layout note).

## Conventions

- Written in Vietnamese, matching the existing doc — keep new docs in the same
  language unless the user asks otherwise.
- Structure mirrors `claude-tidy-plan.md`: numbered sections
  (bối cảnh & mục tiêu, tech stack, UI, pipeline, module breakdown, risks,
  open questions). Keep an explicit "open questions" section even once every
  current question is resolved — this project has repeatedly reopened
  supposedly-settled decisions when a spec got rewritten wholesale (see the
  E1–E6 table in `plans/2026-09-25-pywebview-ui-migration-planning.md` §1.3,
  where a new draft silently reverted six already-implemented decisions); an
  explicit section makes that kind of regression visible instead of buried in
  prose.
- When a decision here is later confirmed or overturned in `plans/`, update
  this doc rather than leaving two sources of truth that disagree — the
  `plans/` roadmap already tracks a "Phát hiện" (findings) table for exactly
  this kind of drift between the original idea and reality.
- Don't duplicate the task breakdown / effort estimates here — that belongs
  in `plans/`, not `docs/`.
