# Backlog — AI Chief Data Brain

> **Vision:** From querying data → to understanding business → to autonomously improving it

**Sprint methodology:** Pick top 10 → design architecture + UX → implement → test → lint → commit → push → verify CI → mark done → next task. After sprint completion, wait for approval, re-prioritize, start next sprint.

---

## Sprint 1 — Complete

| #  | Task | Status | Priority | Dependencies | Est. Complexity |
|----|------|--------|----------|--------------|-----------------|
| 1  | Foundation: Data Graph + Memory + Trust Layers | `done` | P0 | None (prerequisite for all) | High |
| 2  | Autonomous Insight Feed | `done` | P0 | Task 1 | High |
| 3  | Anomaly Intelligence (upgrade) | `done` | P0 | Tasks 1, 2 | Medium |
| 4  | Opportunity Detector | `done` | P0 | Tasks 1, 2 | Medium |
| 5  | Loss Detector | `done` | P0 | Tasks 1, 2 | Medium |
| 6  | Insight → Action Engine | `done` | P0 | Tasks 3, 4, 5 | Medium |
| 7  | Cross-Source Reconciliation Engine | `done` | P1 | Task 1 | High |
| 8  | Semantic Layer Auto-Build | `done` | P1 | Task 1 | High |
| 9  | Query-less Exploration | `done` | P1 | Tasks 1, 2 | Medium |
| 10 | Temporal Intelligence Engine | `done` | P1 | Task 1 | Medium |

---

## Sprint 1 — Task Details

### Task 1: Foundation — Data Graph + Memory + Trust Layers

**Goal:** Build the three core modules that every subsequent feature depends on.

**Data Graph Module**
- Unified registry of metrics, sources, relationships, and dependencies
- Auto-populated from DB index pipeline (extend `probe_service`)
- Models: `MetricDefinition`, `MetricRelationship`, `SourceNode`
- Service: `DataGraphService` — build, query, update, visualize graph
- API: `/api/data-graph/{project_id}` (GET, POST refresh)

**Memory Layer**
- Persistent store for findings: what was discovered, confirmed/rejected, confidence, decay
- Extends existing `AgentLearning` pattern but for insights
- Models: `InsightRecord` (finding, type, confidence, status, source_metrics, timestamps)
- Service: `InsightMemoryService` — store, query, confirm, reject, decay
- Orchestrator integration: check memory before generating new insights
- API: `/api/insights/{project_id}` (GET, PATCH confirm/reject)

**Trust Layer**
- Confidence scoring, source validation, traceability for every insight
- Model: `TrustScore` (insight_id, confidence, sources, validation_method)
- Service: `TrustService` — score calculation, source verification
- Wrapper: `TrustedInsight` dataclass for all agent outputs
- Frontend: confidence badges on insights

**Edge cases:** Empty DB index, single source only, no codebase connected, stale metrics, conflicting relationships, LLM unavailable during graph build.

---

### Task 2: Autonomous Insight Feed

**Goal:** System proactively analyzes data and surfaces insights without user questions.

**Backend:**
- New agent: `InsightFeedAgent` — runs on schedule or on-demand
- Scheduler integration: background task that periodically scans connected sources
- Analysis pipeline: observe metrics → compare to history → detect changes → generate insights
- Store insights in Memory Layer with confidence scores
- Prioritization: critical problems > growth opportunities > informational

**Frontend:**
- New `InsightFeedPanel` component — dedicated feed in sidebar or main area
- Cards: "3 things that changed in 24 hours", "1 critical problem", "2 growth opportunities"
- Real-time updates via SSE
- Dismiss, confirm, drill-down actions

**API:** `/api/feed/{project_id}` (GET latest, POST trigger scan)

**Edge cases:** No data changes in 24h, too many insights (need ranking/dedup), LLM quota limits, user hasn't connected any sources yet, connection down during scan.

---

### Task 3: Anomaly Intelligence (upgrade)

**Goal:** Upgrade `DataSanityChecker` from "something changed" to "why / where / how critical."

**Backend:**
- Extend `DataSanityChecker` → `AnomalyIntelligenceEngine`
- Root cause analysis: when anomaly detected, run follow-up queries to find "why"
- Severity scoring: business impact estimation (revenue, users affected)
- Context enrichment: pull related metrics, similar past events from Memory Layer
- LLM-powered explanation generation

**Frontend:**
- Upgraded anomaly cards with severity indicators, root cause, and suggested actions
- Timeline view of anomalies
- Link anomalies to related insights in the feed

**Edge cases:** Anomaly is just noise (high false positive rate), cascading anomalies from single root cause, insufficient data for root cause analysis.

---

### Task 4: Opportunity Detector

**Goal:** Find segments with high LTV, undermonetized users, channels with potential.

**Backend:**
- New agent: `OpportunityAgent`
- Segment analysis: automatic cohort comparison on key metrics
- Pattern detection: "Users from X convert N% better"
- Gap analysis: where traffic/conversion potential exists
- Store opportunities in Memory Layer

**Frontend:**
- Opportunity cards with impact estimates, evidence, and suggested actions
- Integration with Insight Feed

**Edge cases:** Not enough data for segmentation, single-product businesses, no revenue data available, privacy considerations for user segmentation.

---

### Task 5: Loss Detector

**Goal:** Find revenue leaks, inefficient spend, conversion drops.

**Backend:**
- New agent: `LossDetectorAgent`
- Funnel analysis: identify where users/revenue drop off
- Spend analysis: flag inefficient channels/campaigns
- Regression detection: compare current vs historical conversion rates
- Quantify losses: "$X/month lost due to Y"

**Frontend:**
- Loss cards with monetary impact, trend visualization, and fix suggestions
- Integration with Insight Feed

**Edge cases:** No funnel data, no spend data, seasonal drops misidentified as losses, data latency causing false alarms.

---

### Task 6: Insight → Action Engine ✅ `done`

**Goal:** Every insight gets a concrete recommended action with expected impact.

**Backend:**
- New service: `ActionEngine`
- Takes any insight (anomaly, opportunity, loss) and generates:
  - What to do (specific, actionable)
  - Expected impact (quantified)
  - Confidence level
  - Priority
- LLM-powered action generation with data context
- Track action outcomes when user reports back

**Frontend:**
- Action cards attached to every insight
- "Expected: +X% if you do Y" format
- Action tracking: mark as done, report outcome

**Edge cases:** Insight too vague for action, action requires external systems not connected, multiple conflicting actions, user lacks permissions to act.

---

### Task 7: Cross-Source Reconciliation Engine ✅ `done`

**Goal:** Compare data across sources (DB vs Stripe, Ads vs CRM) and find discrepancies.

**Backend:**
- New agent: `ReconciliationAgent`
- Compare matching metrics across connections
- Detect: missing records, value mismatches, timing differences
- Report discrepancies with severity and likely cause
- Leverages Data Graph to find comparable metrics

**Frontend:**
- Reconciliation dashboard: side-by-side comparison
- Discrepancy list with severity
- Drill-down into specific mismatches

**Edge cases:** Different schemas across sources, timezone mismatches, currency differences, eventual consistency delays, no overlapping metrics between sources.

---

### Task 8: Semantic Layer Auto-Build ✅ `done`

**Goal:** Auto-discover metrics, normalize definitions, replace tribal knowledge.

**Backend:**
- Extend DB index pipeline to extract metric definitions
- LLM-powered: analyze column names, types, relationships → generate metric catalog
- Normalize: unify definitions across connections (e.g., "revenue" means the same everywhere)
- Service: `SemanticLayerService` — build, query, update catalog
- Store in Data Graph

**Frontend:**
- Metric catalog browser
- Edit/confirm metric definitions
- Link metrics to business terms

**Edge cases:** Ambiguous column names, different definitions across DBs, custom aggregation formulas, calculated fields.

---

### Task 9: Query-less Exploration ✅ `done`

**Goal:** User says "What's wrong?" and agent autonomously investigates.

**Backend:**
- New exploration mode in Orchestrator
- Autonomous investigation pipeline:
  1. Scan recent insights and anomalies
  2. Run diagnostic queries across sources
  3. Build hypothesis → test → confirm/reject
  4. Compile findings into structured report
- Leverage Memory Layer for context

**Frontend:**
- "Explore" button or natural language trigger
- Progressive disclosure: show investigation steps as they happen
- Final report with findings, severity, actions

**Edge cases:** No clear issues found (positive report), too many issues (need prioritization), investigation takes too long (timeout/streaming), user interrupts mid-investigation.

---

### Task 10: Temporal Intelligence Engine ✅ `done`

**Goal:** Understand trends, seasonality, lags — not just snapshots.

**Backend:**
- New service: `TemporalIntelligenceService`
- Time series analysis: decompose into trend + seasonality + residual
- Lag detection: find delayed effects between metrics
- Anomaly detection in temporal context (adjust for seasonality)
- Pure Python (statsmodels-lite or custom) — no heavy ML deps

**Frontend:**
- Time series charts with trend overlay
- Seasonality indicators
- "This is normal for this time" context on insights

**Edge cases:** Insufficient history for seasonality detection, irregular time intervals, missing data points, multiple seasonality patterns.

---

## Backlog Queue — Ideas

> These are not prioritized within the queue. They will be prioritized when Sprint 1 is complete.

| #  | Idea | Category | Notes |
|----|------|----------|-------|
| 11 | Cross-Source Causal Graph Engine | Core | Build cause-effect relationships between metrics across sources |
| 12 | Data Hypothesis Generator | Multiplier | Auto-generate growth and problem hypotheses |
| 13 | Auto Cohort Discovery | Multiplier | Find unexpected segments and hidden patterns automatically |
| 14 | Behavioral Pattern Mining | Multiplier | Find action chains and leading indicators ("users who do X → convert 3x") |
| 15 | KPI Dependency Mapping | Multiplier | Map what influences what and how strongly |
| 16 | Smart Alerts with Context Memory | Multiplier | Alerts that know past events, similar cases, resolved problems |
| 17 | Data Confidence Engine | Multiplier | Per-insight confidence with sources and validations |
| 18 | Auto Benchmarking Engine | Multiplier | Compare with history, industry, internal segments |
| 19 | Predictive Scenario Engine | Advanced | "What if you increase price by 10%?" simulations |
| 20 | Cross-Company Pattern Learning | Advanced/Moat | Learn from anonymized patterns across companies |
| 21 | Autonomous Optimization Loops | Advanced/Moat | Find → propose → test → optimize automatically |
| 22 | Multi-database JOIN queries | Platform | Query across multiple connections in a single question |
| 23 | Natural language data transformations | Platform | "Show me revenue per user cohort by signup month" |
| 24 | AI-powered data documentation generation | Platform | Auto-generate docs for every table, column, relationship |
| 25 | Real-time collaborative analysis | Collaboration | Multiple users exploring data together |
| 26 | Shared insight feeds with public links | Collaboration | Share feed with stakeholders |
| 27 | Slack/Discord integration | Collaboration | Push insights to team channels |
| 28 | PDF/email report generation | Output | Scheduled report delivery |
| 29 | Custom visualization builder | Platform | User-defined chart types |
| 30 | Plugin/extension system | Platform | Third-party integrations |
| 31 | SSO (SAML, OIDC) | Enterprise | Enterprise authentication |
| 32 | Granular RBAC | Enterprise | Fine-grained permissions per source/metric |
| 33 | Audit log export | Enterprise | Compliance and security |
| 34 | BigQuery connector | Connectors | Google BigQuery support |
| 35 | Snowflake connector | Connectors | Snowflake support |
| 36 | DuckDB connector | Connectors | DuckDB/local analytics |
| 37 | SQLite connector | Connectors | SQLite support |
| 38 | Redshift connector | Connectors | AWS Redshift support |
| 39 | Query result caching with invalidation | Performance | Cache repeated queries |
| 40 | Dark/light theme toggle | UX | Theme switching |
| 41 | Keyboard-driven navigation | UX | Power user shortcuts |
| 42 | Natural language query templates | UX | Reusable question patterns |
| 43 | Mobile-responsive improvements | UX | Better mobile experience |
| 44 | Data lineage visualization | Data Quality | See where data flows |
| 45 | Schema change detection | Data Quality | Alert when schema changes |
| 46 | Data freshness monitoring | Data Quality | Track when sources last updated |
| 47 | Metric alerting with thresholds | Monitoring | Set alerts on any metric |
| 48 | Goal tracking | Business | Track progress toward business goals |
| 49 | Competitive intelligence integration | Advanced | Pull and compare industry data |
| 50 | Natural language API (headless mode) | Platform | Use as API without UI |
| 51 | Webhook notifications | Integration | Push events to external systems |
| 52 | Data catalog search | UX | Search across all metrics and tables |
| 53 | Conversation branching | UX | Fork a chat to explore alternatives |
| 54 | Insight sharing with annotations | Collaboration | Share specific insights with team notes |
| 55 | Cost attribution analysis | Business | Attribute costs to features/teams |
| 56 | Revenue attribution modeling | Business | Multi-touch attribution |
| 57 | Churn prediction | Advanced | Predict which users will churn |
| 58 | LTV prediction | Advanced | Predict user lifetime value |
| 59 | A/B test analysis agent | Advanced | Automated experiment analysis |
| 60 | Data quality score per source | Data Quality | Overall health score per connection |

---

## Sprint 8 — M1–M6 rollout completion (queued)

**Status:** P0. `code_graph_enabled` + `lineage_enabled` were flipped default-on in **1.15.0 (W6)** via the `python -m app.eval.graph_benchmark` quality gate (spec §9, F-ARCH-6) rather than a time-boxed soak. Remaining: `clustering_enabled` flip (8.5) + the two cleanup PRs (8.6/8.7). See [docs/ROLLOUT_M1_M6.md](docs/ROLLOUT_M1_M6.md) §4 for the cleanup-PR inventory.

| #  | Task | Status | Priority | Dependencies | Est. Complexity |
|----|------|--------|----------|--------------|-----------------|
| 8.1 | Flip `code_graph_enabled` default `False → True` | `done` (default `True` as of 1.15.0 W6, benchmark-gated: `graph_benchmark` PASS `symbols=7 CALLS=2 EXTENDS=1 IMPORTS=1`) | P0 | Graph-quality benchmark | Low |
| 8.2 | Flip `hybrid_retrieval_enabled` default `False → True` after 2-week soak | `done` (default `True` as of 1.14.0, with dense-only fallback) | P0 | 8.1 soak passes | Low |
| 8.3 | Flip `schema_retrieval_enabled` default `False → True` after 2-week soak | `done` (default `True` as of 1.14.0, unioned with legacy relevance net) | P0 | 8.2 soak passes | Low |
| 8.4 | Flip `lineage_enabled` default `False → True` | `done` (default `True` as of 1.15.0 W6, gated together with `code_graph_enabled`) | P0 | 8.1 | Low |
| 8.5 | Flip `clustering_enabled` default `False → True` after 2-week soak | `pending` | P0 | 8.4 soak passes | Low |
| 8.6 | Cleanup PR: remove `if settings.<flag>:` gates per [docs/ROLLOUT_M1_M6.md §4.2](docs/ROLLOUT_M1_M6.md) | `pending` | P0 | 8.5 + soak of default-on flags | Medium |
| 8.7 | Cleanup PR: remove prompt-builder kwargs (`hybrid_retrieval_enabled`, `lineage_enabled`, `schema_retrieval_enabled`, `has_code_clusters`) per [§4.3](docs/ROLLOUT_M1_M6.md) | `pending` | P0 | 8.6 | Low |

**Explicit non-removal list** (preserve these even after defaults flip):

- `KnowledgeAgent._dense_only_search()` — BM25-missing safety net, not legacy. Stays unconditionally.
- `LLM.stream()` and other `@abstractmethod` ABCs in `backend/app/llm/base.py` — standard ABC pattern, not stubs.
- Per-request override of every flag via `extra` (operator escape hatch for projects that need different behavior).

**Rollout status table:** maintained in [docs/ROLLOUT_M1_M6.md §5](docs/ROLLOUT_M1_M6.md). As of 1.15.0: `hybrid_retrieval_enabled`, `schema_retrieval_enabled`, `code_graph_enabled`, `lineage_enabled`, `reranker_enabled`, and `context_planner_enabled` default `True` (last four flipped in 1.15.0 W2/W6 via benchmark gates); `clustering_enabled` remains the only `pending` flag.

---

## Sprint 9 — Test coverage gaps (queued)

**Status:** P2, drives the 72% → 80% backend coverage target documented in [docs/agent-backlog.md](docs/agent-backlog.md).

| #  | Task | Status | Priority | Dependencies | Est. Complexity |
|----|------|--------|----------|--------------|-----------------|
| 9.1 | Full-pipeline E2E with a real fixture repo (clone → ast_parse → graph_build → analyze_files → embed_and_store → bm25_build) | `pending` | P2 | None | Medium |
| 9.2 | Incremental indexing path: only changed files reprocessed (covers the `detect_changes` short-circuit + `cleanup_deleted` step) | `pending` | P2 | 9.1 | Medium |
| 9.3 | Binary / large-file filtering at ingestion (current guards in `ast_parse_concurrency` + `ast_max_file_bytes` are untested at the pipeline level) | `pending` | P2 | None | Low |
| 9.4 | Relevance-quality smoke tests for hybrid retriever (golden set; assert top-k recall ≥ baseline) | `pending` | P2 | None | Medium |
| 9.5 | Component tests for `KnowledgeDocs.tsx` and `WorkflowProgress.tsx` (currently uncovered per [docs/MASTER_TEST_PLAN.md](docs/MASTER_TEST_PLAN.md)) | `pending` | P2 | None | Low |
| 9.6 | Manual a11y matrix execution from [docs/agent-test-matrix.md](docs/agent-test-matrix.md) lines 64-73 (onboarding → mobile → error states) | `pending` | P2 | None | Low |
| 9.7 | Address P2/P3 a11y gaps in [docs/agent-findings.md](docs/agent-findings.md): mobile notes drawer focus management, suggestion-chip aria-pressed, insight-card aria-expanded, layout-flash on resize | `pending` | P2 | 9.6 | Medium |
| 9.8 | Raise CI backend-coverage threshold from 72% to 80% | `pending` | P2 | 9.1–9.4 close measurable gaps | Low |

---

## Sprint 10 — Documented "for now" debts (queued)

**Status:** P2 product/architectural debt — each item is a comment in the codebase saying "this is a heuristic, replace later".

| #  | Task | Status | Priority | Source comment | Est. Complexity |
|----|------|--------|----------|----------------|-----------------|
| 10.1 | Replace `orchestrator_pipeline_table_threshold` table-count routing heuristic with a planner-LLM step (router already returns `estimated_queries` + `needs_multiple_data_sources` — wire those into routing instead) | `pending` | P2 | [backend/app/config.py](backend/app/config.py) lines ~363-365 — "future work will route this through the planner LLM instead of table count alone" | Medium |
| 10.2 | Optional Chroma extension for `SchemaRetriever` (currently BM25-only by design; documented as a future extension point) | `pending` | P3 | [backend/app/knowledge/schema_retriever.py](backend/app/knowledge/schema_retriever.py) lines 11-18 — "do not wire Chroma into this path for now … If we later want semantic recall" | Medium |
| 10.3 | Incremental per-file code-graph updates (today the M2 step rebuilds the full graph on every index run; per-file deltas + edge surgery would cut indexing cost on large repos) | `pending` | P3 | Implied by the "full rebuild" shape of `CodeGraphBuilder.build` | High |
| 10.4 | Multi-language receiver-type resolution for cross-class CALL edges (current tree-sitter walker resolves callee names but not the receiver's class in dynamic languages) | `pending` | P3 | M1 plan scope cut: "single-language receiver typing only" | High |
| 10.5 | Multi-repo / monorepo cross-repo code graph (today the graph is scoped to a single project; teams with split frontend/backend repos can't see lineage across the seam) | `pending` | P3 | M2 plan scope cut: "single-repo only" | High |
| 10.6 | Expose the `query_empty_result_retry` knob in the UI (currently a backend-only feature flag, default `True` since the audit-remediation workstream — no operator surface) | `pending` | P3 | [backend/app/config.py:151](backend/app/config.py) | Low |
| 10.7 | Decide on `data_gate_llm_semantics` (LLM vs keyword heuristic) — currently a `False`-by-default flag with no rollout plan | `pending` | P3 | [backend/app/config.py:598](backend/app/config.py) | Low |

---

## Completed

| # | Task | Completed Date | Notes |
|---|------|---------------|-------|
| 1 | Foundation: Data Graph + Memory + Trust Layers | 2026-03-22 | Models, services, API, frontend panel |
| 2 | Autonomous Insight Feed | 2026-03-22 | InsightFeedAgent, /api/feed/, InsightFeedPanel |
| 3 | Anomaly Intelligence (upgrade) | 2026-03-22 | AnomalyIntelligenceEngine, AnomalyReportCard |
| 4 | Opportunity Detector | 2026-03-22 | OpportunityDetector, OpportunityCard |
| 5 | Loss Detector | 2026-03-22 | LossDetector, LossReportCard |
| 6 | Insight → Action Engine | 2026-03-22 | ActionEngine, ActionCard |
| 7 | Cross-Source Reconciliation Engine | 2026-03-22 | ReconciliationEngine, ReconciliationCard |
| 8 | Semantic Layer Auto-Build | 2026-03-22 | SemanticLayerService, MetricCatalogPanel |
| 9 | Query-less Exploration | 2026-03-22 | ExplorationEngine, ExplorationReport |
| 10 | Temporal Intelligence Engine | 2026-03-22 | TemporalIntelligenceService, TemporalReport |
| 11 | Vision Invariants restored (v1.13.0) | 2026-05-19 | V1 per-connection learning isolation, V2 continuous learning, V3 staleness in complex pipeline, V4 negative feedback contradiction |
| 12 | Correctness Restoration (v1.13.0) | 2026-05-19 | C1 git renames, C2 generate_docs resilience, C3 chroma failure policy, C4 DataGate fail(), C5 read-only get_agent_learnings (times_exposed), C6 insight expiry+decay cron |

> **Queued (Sprints 13-15)** remain as documented in §"Backlog Queue —
> Ideas" and Sprints 8-10 above: M1-M6 rollout completion (8), test
> coverage gaps (9), and "for now" architectural debts (10). v1.13.0 did
> not touch any of those.

---

## Process

1. Take next `pending` task from Sprint
2. Design architecture (backend modules, models, services, API)
3. Design UX/UI (frontend components, interactions, responsive)
4. Analyze edge cases
5. Create 30+ step implementation plan
6. Implement
7. Test (unit + integration + frontend)
8. Lint check (`ruff`, `mypy`, `eslint`, `tsc`)
9. Commit + push
10. Verify GitHub Actions pass
11. If CI fails → fix → re-push
12. Mark task as `done` in this file
13. Proceed to next task
14. After Sprint complete → wait for approval → re-prioritize → next Sprint
