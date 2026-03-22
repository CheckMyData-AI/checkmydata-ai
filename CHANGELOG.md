# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Open-source repository documentation (CONTRIBUTING, ARCHITECTURE, API, etc.)
- GitHub issue templates and PR template
- MIT License
- **Foundation Layer: Data Graph** — unified metrics registry with auto-discovery from DB index, relationship mapping, and graph queries (`/api/data-graph/`)
- **Foundation Layer: Insight Memory** — persistent store for discovered findings with lifecycle management (active → confirmed/dismissed/resolved), deduplication, and confidence decay (`/api/insights/`)
- **Foundation Layer: Trust Layer** — confidence scoring, provenance tracking, and freshness labels for every insight (`TrustService`, `TrustedInsight`)
- New models: `MetricDefinition`, `MetricRelationship`, `InsightRecord`, `TrustScore`
- Frontend `InsightFeedPanel` component with severity filtering, confidence badges, and insight lifecycle actions (confirm/dismiss/resolve/investigate)
- **Autonomous Insight Feed Agent** — proactive data source scanning, auto-discovers trends/outliers/patterns from DB index, LLM-powered deep analysis, stores findings in Memory Layer (`InsightFeedAgent`, `/api/feed/`)
- **Anomaly Intelligence Engine** — upgrades `DataSanityChecker` with root cause analysis, business impact scoring, severity classification, recommended actions, and confidence. Replaces basic warning text with rich `AnomalyReport` objects (`AnomalyIntelligenceEngine`, `AnomalyReportCard`)
- New API endpoints: `POST /api/data-validation/anomaly-analysis` (ad-hoc analysis), `POST /api/data-validation/anomaly-scan/{connection_id}` (table-level scan)
- SQL Agent now automatically stores critical/warning anomalies as insight records in Memory Layer
- Probe Service enriched with anomaly intelligence reports per table
- Frontend `AnomalyReportCard` component with expandable root cause, impact, and action details
- **Opportunity Detector** — finds high-performing segments, conversion gaps, undermonetized users, and growth-potential channels with impact estimates (`OpportunityDetector`, `OpportunityCard`)
- New API endpoint: `POST /api/feed/{project_id}/opportunities/{connection_id}` (opportunity scan with auto-store to insights)
- **Loss Detector** — finds revenue leaks, funnel drop-offs, spend inefficiency, declining trends, and high-churn segments with monetary quantification (`LossDetector`, `LossReportCard`)
- New API endpoint: `POST /api/feed/{project_id}/losses/{connection_id}` (loss scan with auto-store to insights)
- **Insight → Action Engine** — transforms every insight (anomaly, opportunity, loss) into a concrete recommended action with expected impact %, priority, effort, prerequisites, and risks (`ActionEngine`, `ActionRecommendation`, `ActionCard`)
- **Cross-Source Reconciliation Engine** — compares data between two connections: row counts, aggregate values, schemas, and key overlap. Detects missing records, value mismatches, schema divergence. Stores critical discrepancies as insights. (`ReconciliationEngine`, `ReconciliationCard`, `/api/reconciliation/`)
- New API endpoint: `GET /api/insights/{project_id}/actions` (generate prioritized action recommendations from active insights)
- BACKLOG.md for iterative development tracking

## [0.10.0] - 2026-03-22

### Security
- Path traversal protection via `validate_safe_id` on filesystem-facing params
- Project creation uniqueness check (owner_id + name) returns 409 on duplicates
- Audit logging on auth routes, repo mutations, and data validation
- SQL identifier quoting in probe_service to prevent injection
- Rate limiting on all mutating endpoints
- Security headers middleware (X-Content-Type-Options, X-Frame-Options, etc.)
- Command injection fix in subprocess calls
- Input validation with Pydantic Literal types across all routes

### Fixed
- VectorStore shutdown cleanup (close ChromaDB client)
- Stale git lock file cleanup on app shutdown
- Silent exception handling replaced with proper logging across 15+ locations
- Race condition in VectorStore collection access (threading.Lock)
- Invite acceptance atomicity with begin_nested transaction
- MongoDB connection timeout configuration
- N+1 queries in project_overview_service and batch_service
- Frontend unmounted setState guards on 18+ components
- Silent .catch blocks replaced with toast notifications

### Added
- Configurable timeouts: model_cache_ttl, health_degraded_latency, ssh_connect/command
- Database pool_timeout configuration
- Pagination on list_repositories endpoint
- aria-live regions for streaming chat and batch progress
- Cmd/Ctrl+K keyboard shortcut to focus chat input
- React.memo + useCallback optimization on ChatSessionList
- DataTable row cap (500) with "show all" toggle
- LearningsPanel item cap (200)
- DataValidationCard maxLength + aria-label on inputs
- Accessibility: skip-to-content, focus traps, keyboard navigation

### Changed
- Background task error logging via add_done_callback
- Moved hardcoded timeouts to centralized config

## [0.1.0] - 2026-03-15

### Added
- Initial release
- Multi-agent chat system (Orchestrator, SQL, Knowledge, Viz agents)
- Database connectors (PostgreSQL, MySQL, ClickHouse, MongoDB)
- SSH tunnel support
- Git repository indexing with ChromaDB RAG
- Natural language to SQL translation
- Automatic visualization (tables, charts)
- Batch query execution
- Dashboard creation
- Custom validation rules
- Team collaboration with invitations
- Google OAuth integration
- Onboarding wizard
- Demo project setup
