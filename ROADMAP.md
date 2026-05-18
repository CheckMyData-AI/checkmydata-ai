# Roadmap

## Current Priorities

### Stability & Security (Active)
- Comprehensive test coverage (target: 80%+)
- Security audit and hardening
- Error handling improvements
- Performance optimization

### Documentation (Active)
- ~~API reference completion~~ (done — see API.md)
- Video tutorials
- Deployment guides for AWS, GCP, self-hosted

## Near Term

### Database Support
- [ ] SQLite connector
- [ ] BigQuery connector
- [ ] Snowflake connector
- [ ] DuckDB connector

### AI Chief Data Brain (Sprint 1 Complete — see BACKLOG.md)
- [x] Foundation Layer: Data Graph, Insight Memory, Trust Layer
- [x] Autonomous Insight Feed (proactive analysis)
- [x] Anomaly Intelligence (root cause + severity)
- [x] Opportunity Detector (growth segments, undermonetized users)
- [x] Loss Detector (revenue leaks, conversion drops)
- [x] Insight → Action Engine (recommended actions with expected impact)
- [x] Cross-Source Reconciliation Engine
- [x] Semantic Layer Auto-Build
- [x] Query-less Exploration ("what's wrong?")
- [x] Temporal Intelligence Engine (trends, seasonality, lags)

### AI Improvements
- [ ] Query result caching with invalidation
- [ ] Multi-turn conversation memory improvements
- [ ] Agent learning from user feedback (active learning loop)
- [ ] Cost optimization with model routing

### UX Enhancements
- [ ] Dark/light theme toggle
- [ ] Keyboard-driven navigation
- [x] Query history search (Cmd+K / Ctrl+K)
- [ ] Natural language query templates
- [x] Mobile-responsive sidebar drawer and layout

## Medium Term

### Collaboration
- [ ] Real-time collaborative editing
- [ ] Shared dashboards with public links
- [ ] Comments on queries and dashboards
- [ ] Slack/Discord integration for notifications

### Data Pipeline
- [x] Scheduled query execution with alerting (ScheduleManager, cron + threshold alerts)
- [x] Data quality monitoring (Data Validation, sanity checks, benchmarks)
- [x] Automated anomaly detection (AnomalyIntelligenceEngine, proactive scans)
- [ ] Report generation (PDF/email)

### Enterprise Features
- [ ] SSO (SAML, OIDC)
- [ ] Audit log export
- [ ] Role-based access control (granular permissions)
- [ ] Multi-workspace support

## Long Term

### Platform
- [ ] Plugin/extension system
- [ ] Custom visualization builder
- [ ] API-first mode (headless)
- [ ] Self-hosted marketplace

### AI
- [ ] Multi-database join queries
- [ ] Automated data modeling suggestions
- [ ] Natural language data transformation
- [ ] AI-powered data documentation generation

## Architectural Debt & Rollout-Gated Cleanups

The in-house **M1–M6 code intelligence pipeline** (AST parsing, code knowledge graph, hybrid retrieval, question-aware schema retrieval, code↔DB lineage, functional clustering) is shipped behind five feature flags and currently in soak. Operational details live in two canonical docs:

- **Rollout playbook**: per-flag canary criteria, smoke tests, soak duration, rollback procedures, and the exact scope of the post-soak cleanup PR — see [docs/ROLLOUT_M1_M6.md](docs/ROLLOUT_M1_M6.md).
- **Sprint backlog**: the flips themselves, the cleanup PR, the coverage gaps that block the 80% target, and the documented "for now" debts (planner-LLM routing, optional Chroma in `SchemaRetriever`, incremental per-file graph updates, multi-language receiver resolution, multi-repo cross-repo graph) — see [BACKLOG.md](BACKLOG.md) **Sprint 8** (rollout completion), **Sprint 9** (test coverage gaps), and **Sprint 10** (documented "for now" debts).

Until those soaks complete and the cleanup PR ships, the legacy regex/dense-only paths remain the canonical fallback in production — every M1–M6 stage degrades gracefully when its flag is off.

## Contributing to the Roadmap

We welcome input on priorities. If you'd like to work on a roadmap item:
1. Open an issue to discuss the approach
2. Reference this roadmap in your PR description
3. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines
