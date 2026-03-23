# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- CI coverage threshold raised from 69% to 72%
- **Chat feedback redesign** — Removed quick-action chips, FollowupChips, DataValidationCard, and WrongDataModal from chat messages. Thumbs up/down now record data validation and thumbs down auto-triggers agent investigation in chat
- **Sidebar "+New" redesign** — Moved all "+New" buttons from section content into section header "+" icons that appear only when expanded. Applies to Projects, Connections, Chat History, Rules, Schedules, and Dashboards

### Security
- **KnowledgeAgent cache isolation** — Fixed critical cross-project data leakage where cached knowledge could bleed between projects (single-slot cache → dict keyed by project_id)
- **MCP connection IDOR** — Added project ownership check before using MCP connections in orchestrator
- **SafetyGuard on diagnostic queries** — Investigation agent `run_diagnostic_query` now validates SQL through SafetyGuard before execution
- **SafetyGuard on schedule run-now** — Manual schedule execution now applies the same safety checks as the cron scheduler
- **Rate limiting** — Added rate limits to `/visualizations/render`, `/exploration`, `/semantic-layer`, `/reconciliation`, `/temporal` endpoints

### Fixed
- **Connector disconnect safety** — All 6 connectors (postgres, mysql, mongodb, clickhouse, mcp, ssh_exec) now use try/finally in disconnect() to always clear handles even when teardown throws
- **Keyboard shortcut conflict** — Removed duplicate Cmd/Ctrl+K handler from ChatInput; ChatSearch now exclusively owns the shortcut
- **localStorage quota safety** — Wrapped localStorage.setItem calls in auth-store and app-store with try/catch to handle QuotaExceededError gracefully
- **useRestoreState race** — Added cancellation flag to prevent stale async restore results from overwriting store after unmount or auth change
- **ProjectSelector race** — Added sequence counter to discard out-of-order API responses when rapidly switching projects
- **Health endpoint depth** — /api/health now verifies DB connectivity (SELECT 1), returns 503 when database is unreachable
- **Graceful shutdown** — Indexing and sync background tasks from connections/repos routes are now cancelled during shutdown
- **seedActiveTasks race** — useGlobalEvents seedActiveTasks now checks active flag before writing to store, preventing stale seed after disconnect
- Recreated backend venv to fix stale shebangs from old project path
- **InsightFeedPanel** now shows "Couldn't load insights" with Retry when API fails (previously showed misleading empty state)
- **DashboardList** now shows "Couldn't load dashboards" with Retry when API fails (previously showed misleading empty state)
- **ConnectionSelector** now shows "No connections yet" empty state when no connections exist
- **VizRenderer** now shows "Visualization data unavailable" instead of rendering nothing when payload is missing
- **SSE stream completion guard** — Chat stream now fires `onError` if server ends without result/error event, preventing stuck loading state
- **DataValidationCard** — Removed premature optimistic `setVerdict` before API confirmation; UI only updates on success
- **AccountMenu** — Added Escape key handler for keyboard dismissal
- **RetryStrategy** — Fixed empty repair hints when COLUMN_NOT_FOUND has no suggested columns
- **Sidebar callbacks** — Replaced 11 inline lambdas with stable useCallback refs to prevent unnecessary child effect re-runs
- **Notes store** — `loadNotes` failure now shows toast error instead of silent empty state
- **Silent exceptions** — Added debug logging to 10+ previously silent `except: pass` blocks across chat, connectors, and agent modules
- **Accessibility** — Added dialog semantics to BatchRunner, aria-labels to icon-only buttons and form inputs across 6 components
- **Performance** — Narrowed Zustand selectors in 17+ components to prevent full-store re-renders
- **test_alembic.py** — use `sys.executable -m alembic` instead of bare `alembic` CLI to avoid picking up system Python outside venv

### Tests
- batch_service.py: 46% -> 100% coverage (9 new tests for execute_batch)
- code_db_sync_service.py: 55% -> 93% coverage (39 new tests — CRUD, status helpers, runtime enrichment, formatting)
- connection_service.py: 69% -> 99% coverage (20 new tests — test_ssh full flow, to_config error paths, update extended fields, pagination)
- project_overview_service.py: 67% -> 93% coverage (24 new tests — save_overview, _split_overview_sections, _hash_section, notes section, edge cases)
- viz/export.py: 68% -> 100% (xlsx export test), viz/utils.py: 83% -> 100% (serialize_value edge cases)
- agent_learning_service.py: 66% -> 87% (53 new tests — CRUD, fuzzy dedup, decay, compile_prompt, priority score)
- benchmark_service.py: 66% -> 100% (24 new tests — find/create/confirm/flag_stale, normalize, edge cases)
- db_index_service.py: 69% -> 100% (48 new tests — upsert, delete, index_age, is_stale, indexing_status, detail edge cases)
- Overall backend coverage: 68.78% -> 72.63%

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
- **Semantic Layer Auto-Build** — auto-discovers metrics from DB index entries, infers aggregation (SUM/COUNT/AVG), units, and categories, normalizes across connections via canonical name mapping (70+ business metric aliases), and links equivalent metrics in the Data Graph. Browsable metric catalog with search and category filters. (`SemanticLayerService`, `MetricCatalogPanel`, `/api/semantic-layer/`)
- **Query-less Exploration** — autonomous investigation engine: user says "What's wrong?" and the system scans insights, anomalies, opportunities, losses, reconciliation discrepancies, and data health to compile a prioritized investigation report with findings sorted by severity. (`ExplorationEngine`, `ExplorationReport`, `POST /api/explore/`)
- **Temporal Intelligence Engine** — pure-Python time series analysis: linear trend detection with R² fit quality, seasonality detection via autocorrelation on detrended data (weekly/monthly/quarterly/yearly), temporal anomaly detection adjusted for trend, and cross-series lag/lead detection via cross-correlation. (`TemporalIntelligenceService`, `TemporalReport`, `/api/temporal/`)
- New API endpoint: `GET /api/insights/{project_id}/actions` (generate prioritized action recommendations from active insights)
- BACKLOG.md for iterative development tracking

### Fixed
- **Sidebar popup overflow** — NotificationBell dropdown, AccountMenu, and Tooltip now render via React portals (`PopoverPortal`) to escape sidebar `overflow-hidden`, preventing clipping on desktop collapsed/expanded states
- **Charts missing in Saved Queries** — NoteCard now renders `VizRenderer` (bar/line/pie/scatter charts) from `visualization_json` in a collapsible "Chart" section
- **Refresh-to-chat** — Clicking "Refresh" on a saved query now posts the refreshed result as a message in the currently active chat session (with `[Refreshed]` prefix)
- **Critical: Router prefix duplication** — Sprint 1 routes (reconciliation, semantic-layer, explore, temporal) had double-prefixed paths (e.g. `/api/reconciliation/reconciliation/...`) causing 404s from frontend. Removed redundant router-level prefix.
- **Security: Cross-project insight access** — confirm/dismiss/resolve insight endpoints now verify the insight belongs to the target project before mutation, preventing cross-project data manipulation.
- **Feed API empty responses** — `scan_opportunities` and `scan_losses` now return `insights_stored: 0` when no DB entries exist, matching frontend DTO expectations.
- **Next.js viewport metadata deprecation** — moved `themeColor` and `viewport` from `metadata` export to proper `viewport` export per Next.js 15 API, eliminating build warnings.
- **Float conversion safety** — added `_safe_float` utility in action_engine and exploration_engine to handle `None`, non-numeric, and string confidence values without crashing.
- **Reconciliation schema handling** — `reconcile_schemas` now handles `None` column lists gracefully with `set(schema.get(table) or [])`.
- **Feed HTTPException consistency** — replaced inline `from fastapi import HTTPException` with top-level import and keyword args for consistency.

### Changed
- Test coverage increased from 68.90% to 71.03%
- Added integration tests for Sprint 1 route path reachability (reconciliation, semantic-layer, explore, temporal)
- Added integration test for cross-project insight access prevention
- Added unit tests for `_safe_float` edge cases and `None`/non-numeric confidence handling

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
