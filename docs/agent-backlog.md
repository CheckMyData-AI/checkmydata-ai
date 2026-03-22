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
| 1 | Stale venv shebangs | Backend venv created under old project path; CLI tools fail directly | Dev workflow friction — must use `python -m` prefix | **Resolved: venv recreated (Cycle 2)** | P1 (resolved) | Low |

---

## Reliability

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 2 | Test coverage at 70.03% | Below 80% target; improved from 69.42% | connection_service 69%→99%, project_overview_service 67%→93%, viz 68%→100%. CI threshold raised to 70% | Next: agent_learning_service (66%), benchmark_service (66%), db_index_service (69%) | P1 | High |
| 3 | Missing google-auth in local venv | Dependency declared but not installed | 3 unit tests fail locally (CI installs fresh so CI passes) | Resolved: installed google-auth | P0 (resolved) | Trivial |

---

## UX Improvements

| # | Title | Problem | User Impact | Solution | Priority | Complexity |
|---|-------|---------|-------------|----------|----------|------------|
| 4 | PopoverPortal refactoring | Sidebar popovers clipped by overflow-hidden | Users couldn't see full notification/account menus | Resolved: portal-based rendering (commit 7dd1971) | P1 (resolved) | Low |
| 9 | Misleading empty states on API failure | InsightFeedPanel, DashboardList showed "no data" when API failed | Users thought data was empty when it was a network error | **Resolved (Cycle 3): Added loadError tracking + Retry** | P1 (resolved) | Low |
| 10 | Missing connection list empty state | ConnectionSelector showed nothing when list was empty | No guidance for new users | **Resolved (Cycle 3): Added "No connections yet" text** | P2 (resolved) | Trivial |
| 11 | VizRenderer null for missing payload | Visualization area disappeared with no feedback | Users saw empty space in chat | **Resolved (Cycle 3): Fallback "data unavailable" message** | P2 (resolved) | Trivial |
| 12 | Mobile notes drawer accessibility | Missing Escape key handling, focus trap, aria-modal | Screen reader / keyboard users can't close panel | Needs fix: align with Sidebar mobile drawer pattern | P2 | Low |
| 13 | Suggestion chips missing aria-label | Truncated text not accessible to screen readers | Accessibility gap for SR users | Add aria-label with full text | P3 | Trivial |
| 14 | Insight cards missing aria-expanded | Expandable rows lack expanded/collapsed state for SR | Accessibility gap | Add aria-expanded to toggle button | P3 | Trivial |
| 15 | Mobile layout flash | useMobileLayout defaults to false, causes brief desktop layout on mobile | Visual flash on first paint | Initialize from matchMedia in useState | P3 | Low |

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
| 8 | CI coverage threshold at 70% | Raised from 69% in Cycle 3; still below 80% target | Low bar allows coverage regression | Continue incrementally raising threshold | P2 | Trivial |
