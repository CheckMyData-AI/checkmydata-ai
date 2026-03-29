# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Project creation eligibility gate** — New `can_create_projects` flag on users table (default `false`). Only eligible users can create projects on the hosted version; others see a "Request Access" modal with email/description/message form that sends a request to `contact@checkmydata.yay`. Backend enforces with 403 on `POST /api/projects`. New `POST /api/projects/access-requests` endpoint. Admin users (`sergeysheleg4@gmail.com`, `sergey@appvillis.com`) are seeded with `can_create_projects=true` via Alembic migration. Non-eligible users can still join projects via invite or use the self-hosted version
- **Analytics & Usage RBAC** — Analytics (`GET /chat/analytics/feedback/{pid}`, `GET /data-validation/analytics/{pid}`, `GET /data-validation/summary/{pid}`) and Usage sidebar panels are now restricted to project **owners** only. Non-owners no longer see these sections in the sidebar
- **Dashboard RBAC** — Dashboard create/edit/delete operations now require at least **editor** role. Viewers can list and view shared dashboards but cannot modify them. The "New dashboard" sidebar action and Edit button on dashboard pages are hidden for viewers. Any editor/owner can edit or delete any dashboard in their project (not just the creator)
- **`FormModal` component** (`frontend/src/components/ui/FormModal.tsx`) — Reusable modal shell with title bar, close (X) button, Escape key, backdrop click dismiss, focus trap, and scroll support
- **KnowledgeResult.sources populated** — RAG search results now correctly wire `RAGSource` objects into `KnowledgeResult.sources`, enabling citation display in chat
- **Global learning patterns** — `AgentLearningService` now identifies learnings that appear across 2+ connections and promotes them into every connection's prompt as universal patterns
- **Pre-call token estimation** — `LLMRouter.estimate_tokens()` uses tiktoken (OpenAI-accurate) with char-based fallback for pre-call context budgeting
- **Knowledge quality scoring** — `RAGFeedbackService` now computes per-source quality scores combining success rate and average retrieval distance, and identifies low-quality sources for re-indexing
- **Persistent query cache** — `QueryCache` supports optional file-based persistence via `query_cache_persist_dir` config, surviving process restarts
- **Incremental schema diff** — `SchemaInfo.fingerprint()` and `SchemaInfo.diff()` enable comparing schemas to detect only changed tables, avoiding full re-introspection
- **Token budget caps** — `UsageService.check_budget()` enforces configurable daily/monthly token limits per user with `BudgetExceededError` and remaining-budget reporting
- **Landing page and full branding** — New public landing page at `/` with hero section, feature grid (6 cards), how-it-works flow, open-source CTA, and supported databases banner. Dark theme using existing design system tokens with JSON-LD structured data for SEO
- **Marketing layout** — Shared `(marketing)` route group layout with sticky blurred header (logo, nav, Login, Get Started CTA) and 4-column footer (Product, Legal, Community links)
- **Dedicated login page** (`/login`) — Standalone authentication page with CheckMyData.ai branding replacing the inline AuthGate form. Supports email/password and Google OAuth
- **About page** (`/about`) — Product mission, technology stack overview, and open-source philosophy
- **Contact page** (`/contact`) — Email channels (contact@checkmydata.ai, support@checkmydata.ai) and GitHub community links
- **Support page** (`/support`) — FAQ with expandable details, documentation links, and support channels
- **Branding assets** — Generated favicon.ico, icon-192.png, icon-512.png, apple-touch-icon.png, og-image.png (1200x630), and reusable `Logo.tsx` SVG component (`LogoMark` + `LogoFull` variants)
- **SEO infrastructure** — robots.txt (disallows /app and /dashboard), dynamic sitemap.xml via Next.js `sitemap.ts`, `metadataBase` on root layout, canonical URLs and OG/Twitter Card metadata on all pages

### Fixed
- **Authenticated user landing redirect** — Added `AuthRedirect` client component to the landing page so authenticated users visiting `/` are automatically redirected to `/app` instead of seeing the marketing page

### Changed
- **Custom Rules editor enlarged** — Rule edit/create modal widened from `max-w-lg` (512px) to `max-w-3xl` (768px) with a taller monospaced textarea (rows=12, min-h-200px) for comfortable markdown editing
- **Agent Learnings popup** — LearningsPanel converted from an inline accordion inside the sidebar to a centered `FormModal` popup (`max-w-3xl`) with 60vh scroll area, larger text, and roomier edit textareas
- **Sidebar forms → centered modals** — All 6 sidebar create/edit forms (Project, Connection, SSH key, Rule, Schedule, Dashboard) now open as centered pop-up modals instead of rendering inline in the sidebar
- **StageValidator configurable strictness** — Min/max row count checks can now fail (not just warn) via `strict_row_bounds` flag
- **SSH tunnel idle cleanup** — `SSHTunnelManager` now tracks last-used time per tunnel and closes idle tunnels (default 30min TTL)
- **Parallel batch queries** — `BatchService.execute_batch()` now runs queries concurrently (up to 4 parallel, configurable)
- **Expanded rule-based viz** — `VizAgent` now handles more cases without LLM calls: auto-detects pie/bar/line charts for common data shapes
- **Deprecated orchestrator decoupled** — `core/orchestrator.py` is no longer imported by any production code
- **Route restructure** — Main application moved from `/` to `/app`. Unauthenticated users see the landing page at `/` instead of a login form
- **AuthGate simplified** — Reduced from 293-line login form to a 42-line redirect guard that sends unauthenticated users to `/login`
- **Legal pages moved** — `/terms` and `/privacy` migrated from `(legal)` to `(marketing)` route group to share the common header/footer
- **401 redirect** — Session-expired handler in `api.ts` now redirects to `/login` instead of `/`
- **manifest.json** — Updated `start_url` to `/app`, added enhanced description

### Added
- **Adaptive step budget system** — Replaced the hard 10-iteration orchestrator ceiling with an adaptive step budget (default 25). The LLM is now informed when it's running low on steps via a step-budget-aware wrap-up prompt (`orchestrator_wrap_up_steps`). When exhausted, a final LLM synthesis call (`orchestrator_final_synthesis`) produces a coherent summary instead of a static "maximum steps reached" message.
- **Continuation protocol** — When the step limit is reached, the response includes `response_type: "step_limit_reached"` with `steps_used`, `steps_total`, and `continuation_context`. The frontend renders a "Continue analysis" button that lets users resume the analysis from where it left off.
- **Per-project and per-request step overrides** — Added `max_orchestrator_steps` column to the `Project` model and `max_steps` field to the chat request body. Resolution order: request `max_steps` > project `max_orchestrator_steps` > global `max_orchestrator_iterations`.
- **Consistent sub-agent iteration limits** — `KnowledgeAgent` and `InvestigationAgent` now use `settings.max_knowledge_iterations` and `settings.max_investigation_iterations` instead of hardcoded class constants. `MAX_SUB_AGENT_RETRIES` in the orchestrator uses `settings.max_sub_agent_retries`.
- **Orchestrator prompt efficiency guideline** — Added a tool-usage efficiency guideline to the orchestrator system prompt encouraging the LLM to combine related questions and parallelize independent tool calls.

### Fixed
- **Email service security and reliability hardening** (`backend/app/services/email_service.py`) — Fixed HTML injection vulnerability: all user-provided values (`display_name`, `project_name`, `inviter_name`, etc.) are now HTML-escaped via `html.escape()` before interpolation into email templates. Added retry with exponential backoff (1s, 2s, 4s) for transient Resend errors (429 rate-limit, 500 server error), max 3 retries. Moved `resend.api_key` assignment from every `_send()` call to `__init__()`. Email send results now log the Resend email ID for traceability. Added category tags (`welcome`, `invite`, `invite-accepted`) for Resend dashboard analytics.
- **ARQ worker crash** — `run_db_index` and `run_code_db_sync` worker tasks referenced non-existent service methods (`set_indexing_status_standalone`, `index_connection`, `run_sync_standalone`). Rewrote both to use `DbIndexPipeline` and `CodeDbSyncPipeline` with proper session management. Fixes #128
- **ReadinessBanner stale state** — Banner showing "index outdated" from a previous project was never cleared on project switch. Now resets `staleInfo` to null when the new project is not stale. Fixes #129
- **WrongDataModal empty connection_id** — Investigation form sent `connection_id: ""` when no DB connection was selected, causing 422 errors. Now validates connection and shows user-friendly toast. Fixes #130
- **useGlobalEvents null workflow_id crash** — `toLogEntry` called `.slice()` on potentially null `workflow_id`, crashing SSE event processing. Added null-safe fallback. Fixes #131
- **Traceback logging in task callbacks** — 5 files passed exception instances to `exc_info=` in asyncio task done callbacks where `sys.exc_info()` is empty. Changed to explicit `(type, value, traceback)` tuples for reliable stack traces. Fixes #132
- **chat.py missing ConnectionConfig import** — Added `TYPE_CHECKING` import for `ConnectionConfig`, resolving ruff F821 and mypy name-defined errors. Fixes #133
- **Ruff lint violations** — Resolved all E501 (line too long) and I001 (import sorting) across `chat.py`, `task_queue.py`, `main.py`, `email_service.py`. `ruff check app/` now passes clean. Fixes #134
- **Logout state leak** — Sign-out now resets all Zustand stores (app, notes, log, task) preventing previous user's chat messages and project data from persisting in memory. Fixes #135
- **Knowledge agent raw tool fallback** — When max iterations exhausted, fallback now uses the last assistant message instead of raw tool output. Fixes #136
- **task_queue.py mypy regression** — Fixed `exc_info` tuple type by adding explicit None guard on `t.exception()`. Fixes #137
- **SSE premature connected flag** — Removed eager `setConnected(true)` after subscription setup; connected state now only set on first received event. Fixes #138
- **Orchestrator shared SQL state** — Per-request SQL results (`_last_sql_result`) scoped per `workflow_id` to prevent data leakage between concurrent requests. Fixes #139

### Added
- **Design system documentation** (`DESIGN_SYSTEM.md`) — Comprehensive visual guide covering semantic color tokens, typography scale, spacing, border-radius, shadows, icons, button variants, form inputs, cards, modals, tooltips, toasts, status indicators, animations, responsive rules, and accessibility guidelines
- **Frontend design system skill** (`.cursor/skills/frontend-design-system/SKILL.md`) — Cursor agent skill that enforces design system compliance on all future frontend work
- **Celery worker infrastructure** (`backend/app/worker.py`, `backend/app/core/task_queue.py`, `backend/app/core/cache.py`) — Redis-backed task queue with shared cache layer for background job processing

### Changed
- **Full design system migration** (68 frontend files) — Migrated all raw Tailwind palette classes (`zinc-*`, `blue-*`, `red-*`, `emerald-*`, `amber-*`, `purple-*`, etc.) to semantic design tokens (`surface-*`, `text-*`, `border-*`, `accent`, `success`, `error`, `warning`, `info`). Zero raw palette classes remain in component files
- **Typography scale enforcement** — Eliminated all off-scale font sizes: `text-[8px]`/`text-[9px]` → `text-[10px]`, `text-[11.5px]` → `text-[11px]`, `text-[12px]`/`text-[13px]` → `text-sm`, legal page h1 `text-3xl` → `text-2xl`
- **Card/panel border-radius standardization** — All card and panel containers now use `rounded-xl`; form inputs use `rounded-lg`; modals use `rounded-lg`
- **Modal accessibility** — OnboardingWizard now has `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, focus trap, and Escape-to-close. WrongDataModal updated with `aria-labelledby` and correct shadow level
- **Toast styling** — Success/error/info toast variants now use semantic tokens instead of raw palette colors
- **Button focus rings** — ConfirmModal Cancel/Confirm buttons now have `focus-visible:ring` styles
- **Shadow standardization** — Eliminated `shadow-2xl` (modals → `shadow-xl`), `shadow-md` (LogPanel toggle → `shadow-lg`)
- **Batch service refactored** for Celery task queue support with improved error handling

### Fixed
- **Missing ARIA labels** — Added `aria-label` to icon-only buttons in InviteManager, LearningsPanel, ScheduleManager, NoteCard, DashboardBuilder, AccountMenu, LlmModelSelector, and OnboardingWizard
- **Missing `transition-colors`** — Added smooth color transitions to interactive elements in StageProgress, Sidebar, NotificationBell
- **ActionCard `aria-expanded`** — Expand/collapse button now correctly announces its state to screen readers
- **ConfirmModal typing input** — Added `aria-label` for the confirmation phrase input
- **SessionContinuationBanner invalid tokens** — Fixed references to non-existent tokens (`text-text-2`, `bg-border`) → valid semantic tokens
- **Test assertions updated** — VerificationBadge and ConfirmModal tests updated to match semantic token class names

### Added
- **Transactional emails via Resend** (`backend/app/services/email_service.py`) — Three email types: welcome email on registration, invite notification when a project owner invites a collaborator, and acceptance confirmation when an invite is accepted. Uses the Resend Python SDK with `asyncio.to_thread()` for async compatibility. Idempotency keys prevent duplicate sends. Gracefully no-ops when `RESEND_API_KEY` is not configured. New env vars: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `APP_URL`
- **Session rotation** (`backend/app/services/session_summarizer.py`) — Automatic context-aware session rotation when chat history approaches the context window limit. Summarizes the old session via LLM, creates a new session with a continuation banner linking back to the original. Frontend `SessionContinuationBanner` component shows the transition. Cost estimate endpoint now includes `rotation_imminent` flag. Configurable via `SESSION_ROTATION_ENABLED`, `SESSION_ROTATION_THRESHOLD_PCT`, `SESSION_ROTATION_SUMMARY_MAX_TOKENS`
- **Context usage tracking in AgentResponse** — `context_usage_pct` field added to `AgentResponse` so the frontend can display how much of the context window has been consumed
- **Connection health auto-refresh** — `ConnectionHealth` component now auto-refreshes status periodically and shows more detailed health info
- **ChatMessage copy-all button** — New button on chat messages to copy the entire message content
- **GeoIP two-tier cache** (`backend/app/services/geoip_cache.py`) — In-memory LRU (100k entries, ~20MB) + SQLite persistent storage (`data/geoip_cache.db`, WAL mode, `WITHOUT ROWID`) for IP geolocation results. Eliminates redundant lookups across requests and survives process restarts. Handles millions of unique IPs. Batch operations deduplicate IPs and use batch SQL reads/writes. Configurable via `GEOIP_CACHE_ENABLED`, `GEOIP_CACHE_DIR`, `GEOIP_MEMORY_CACHE_SIZE` env vars
- **Data Processing meta-tool (`process_data`)** — Orchestrator tool that enriches query results with derived data between query steps. Enables multi-step analysis workflows (e.g., query DB for IPs, convert to countries, filter, aggregate). Supports chaining multiple operations sequentially
- **IP-to-country enrichment (`ip_to_country`)** — Offline GeoIP resolution using `geoip2fast` (MaxMind GeoLite2 database). Converts IP address columns to ISO country codes and country names with no external API calls
- **Phone-to-country enrichment (`phone_to_country`)** — Offline E.164 dialing code prefix resolution (~250 countries/territories) with Canadian area code disambiguation for US/CA differentiation within NANP +1 zone
- **In-memory aggregation (`aggregate_data`)** — Groups enriched data by one or more columns and computes `count`, `count_distinct`, `sum`, `avg`, `min`, `max`, `median`. **Multiple functions per column supported** (e.g., `amount:sum,amount:avg,*:count`). Optional `sort_by` / `order` params for controlling result ordering
- **Row filtering (`filter_data`)** — Post-enrichment row filtering by column value. Supports operators: `eq`, `neq`, `contains`, `not_contains`, `gt`, `gte`, `lt`, `lte`, `in`. Can exclude empty/null values with `exclude_empty`
- **`count_distinct` aggregation** — Counts unique non-null values in a column within each group (e.g., unique users per country)
- **`median` aggregation** — Computes median value for numeric columns within each group
- **GeoIPService** (`backend/app/services/geoip_service.py`) — Singleton service for offline IP geolocation lookups with graceful fallback when the library is unavailable
- **PhoneCountryService** (`backend/app/services/phone_country_service.py`) — Singleton service for offline phone number to country resolution via E.164 dialing codes, including Canadian area code disambiguation
- **DataProcessor** (`backend/app/services/data_processor.py`) — Pluggable data transformation engine that operates on `QueryResult` objects with four operations: `ip_to_country`, `phone_to_country`, `aggregate_data`, `filter_data`
- **Complex pipeline support** — `process_data` registered as a valid stage tool in `QueryPlanner` and `StageExecutor` for multi-stage queries (up to 10 stages). Stage executor parses structured JSON from `input_context` with fallback heuristics and emits fine-grained progress events
- **Sequential guard for `process_data`** — When `process_data` appears among parallel tool calls, the orchestrator forces sequential execution to prevent race conditions on shared `_last_sql_result` state
- **Aggregation visualization** — VizAgent is automatically triggered after `aggregate_data` to produce charts/tables for aggregated results
- **Cross-message enriched data persistence** — Enriched `QueryResult` survives across conversation turns for 5 minutes, enabling follow-up questions without re-running the full enrichment pipeline
- **Orchestrator iteration limit raised to 10** — Supports complex multi-enrichment workflows (e.g., dual-query call+SMS analysis with ip_to_country + phone_to_country + aggregate_data for each)

### Fixed
- **Google OAuth 403 on cross-origin** — CSRF double-submit cookie check in `/api/auth/google` now skips verification when the cookie is absent (cross-origin setup where frontend and API are on different domains). The nonce parameter already provides replay protection for the programmatic GIS callback flow
- **Heroku backup skip** — `BackupManager` now detects Heroku (`DYNO` env var) and skips `pg_dump` for managed Postgres, recommending `heroku pg:backups` instead
- **Noisy orchestrator context messages** — Replaced verbose SSE "thinking" events for context usage with quieter log-level messages to reduce UI clutter
- **LLM error formatting** — Improved error message formatting in LLM error classes
- **Registration race condition** — Concurrent duplicate email registrations now caught by DB `IntegrityError` and returned as 409 instead of 500
- **Invite accept commit on early return** — `accept_invite` now commits invite status change when user is already a project member, preventing the update from being silently rolled back
- **PATCH project response missing user_role** — `update_project` now returns a full `ProjectResponse` with `user_role` instead of the raw ORM object
- **Chat feedback learning trigger** — Negative feedback learning now triggers based on the clamped rating value instead of the raw request value, ensuring ratings like -2 or -5 still fire the learning pipeline
- **Reconnect handler connection leak** — `reconnect_connection` now always calls `connector.disconnect()` in a `finally` block, preventing connection/tunnel leaks on successful health checks
- **MCP connector TypeError on health check** — Reconnect and test-connection endpoints now gracefully handle MCP connections that don't support the `DatabaseAdapter` interface
- **Session rename title validation** — `SessionUpdate.title` now enforces `min_length=1` and `max_length=255` to prevent empty or oversized session titles
- **useRestoreState access detection** — `isAccessError` now detects permission errors by matching actual API error messages instead of just HTTP status code strings
- **Missing model imports** — Added 5 missing models (`BatchQuery`, `DataBenchmark`, `Dashboard`, `DataValidationFeedback`/`DataInvestigation`, `SessionNote`) to `models/__init__.py` for consistent mapper registration
- **Integration test auth for /health/modules** — Tests for the authenticated `GET /api/health/modules` endpoint now use `auth_client` instead of unauthenticated `client`
- **Performance smoke test limit for external API** — `test_models_list_latency` now uses a 2-second limit appropriate for the external OpenRouter API call instead of the 300ms internal-only limit
- **Mobile sidebar missing Dashboards** — Added Dashboards section to mobile sidebar drawer, matching desktop feature parity
- **DashboardBuilder JSON.parse crash** — Wrapped `visualization_json` parse in try/catch to prevent builder crash on malformed data
- **Investigation IDOR** — `get_investigation` and `confirm-fix` endpoints now verify the investigation's connection belongs to the requested project, preventing cross-project data access
- **SQL safety guard bypass** — UPDATE pattern now matches qualified table names (`schema.table`, `"schema"."table"`) and added MERGE/UPSERT DML patterns to read-only guard
- **Backend container runs as root** — Dockerfile.backend now creates a non-root `appuser` and runs the application with reduced privileges
- **Auth store localStorage consistency** — `storeAuth` now uses the safe-storage module matching the rest of the auth store, preventing partial state on Safari private mode
- **Pipeline end event not emitted** — Complex query and pipeline resume paths now emit `pipeline_end` event, preventing SSE streams from hanging indefinitely
- **SQL agent connector leak** — Connector cache now capped at 32 entries with LRU eviction and stale connector detection, preventing unbounded connection growth
- **Session title generation MissingGreenlet** — `generate_session_title` now uses explicit async query instead of triggering lazy-loaded relationship
- **Chat search LIKE injection** — Search term `%`, `_`, `\` characters now escaped before building LIKE pattern
- **WebSocket error information leak** — Error handler now sends generic message instead of raw exception string
- **SSE event regex mismatch** — Frontend SSE parser now matches hyphenated event names (e.g., `pipeline-end`)
- **ChatInput max length mismatch** — Frontend char limit raised from 4000 to 20000 to match backend
- **ChatMessage note state not reactive** — Note saved indicator now uses reactive Zustand subscription
- **Learning IDOR** — `update_learning` now verifies ownership before mutating, preventing cross-connection learning edits
- **MongoDB URI credential encoding** — Username and password now URL-encoded with `quote_plus` to handle special characters
- **SSH tunnel race condition** — Per-key asyncio locks prevent concurrent tunnel creation for the same config
- **ClickHouse password in process list** — Exec templates now pass password via environment variable instead of CLI argument
- **SSH key delete without user_id** — `delete()` now called with `user_id` for ownership verification consistency
- **Schedule pagination** — `list_schedules` and `get_history` endpoints now accept `skip`/`limit` query params
- **Alert conditions validation** — `alert_conditions` JSON validated as array with max_length; `notification_channels` capped
- **Result summary size cap** — Schedule run results truncated to 50 rows if JSON exceeds 1MB
- **Benchmark query unbounded** — `get_all_for_connection` now limited to 500 results
- **OpenRouter model fetch contention** — Double-check locking pattern reduces lock contention during cache misses
- **Connection service default limit** — `list_by_project` default reduced from 2000 to 200
- **Test connection error sanitization** — Error messages truncated to 500 chars to prevent internal detail leaks
- **Input validation hardening** — Added `max_length` to `LearningUpdate.lesson`, `SshKeyCreate.passphrase`, `mcp_env` size limits
- **Orchestrator fire-and-forget warning** — `ensure_future` callback now retrieves exceptions to suppress "Task exception was never retrieved" warnings
- **Default rules protection** — Default rules (system-generated) now return 403 on update/delete attempts, preventing accidental corruption
- **Shared notes access broken** — `get_note` and `execute_note` now use `_require_note_access` which allows project members to access shared notes (previously always returned 403)
- **NoteCard comment editing for non-owners** — Comment section now read-only for non-owners, preventing guaranteed 403 failures
- **Viz endpoint DoS** — `RenderRequest` rows capped at 10K, `ExportRequest` at 50K, columns at 500 to prevent server OOM
- **Dashboard update/delete membership check** — Both endpoints now verify project membership before checking creator ownership
- **Session notes unbounded queries** — `_find_similar` capped at 100 candidates, `get_notes_for_context` capped at 200 with 50-note default return
- **Rules rate limiting** — Added rate limits to `list_rules` (60/min) and `update_rule` (20/min)
- **Dashboard refresh parallelized** — `handleRefreshAll` now uses `Promise.allSettled` instead of sequential awaits
- **DashboardBuilder noteMap memoization** — `noteMap` wrapped in `useMemo` to prevent needless re-renders
- **Frontend input maxLength** — Added maxLength to RulesManager name/content, DashboardBuilder title inputs
- **ChartRenderer unknown type fallback** — Shows descriptive message instead of blank rectangle for unsupported chart types

### Security
- **Auth register error sanitization** — Register endpoint no longer exposes internal ValueError messages; returns static "already exists" message while logging details server-side
- **Rate limits on write endpoints** — Added rate limits to 7 previously unprotected mutation endpoints (PATCH projects, PATCH/DELETE sessions, generate-title, feedback, mark notification read, delete SSH key)
- **Probe service SQL injection hardening** — Tightened `_VALID_TABLE_RE` regex to reject quote characters; added `_quote_identifier()` with proper double-quote escaping per SQL standard
- **WebSocket input validation** — Chat WebSocket handler now validates incoming JSON with `WsChatMessage` Pydantic model (enforces message length, provider/model max_length)
- **Credentials cleanup** — Deleted local `notes.md` containing plaintext DB password and SSH private key (never committed to git history)

### Fixed
- **LLM health checks activated** — `start_health_checks()` now called on app startup; failed providers auto-marked unhealthy and skipped in fallback chain until recovered
- **Connector query result row cap** — All 4 DB connectors now cap results at 10,000 rows with `truncated` flag, preventing OOM on large result sets
- **useRestoreState race condition** — Sequence counter prevents stale restore data from overwriting user's active project selection during rapid switching
- **Misleading reconnect banner** — ChatPanel connection-down banner now says "Click Retry to reconnect" instead of the inaccurate "Attempting reconnect..."
- **Form input length limits** — Added maxLength to all text inputs in OnboardingWizard and ConnectionSelector (hosts, ports, credentials, URLs, commands)
- **Connector query timeout** — All connectors now use `settings.query_timeout_seconds` (default 30s) instead of hardcoded 120s
- **Workflow tracker synchronization** — `subscribe()` and `unsubscribe()` now async and acquire `_lock`, matching `_broadcast`'s locking discipline
- **Error boundary logging** — Both ErrorBoundary and SectionErrorBoundary now log caught errors with component stack via `componentDidCatch`
- **WebSocket token usage tracking** — WebSocket chat path now records LLM token usage via UsageService, matching HTTP `/ask` and `/ask/stream` endpoints (costs were previously untracked for WS users)
- **Toast notification cap** — Toasts limited to 5 max; oldest evicted when exceeded (prevents screen flooding during network failures)
- **Unbounded message loading** — `ChatService.get_session()` no longer eagerly loads all messages via `selectinload`; messages now fetched with DB-level LIMIT/OFFSET
- **SSH tunnel cleanup on connection delete** — `ConnectionService.delete()` now closes associated SSH tunnels across all connector types, preventing tunnel accumulation
- **localStorage Safari compatibility** — All localStorage access across 9 files wrapped in try/catch to prevent crashes in Safari private browsing mode
- **JWT expiry zombie state** — `scheduleRefresh` now triggers immediate logout with toast when token is already expired, instead of silently returning
- **WrongDataModal focus trap** — Tab key now cycles within the modal when open, preventing keyboard users from tabbing into background content
- **SSE stream deduplication** — `ConnectionHealth` components now use a shared event bus instead of each opening its own SSE stream to `/workflows/events`
- **Connector pool leak** — All 4 DB connectors (Postgres, MySQL, MongoDB, ClickHouse) now close existing pool/client in `connect()` before creating new ones, preventing connection leaks on repeated connect calls
- **Silent exceptions in sql_agent.py** — Added `logger.debug(exc_info=True)` to 13 previously silent `except` blocks in context-loading helpers, making failures diagnosable from logs
- **ConnectionHealth loading state** — Component now shows pulsing indicator during initial health check instead of immediately displaying "unknown" status
- **Accessibility** — Added `aria-label` attributes to 3 inputs in `ClarificationCard` and `MetricCatalogPanel` that only had placeholder text

### Added
- **Frontend API retry** — GET/HEAD requests automatically retry up to 2 times on network errors and 502/503/504 with exponential backoff; mutation methods (POST/PATCH/DELETE) never retry
- **TTLCache utility** — Generic TTL + LRU cache class (`app/core/ttl_cache.py`) with bounded size and time-based expiry
- **Safe storage utility** — `safe-storage.ts` module with try/catch-wrapped localStorage helpers
- **SSE event bus** — Local pub/sub (`broadcastEvent`/`onEvent`) in `sse.ts` for sharing SSE events without duplicate streams
- **Custom 404 page** — Branded `not-found.tsx` with dark theme styling and link back to home
- **Focus refresh** — `useRefreshOnFocus` hook re-fetches projects, connections, and sessions when browser tab regains focus (throttled to once per 30 seconds)

### Performance
- **Agent cache LRU eviction** — `sql_agent` and `knowledge_agent` caches now use TTLCache with max_size=128, preventing unbounded memory growth over long runtimes
- **Lazy-loaded react-markdown** — `ChatMessage.tsx` and `SQLExplainer.tsx` now use `next/dynamic` to load `react-markdown` on demand as a separate chunk

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
- **Build type error** — Fixed TypeScript build failure in ChatSessionList.tsx: added proper type assertions for metadata fields after Record<string, unknown> migration
- **Health modules auth** — /api/health/modules now requires authentication, preventing unauthenticated infrastructure reconnaissance
- **Session messages pagination** — GET /sessions/{id}/messages now supports limit/offset (default 500, max 2000) to prevent unbounded responses
- **Knowledge cache TTL** — KnowledgeAgent and SQLAgent now expire cached project knowledge after 5 minutes, preventing stale data after DB/schema updates
- **Query timeouts** — MySQL and ClickHouse connectors now enforce 120s query timeout via asyncio.wait_for, preventing pool exhaustion from long-running queries
- **Connector disconnect safety** — All 6 connectors (postgres, mysql, mongodb, clickhouse, mcp, ssh_exec) now use try/finally in disconnect() to always clear handles even when teardown throws
- **Keyboard shortcut conflict** — Removed duplicate Cmd/Ctrl+K handler from ChatInput; ChatSearch now exclusively owns the shortcut
- **Double-submit guards** — ConnectionSelector handleUpdate/handleIndexDb/handleSync and ScheduleManager toggle now prevent duplicate API calls on rapid clicks
- **useRestoreState race** — Added cancellation flag to prevent stale async restore results from overwriting store after unmount or auth change
- **ProjectSelector race** — Added sequence counter to discard out-of-order API responses when rapidly switching projects
- **Health endpoint** — /api/health now verifies DB connectivity (SELECT 1), returns 503 when database is unreachable
- **Graceful shutdown** — Indexing and sync background tasks are now cancelled during app shutdown
- **seedActiveTasks race** — useGlobalEvents checks active flag before writing to store, preventing stale seed after disconnect
- **Markdown image blocking** — ChatMessage and SQLExplainer now block markdown img tags to prevent arbitrary external image requests
- **Suggestion stale closure** — ChatPanel suggestion reset now depends on activeProject?.id, ensuring suggestions reload on project switch
- **ConnectionHealth feedback** — Reconnect failure now shows error toast instead of silently swallowing errors
- **Silent exceptions** — Added debug logging to remaining silent except blocks (WebSocket send, OpenRouter error body, tunnel introspection)
- **Input validation** — Added max_length constraints to ConnectionCreate (10+ fields) and ProjectUpdate (10 fields)
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
