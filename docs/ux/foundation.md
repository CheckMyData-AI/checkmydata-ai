# UX Foundation

<!-- Managed with super-ux. Records the standing UX decisions that apply across every
     feature, so they are not re-litigated per run. -->

## Design tooling

**This project designs text-only. There are no Figma frames, and none are expected.**

- `docs/ux/scenarios.md` is the **source of truth** for all user-facing behavior.
  A scenario — persona, entry point, preconditions, steps, expected result, UI
  elements, states, errors & recovery — is the design deliverable. If a behavior is
  not in `scenarios.md`, it is not designed yet.
- The visual layer is already fixed by `DESIGN_SYSTEM.md` (semantic tokens from
  `@theme` in `frontend/src/app/globals.css`, DM Sans / JetBrains Mono, the
  `components/ui/Icon.tsx` `PATHS` record, the single `max-width: 767px` breakpoint,
  ≥44 px touch targets). New surfaces **extend already-designed components**; they do
  not introduce a new visual language, so there is nothing a mockup would decide that
  the design system has not already decided.
- Therefore: **do not ask which Figma file or team to use, and do not create one.**
  Do not open a design tool to specify a screen. Write or update the scenario, then
  build against `DESIGN_SYSTEM.md`.
- Where a layout genuinely needs to be shown rather than described, use ASCII/markdown
  sketches inside the scenario or the module spec — kept in-repo, diffable, and
  reviewable in the same change as the code.

Decision reference: `docs/superpowers/specs/2026-08-01-analytics-sources-brief.md` →
Decisions locked, **D9 (Design surface = text-only)**.

## Working rules

- Any change to user-facing behavior updates `docs/ux/scenarios.md` **in the same
  change** — new scenarios, adjusted steps, status and coverage.
- Any new feature **starts** with scenarios: draft them, check them against the
  existing base for conflicts, overlaps and gaps, get them approved, then build.
- `backend/tests/unit/docs/test_ux_scenarios.py` enforces the mechanical part of the
  format: every `### SCN-nnn` body has exactly one Index row and vice versa, IDs are
  unique, and `Coverage:` paths on new scenarios resolve on disk.
- Scenario IDs are **allocated from the end of the file** and are never reused. Check
  the highest existing ID in the Index before assigning; a spec that names IDs is a
  proposal, not a reservation.
