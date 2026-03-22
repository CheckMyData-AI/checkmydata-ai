# Agent Backlog

Prioritized list of improvements discovered by the continuous improvement agent.

## Scoring

Priority = Impact + Vision Alignment + Reliability Gain + Speed Gain - Complexity - Risk

---

## Critical Bugs

_None found this cycle._

---

## Core Flow Issues

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 1 | Stale venv shebangs | Backend venv created under old project path; CLI tools fail directly | Dev workflow friction — must use `python -m` prefix | Recreate venv or run `make setup-backend` | P1 | Low |

---

## Reliability

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 2 | Test coverage at 68.78% | Below 80% target; Sprint 1 services have thin coverage | Reduced confidence in new features; regressions may slip through | Add tests for batch_service (46%), code_db_sync_service (55%), project_overview_service (67%) | P1 | High |
| 3 | Missing google-auth in local venv | Dependency declared but not installed | 3 unit tests fail locally (CI installs fresh so CI passes) | Resolved: installed google-auth | P0 (resolved) | Trivial |

---

## UX Improvements

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 4 | PopoverPortal refactoring | Sidebar popovers clipped by overflow-hidden | Users couldn't see full notification/account menus | Resolved: portal-based rendering (commit 7dd1971) | P1 (resolved) | Low |

---

## Documentation

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 5 | BACKLOG.md / ROADMAP.md drift | Sprint 1 completion not reflected in tracking docs | Confusing project state for contributors | Resolved: synced both files | P0 (resolved) | Trivial |

---

## Security

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 6 | Plaintext credentials in notes.md | SSH key, DB password, server IP in plaintext file | Potential credential exposure if file shared | Already gitignored. User should rotate credentials. | P2 | Trivial |

---

## Performance

_No performance issues discovered this cycle. Needs browser-based profiling in next cycle._

---

## Tech Debt

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 7 | README.md is 3600+ lines | Single massive README hard to navigate | Contributor friction, hard to find information | Consider splitting into focused topic docs | P3 | Medium |
| 8 | CI coverage threshold at 68% | Threshold below the stated 80% target | Low bar allows coverage regression | Incrementally raise threshold as coverage improves | P2 | Trivial |
