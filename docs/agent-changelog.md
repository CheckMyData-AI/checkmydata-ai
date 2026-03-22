# Agent Changelog

Changes made by the continuous improvement agent.

---

## Cycle 1 — 2026-03-22

### Fixed

- **Missing `google-auth` dependency in local venv** — Installed `google-auth>=2.0.0` (declared in `pyproject.toml` but absent from `.venv`). Fixes 3 failing unit tests in `TestVerifyGoogleToken`.

### Documentation

- **BACKLOG.md** — Updated Sprint 1 table: tasks 6-10 changed from `pending` to `done`. Updated header from "Sprint 1 — Active" to "Sprint 1 — Complete". Populated Completed section with all 10 tasks and completion dates.
- **ROADMAP.md** — Checked all Sprint 1 items under "AI Chief Data Brain" as complete (`[x]`). Updated section header to "Sprint 1 Complete".

### Infrastructure

- **Created `/docs/` agent tracking directory** with:
  - `agent-status.md` — cycle state and health summary
  - `agent-backlog.md` — prioritized improvement backlog
  - `agent-findings.md` — discoveries and analysis
  - `agent-changelog.md` — this file
  - `agent-test-matrix.md` — core flow verification matrix
