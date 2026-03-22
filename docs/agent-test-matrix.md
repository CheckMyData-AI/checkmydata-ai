# Agent Test Matrix

Core user flow verification status. Updated each improvement cycle.

---

## Last Updated: 2026-03-22 (Cycle 3)

## Automated Test Coverage

| Flow | Unit Tests | Integration Tests | Coverage | Status |
|------|-----------|-------------------|----------|--------|
| Authentication (register/login) | 35+ | 15+ | 92% | PASS |
| Google OAuth | 3 | — | 92% | PASS (fixed missing dep) |
| Project CRUD | 10+ | 8+ | 90% | PASS |
| Connection CRUD | 44 | 12+ | 99% | PASS |
| SSH Key Management | 10+ | 5+ | 78% | PASS |
| Chat / Orchestrator | 20+ | — | ~70% | PASS |
| SQL Agent | 15+ | — | ~65% | PASS |
| Knowledge / RAG | 10+ | — | ~60% | PASS |
| Batch Queries | 21 | — | 100% | PASS |
| Data Validation | 10+ | 5+ | 100% (service) | PASS |
| Scheduling | 10+ | — | 100% (service) | PASS |
| Rules | 5+ | — | 100% (service) | PASS |
| Notes | 5+ | — | 100% (service) | PASS |
| Dashboards | 5+ | — | 100% (service) | PASS |
| Invites / Members | 10+ | — | 90% | PASS |
| Insights / Memory | 5+ | 3+ | ~70% | PASS |
| Data Graph | 5+ | 2+ | ~65% | PASS |
| Reconciliation | 3+ | 2+ | ~60% | PASS |
| Semantic Layer | 3+ | 2+ | ~60% | PASS |
| Exploration | 3+ | 2+ | ~60% | PASS |
| Temporal Intelligence | 3+ | 2+ | ~60% | PASS |
| Project Overview | 38 | — | 93% | PASS |
| Viz (chart/table/text/export) | 54 | — | 88-100% | PASS |

## Frontend Component Tests

| Component | Tests | Status |
|-----------|-------|--------|
| AuthGate | 5+ | PASS |
| AccountMenu | 3+ | PASS |
| ChatPanel | 5+ | PASS |
| ChatInput | 3+ | PASS |
| ChatMessage | 3+ | PASS |
| ChatSessionList | 3+ | PASS |
| ConnectionSelector | 3+ | PASS |
| ProjectSelector | 3+ | PASS |
| OnboardingWizard | 3+ | PASS |
| BatchRunner | 3+ | PASS |
| DashboardList | 3+ | PASS |
| DataTable | 3+ | PASS |
| ChartRenderer | 3+ | PASS |
| VizRenderer | 3+ | PASS |
| NotificationBell | 3+ | PASS |
| RulesManager | 3+ | PASS |
| ScheduleManager | 3+ | PASS |
| SshKeyManager | 3+ | PASS |
| ErrorBoundary | 3+ | PASS |
| Sidebar | 3+ | PASS |

## Manual Verification (Not Yet Performed)

| Flow | Steps | Status |
|------|-------|--------|
| End-to-end onboarding | Register -> Wizard -> Connect DB -> Index -> Chat | NOT TESTED |
| Chat with real database | Ask natural language question -> Get SQL + results | NOT TESTED |
| Insight feed scan | Trigger feed scan -> View insights -> Confirm/dismiss | NOT TESTED |
| Dashboard creation | Save query -> Build dashboard -> View | NOT TESTED |
| Mobile responsiveness | All core flows on mobile viewport | NOT TESTED |
| Error states | Network errors, auth expiry, connection failures | NOT TESTED |

## Coverage Improvement Targets (Next Cycle)

| Service | Current | Target | Gap |
|---------|---------|--------|-----|
| connection_service.py | 99% | — | Done |
| project_overview_service.py | 93% | — | Done |
| batch_service.py | 100% | — | Done |
| code_db_sync_service.py | 93% | — | Done |
| viz/export.py | 100% | — | Done |
| viz/utils.py | 100% | — | Done |
| agent_learning_service.py | 66% | 80% | +14% |
| benchmark_service.py | 66% | 80% | +14% |
| db_index_service.py | 69% | 80% | +11% |
