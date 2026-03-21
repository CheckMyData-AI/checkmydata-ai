# CheckMyData.ai

AI-powered database query agent that analyzes Git repositories, understands database schemas, and lets you query databases through natural language chat with rich data visualization.

---

## How It Works — The Big Picture

```
┌───────────────────────────────────────────────────────────────────────┐
│                        User  (Browser)                               │
│  ┌─────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐  ┌──────┐│
│  │  Auth    │  │  Sidebar     │  │  Chat    │  │ Visualiz.  │  │Notes ││
│  │  Gate    │  │  (Projects,  │  │  Panel   │  │ (Table/    │  │Panel ││
│  │         │  │  Connections, │  │          │  │  Chart/    │  │(Saved││
│  │         │  │  SSH Keys,   │  │          │  │  Export)   │  │Quer.)││
│  │         │  │  Rules, Docs)│  │          │  │            │  │      ││
│  └────┬────┘  └──────┬───────┘  └────┬─────┘  └─────┬──────┘  └──┬───┘│
│       │              │               │              │            │    │
└───────┼──────────────┼───────────────┼──────────────┼────────────┼────┘
        │              │               │              │            │
        ▼              ▼               ▼              ▼            ▼
┌───────────────────────────────────────────────────────────────────────┐
│                    FastAPI  Backend  (Python)                         │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  API Layer  (/api/...)                                        │   │
│  │  auth · projects · connections · ssh-keys · chat · notes      │   │
│  │  repos · rules · visualizations · workflows · data-validation │   │
│  │  usage · health                                               │   │
│  └──────────────────────────┬─────────────────────────────────────┘   │
│                             │                                         │
│  ┌──────────────────────────▼─────────────────────────────────────┐   │
│  │  Multi-Agent System                                            │   │
│  │  OrchestratorAgent → routes to specialised sub-agents:        │   │
│  │    SQLAgent:       schema + SQL gen + validation + execution   │   │
│  │    VizAgent:       chart type + config (rule-based / LLM)     │   │
│  │    KnowledgeAgent: RAG search + entity info + codebase Q&A    │   │
│  │  AgentResultValidator: validates before returning to user     │   │
│  └──┬────────┬───────────┬────────────┬───────────────────────────┘   │
│     │        │           │            │                               │
│     ▼        ▼           ▼            ▼                               │
│  ┌──────┐ ┌──────────┐ ┌──────────┐ ┌────────────────────────────┐   │
│  │ LLM  │ │Knowledge │ │Connectors│ │ Workflow Tracker            │   │
│  │Router│ │  Layer   │ │(PG,MySQL,│ │ (SSE events, structured    │   │
│  │      │ │          │ │ Mongo,CH)│ │  logging, step-by-step     │   │
│  │OpenAI│ │ Git repo │ │          │ │  progress)                 │   │
│  │Anthro│ │ ChromaDB │ │SSH tunnel│ │                            │   │
│  │OpenR.│ │ Doc gen  │ │support   │ │                            │   │
│  └──────┘ └──────────┘ └──────────┘ └────────────────────────────┘   │
│                                                                       │
│  Internal Storage: SQLite (agent.db) + ChromaDB (vectors)             │
└───────────────────────────────────────────────────────────────────────┘
```

The system has **four main flows**:

1. **Setup flow**: Register/login -> add SSH keys -> create project (with Git repo) -> create database connection (with SSH tunnel) -> index repository
2. **Chat flow**: Ask a question in natural language -> the **OrchestratorAgent** routes to the appropriate sub-agent (SQLAgent for DB queries, KnowledgeAgent for codebase Q&A, or direct text response) -> VizAgent picks the best chart type for SQL results -> results returned with visualization. Uses SSE streaming with agent-level progress events. Chat history is token-budget-managed and older messages are summarized to stay within limits.
3. **Knowledge flow**: Git repo is analyzed via a multi-pass pipeline (project profiling -> entity extraction -> cross-file analysis -> enriched LLM doc generation) -> chunks stored in ChromaDB for RAG retrieval
4. **Sharing flow**: Project owner invites collaborators by email -> invited users register and are auto-accepted -> each user gets isolated chat sessions while sharing the same project data and connections

---

## User Guide — Step by Step

### 1. Installation & First Launch

```bash
# Clone and setup everything in one command
make setup       # creates venv, installs Python & Node deps, generates .env & encryption key, runs DB migrations

# Start both backend and frontend
make dev         # backend on :8000, frontend on :3100
```

Open `http://localhost:3100` in your browser.

### 2. Register / Login

When you first open the app, you see the **AuthGate** — a login/registration form.

- Enter email + password + display name to **create an account**
- Or click **"Sign in with Google"** to authenticate via your Google account (no password needed)
- Emails are normalized (lowercased, trimmed) on registration and login for case-insensitive matching
- JWT token is stored in `localStorage`, so you stay logged in across page refreshes
- Tokens include `iat` (issued-at) timestamps and are automatically refreshed before expiry (30 minutes before)
- On page load, the session is validated server-side via `GET /api/auth/me`
- Your email appears in the sidebar footer; click the **settings icon** to access account options (change password, sign out, delete account). The "Change Password" option is hidden for Google-only users since they have no local password
- Auth responses include `auth_provider` (`"email"` or `"google"`) so the frontend can adapt the UI accordingly
- Pending invite responses include `project_name` so users can distinguish which project each invite is for

**Google OAuth**: If you register with email/password first and later sign in with Google using the same email, your accounts are automatically linked. Google Sign In uses nonce-based replay protection and CSRF double-submit cookies.

**Google OAuth Setup** (required for "Sign in with Google"):

1. Go to [Google Cloud Console → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) and configure:
   - App name, user support email, developer contact email
   - Scopes: `openid`, `email`, `profile`
   - Publishing status: "Testing" (for dev) or "In production" (for public access)
2. Go to [Credentials](https://console.cloud.google.com/apis/credentials) → Create OAuth 2.0 Client ID (Web application type)
3. Under **Authorized JavaScript origins**, add every origin that loads the sign-in page:
   - `http://localhost:3100` (local development)
   - `https://checkmydata.ai` (production — replace with your actual domain)
4. Copy the **Client ID** and set it in:
   - `backend/.env` → `GOOGLE_CLIENT_ID=your-client-id`
   - `frontend/.env.local` → `NEXT_PUBLIC_GOOGLE_CLIENT_ID=your-client-id`
5. No `GOOGLE_CLIENT_SECRET` is needed — the app uses Google Identity Services (GIS) with ID-token verification, which only requires the Client ID. A client secret would only be necessary for the server-side Authorization Code flow (e.g. accessing Google Drive on behalf of users).

### 3. Add SSH Keys

Before connecting to servers, you need to register your SSH keys:

1. In the sidebar, find the **SSH Keys** section
2. Click **+ Add**
3. If you're not sure where to find your key, click **"Need help finding your SSH key?"** — an inline guide walks you through checking for existing keys, generating a new one, and copying the private key
4. Paste your **private key** (PEM format, the contents of `~/.ssh/id_ed25519` or similar)
5. Give it a **name** (e.g. "production-server")
6. Optionally enter a **passphrase** if the key is encrypted
7. Click **Save** — the system validates the key, shows its type (`ssh-ed25519`) and fingerprint

The key is encrypted at rest with AES (Fernet). The API never returns the raw private key — only metadata.

### 4. Create a Project

A **Project** groups together a Git repository, an LLM configuration, and a set of database connections.

1. In the sidebar **Projects** section, click **+ New**
2. Enter a **name** (e.g. "My Analytics")
3. Optionally set a **Git repo URL** — when you paste it, the system automatically:
   - **Detects SSH URLs** (`git@...`) and auto-selects an SSH key if only one is available
   - **Verifies access** by running `git ls-remote` in the background (debounced 800ms)
   - Shows a green **"Access verified"** badge with the branch count, or a red error
   - **Populates the branch dropdown** with all remote branches
   - **Auto-selects** `main` (or `master` if `main` doesn't exist) as the default branch
4. Optionally configure **per-purpose LLM models** under the collapsible **"LLM Models"** section (collapsed by default for new projects, expanded when editing):
   - **Indexing** — "Repo analysis & docs" — used for repository analysis and documentation generation
   - **Agent** — "Chat & reasoning" — used for the conversational agent loop, tool decisions, and answer generation
   - **SQL** — "Query generation & repair" — used for SQL query generation and repair; has a **"Use Agent model"** checkbox (checked by default) that mirrors the Agent settings
   
   Supported providers: OpenAI, Anthropic, OpenRouter. If left blank, the system default (OpenAI) is used. The active project shows all configured LLM models in a compact badge below the project name.
5. Click **Create**

The project appears in the sidebar. Click it to make it active.

### 5. Create a Database Connection

Each project can have multiple database connections. The system supports 4 database types:

| Database | Port | Connector |
|---|---|---|
| PostgreSQL | 5432 | `asyncpg` |
| MySQL | 3306 | `aiomysql` |
| MongoDB | 27017 | `motor` |
| ClickHouse | 9000 | `clickhouse-connect` |

To add a connection:

1. With a project selected, find **Connections** section, click **+ New**
2. Enter connection name and select **db type**
3. **Option A — Direct fields**: Fill in host, port, database name, username, password
4. **Option B — Connection string**: Toggle "Use connection string" and paste a full URI like `postgresql://user:pass@host:5432/dbname`
5. **SSH Tunnel** (recommended for databases accessible only via a jump server):
   - Enter SSH host IP, port (default 22), SSH user
   - Select an SSH key from the dropdown
   - The system creates an SSH tunnel automatically — the database fields should point to the *remote* host (usually `127.0.0.1:3306`)
   - No CLI tools (e.g. `mysql`, `psql`) are needed on the server — the agent connects via a native Python driver through the port-forwarded tunnel
   - The form validates that SSH user and key are set before allowing save
   - **Note:** SSH fields are hidden when "Use connection string" is enabled — SSH tunnel only works with individual host/port fields
6. **SSH Exec Mode** (alternative — use only if port forwarding is blocked):
   - Enable the **SSH Exec Mode** checkbox (appears when SSH host is configured; not available for MongoDB)
   - A command template is auto-filled based on the selected DB type; you can also select a preset or write a custom one
   - Templates use placeholders: `{db_host}`, `{db_port}`, `{db_user}`, `{db_password}`, `{db_name}`. The query is piped via stdin.
   - Optionally add **pre-commands** (one per line) — e.g., `source ~/.bashrc`, `export PATH=/opt/mysql/bin:$PATH`. Pre-commands apply to both queries and schema introspection.
   - Use this mode when: port forwarding is blocked, the DB client is only installed on the server, or custom setup commands are required
7. **Read-only mode** (checked by default) — blocks `INSERT`, `UPDATE`, `DELETE`, `DROP` queries
8. Click **Create Connection**
9. Each connection shows a **status dot** (green = connected, red = error, gray = not checked). Click **↻** to check the connection — this tests the full chain (SSH tunnel + database) in one step.

**Example — MySQL via SSH tunnel (port forwarding):**
```
SSH Host: 203.0.113.50      SSH User: ssh-user     SSH Key: "my-ssh-key"
DB Host: 127.0.0.1          DB Port: 3306          DB Name: my_database
DB User: db_readonly_user   DB Password: ****
```
The agent will SSH into `203.0.113.50`, then connect to MySQL at `127.0.0.1:3306` through the tunnel.

**Example — MySQL via SSH exec mode (CLI on server):**
```
SSH Host: 203.0.113.50      SSH User: my-agent           SSH Key: "server-ssh-key"
DB Host: 127.0.0.1          DB Port: 3306                DB Name: my_database
DB User: db_readonly_user         DB Password: ****
SSH Exec Mode: ON
Template: MYSQL_PWD="{db_password}" mysql -h {db_host} -P {db_port} -u {db_user} {db_name} --batch --raw
```
The agent will SSH into the server and execute queries via the `mysql` CLI client directly. This is equivalent to running: `ssh server 'echo "SELECT ..." | mysql ...'`

### 6. Index the Database (DB Index)

After creating and testing a database connection, you can run a **database index** to give the query agent richer context about your data:

1. Select a connection in the sidebar and make sure it shows a green status dot (test passes)
2. Click the **IDX** button that appears next to the active connection
3. The backend runs a 6-step pipeline in the background:
   - **Introspect Schema** — fetches all tables, columns, types, FKs, indexes
   - **Fetch Sample Data** — queries the 3 newest rows per table (ordered by `created_at`, `updated_at`, or PK)
   - **Load Project Knowledge** — loads code-level entity info and custom rules
   - **LLM Validation** — an LLM analyzes each table: determines if it's active, rates relevance (1-5), writes a business description, identifies data patterns, analyzes numeric column formats (currency in cents vs dollars, decimal precision, units of measurement, value ranges), and checks alignment with code
   - **Store Results** — persists the per-table index in the internal database
   - **Generate Summary** — LLM produces an overall database summary with query recommendations

4. The IDX button shows status:
   - **Gray "IDX"** — not yet indexed
   - **Amber pulsing "IDX..."** — indexing in progress
   - **Green "IDX"** — indexed (hover to see table counts and index age, e.g. "2h ago")

5. Once indexed, the query agent gains:
   - A `get_db_index` tool to look up table descriptions, relevance scores, and query hints
   - Enriched schema context injected automatically into every query
   - Knowledge of which tables are active, empty, or orphaned (exist in DB but not in code)
   - Numeric format notes per table: currency storage (cents vs whole units), decimal precision, units of measurement, value ranges
   - DB index context in the query repair loop for better SQL error recovery

6. The index can be re-triggered at any time by clicking IDX again. Stale entries for removed tables are automatically cleaned up.

**Staleness and freshness:**
- The system prompt warns the LLM when the DB index is older than the configured TTL
- The prompt notes that `get_schema_info` is always live truth while `get_db_index` is a pre-analyzed snapshot
- When project code is re-indexed, all `code_match_status` values in the DB index are flagged as "code_stale" to prevent stale cross-reference data
- Indexing status is persisted in the database (`indexing_status` field on `DbIndexSummary`) so it survives server restarts and works across multiple processes

**Configuration:**
- `DB_INDEX_TTL_HOURS` — how long before the index is considered stale (default: 24h); wired into staleness detection and system prompt warnings
- `DB_INDEX_BATCH_SIZE` — how many small/empty tables to batch per LLM call (default: 5); passed to the pipeline constructor
- `AUTO_INDEX_DB_ON_TEST` — auto-trigger indexing after a successful connection test (default: false); implemented in the test endpoint

### 7. Code-DB Sync (Code-Database Synchronization)

After both the **repository** is indexed and the **database** is indexed, you can run **Code-DB Sync** to deeply cross-reference your codebase with the database. This produces enriched per-table notes that help the query agent understand data formats and avoid interpretation errors.

1. Select a connection that has been indexed (green "IDX" badge)
2. Click the **SYNC** button that appears next to "IDX"
3. The backend runs a 6-step pipeline in the background:
   - **Load Code Knowledge** — loads entities, table usage, enums, service functions from the project knowledge cache
   - **Load DB Index** — loads pre-analyzed database schema, sample data, and column types
   - **Match Tables** — cross-references code entities and table usage with DB tables to classify each as `matched`, `code_only`, `db_only`, or `mismatch`
   - **LLM Analysis** — for each table, sends combined code + DB context to the LLM to discover data format details, conversion rules, and business logic
   - **Store Results** — persists per-table sync entries with column-level notes
   - **Generate Summary** — LLM produces project-wide data conventions and query guidelines

4. The SYNC button shows status:
   - **Gray "SYNC"** — not yet synced (or DB not indexed)
   - **Amber pulsing "SYNC..."** — sync in progress
   - **Green "SYNC"** — synced (hover to see table counts and sync age)
   - **Amber outline "SYNC"** — sync data is stale (code or DB was re-indexed since last sync)

5. Once synced, the query agent gains:
   - A `get_query_context` tool that merges table schemas, distinct enum values, conversion warnings, business rules, and code query patterns into a single compact bundle — replacing the need to call 4-6 separate tools
   - A `get_sync_context` tool to look up data format warnings, conversion rules, and query tips
   - Proactive warnings about money/currency (cents vs dollars), date formats (UTC vs local), enum values, soft-delete patterns, and boolean storage
   - A compact table map injected into the system prompt so the agent immediately knows which tables exist and their purpose
   - Enriched query repair context (sync warnings, distinct values, business rules) that helps auto-fix failed queries

6. **Staleness**: When either the repository or the database is re-indexed, sync data is automatically marked as stale. The UI shows the SYNC button with an amber outline, prompting a re-sync.

7. **Chat Readiness Gate (Status Dashboard)**: When you select a project and open a new chat, a status dashboard appears showing the actual state of each setup step with live green/grey indicators:
   - **Green dot + "Done"** for completed steps (Git repository connected, repository indexed, database connection, database indexed, code-DB synced)
   - **Grey dot** for incomplete steps, with actionable "Run" buttons for indexing/sync and navigation links for connecting repos/DBs
   - The dashboard is **cached per project** so it doesn't flash "Checking readiness..." every time you open a new chat. If everything is ready, the gate is skipped entirely and you go straight to the chat.
   - **Readiness cache invalidation**: When indexing, DB indexing, or sync completes via the sidebar or connection selector, the readiness cache is automatically cleared so the ReadinessGate shows the updated state on the next check.
   - `repo_indexed` is determined by the presence of a `CommitIndex` record (SQL database) rather than a ChromaDB vector count, making it reliable across dyno restarts on Heroku.
   - **Staleness detection**: If the repository was indexed more than 7 days ago and there are new commits, an amber warning appears: "Index is outdated (> 7 days, N new commits). Re-indexing recommended." with a one-click "Re-index" button.
   - **Vector store recovery**: If the vector store (ChromaDB) is empty but indexed documents exist in the SQL database (e.g. after a server restart on ephemeral filesystem), the indexing pipeline automatically detects this and triggers a full re-index to rebuild the vector store.
   - Shows "Last indexed X ago" and "N new commits" when applicable.
   - You can still "Chat anyway" to bypass the gate if setup is incomplete.

**What the sync discovers (examples):**
- `orders.amount` — "Stored in cents (integer). Divide by 100 for dollar values."
- `users.created_at` — "UTC timestamp, ISO 8601 format."
- `subscriptions.status` — "Enum: active | paused | cancelled | expired."
- `payments.deleted_at` — "Soft-delete pattern. Filter `WHERE deleted_at IS NULL` for active records."

### 8. Agent Learning Memory (ALM)

The agent automatically **learns from query outcomes** and accumulates per-connection knowledge that improves future queries. No manual setup required — learning happens transparently.

> **Architecture note:** In the multi-agent system, ALM lives inside `SQLAgent` (`backend/app/agents/sql_agent.py`). The orchestrator delegates database queries to `SQLAgent`, which loads learnings into its system prompt, extracts new ones post-execution, and exposes learning tools.

**How it works:**
- After every query that requires a retry (validation loop fires), the system analyzes what went wrong and what fixed it
- Lessons are extracted using zero-cost **heuristic extractors** (no LLM calls) for common patterns
- For complex sessions (3+ query attempts), an optional **LLM-based analyzer** performs deeper cross-query pattern extraction (max once per connection per hour to control cost)
- Each lesson is stored per-connection with a confidence score that grows with confirmations
- On the next query, accumulated learnings are injected into the system prompt and query context
- Usage is tracked: `times_applied` increments each time a learning is loaded for context

**What it learns automatically:**
| Category | Example | Trigger |
|---|---|---|
| Table Preference | "Use `orders_v2` not `orders_legacy` for revenue" | Agent tries table A (fails), succeeds with table B |
| Column Usage | "`amount_total` doesn't exist; use `total_amount`" | `column_not_found` error repaired |
| Data Format | "`amount` stored in cents, divide by 100" | Repair added `/ 100` division |
| Query Pattern | "Always JOIN `currencies` when querying revenue" | Repeated repair pattern / LLM analysis |
| Schema Gotcha | "`deleted_at IS NULL` required for active records" | Soft-delete filter added in repair |
| Performance Hint | "`events` table: always filter by date range" | Timeout resolved by adding filter |

**Confidence system:**
- New heuristic lessons start at 60% confidence
- Agent-recorded lessons start at 80%
- Each confirmation adds +10% (capped at 100%)
- Contradictions reduce by −30%
- **Confidence decay:** Learnings not updated in 30+ days lose 0.02 confidence per decay cycle (runs at startup). Learnings that decay below 20% are automatically deactivated
- Only lessons with ≥50% confidence appear in the system prompt

**Managing learnings:**
- A blue **LEARN** badge with count appears on connections that have accumulated learnings
- Hover over the badge for a **category breakdown tooltip** (e.g., "3 table prefs, 2 schema gotchas")
- Click the badge to open the **LearningsPanel** — view, edit, deactivate, or delete individual lessons
- **Filter by category** using the filter pills above the learnings list
- **Sort** by confidence, date, most confirmed, or most applied
- **Recompile** the learnings prompt on demand using the refresh button
- Use **Clear all** to reset the learning memory for a connection
- The agent also has `get_agent_learnings` and `record_learning` tools — it can manually record discoveries during conversations

**User feedback integration:**
- When you give a **thumbs down** on an assistant message, the system triggers a learning analysis on the failed interaction

### 8b. Agent Self-Improvement Feedback Loop

The agent has a **proactive data accuracy verification system** that goes beyond reactive thumbs-up/down feedback. It detects anomalies, asks users for validation, and builds persistent knowledge.

**Components:**

1. **Data Sanity Checker** (`backend/app/core/data_sanity_checker.py`) — Automatic checks on every query result before presenting to users:
   - All-null / all-zero column detection
   - Future date anomalies
   - Percentage sum validation (should add to ~100%)
   - Benchmark comparison (deviations from verified values)

2. **Session Notes (Agent Working Memory)** (`backend/app/services/session_notes_service.py`) — Persistent per-connection notes that the agent uses across sessions. Categories: data_observation, column_mapping, business_logic, calculation_note, user_preference, verified_benchmark. Fuzzy deduplication prevents redundant notes.

3. **Data Validation Feedback** (`backend/app/services/data_validation_service.py`) — Structured user feedback beyond thumbs up/down:
   - **Confirmed** — data is correct, creates a benchmark
   - **Approximate** — close enough, creates benchmark + observation note
   - **Rejected** — incorrect, creates learning + note + flags stale benchmarks

4. **Benchmark Store** (`backend/app/services/benchmark_service.py`) — Stores verified metric values (e.g., "Monthly Revenue ≈ $50,000") for sanity-checking future queries. Confidence grows with confirmations, decays when flagged stale.

5. **Feedback Pipeline** (`backend/app/services/feedback_pipeline.py`) — Processes validation feedback → creates learnings, notes, and benchmarks automatically.

6. **Structured Clarification** — The orchestrator can ask structured questions (yes/no, multiple choice, numeric, free text) via the `ask_user` tool, rendered as `ClarificationCard` in the UI.

**"Wrong Data" Investigation Cycle:**

When a user clicks the **"Wrong Data" button** (warning triangle icon) on any SQL result message:
1. **Collect** — User selects complaint type (numbers too high/low, wrong time period, missing data, wrong categories) and optionally provides expected value and problematic column
2. **Investigate** — `InvestigationAgent` runs diagnostic queries, checks column formats, compares results, identifies root cause (missing filter, wrong JOIN, data format, aggregation error)
3. **Present Fix** — Shows original vs corrected results side-by-side with diff highlighting, root cause explanation, and corrected SQL
4. **Confirm** — User accepts the fix (triggers memory updates: learnings, notes, benchmarks, sync enrichments) or rejects to re-investigate

**Enhanced Code-DB Sync:**

The Code-DB Sync pipeline now extracts additional intelligence from the codebase:
- **Query Patterns** — WHERE/filter conditions found in code (e.g., `transactions WHERE status = 1`)
- **Constant Mappings** — Status/flag constants (e.g., `STATUS_ACTIVE = 1`, `STATUS_PENDING = 0`)
- **Scope Filters** — ORM scopes/managers defining default filters (Rails scopes, Django managers, Laravel scopes)
- **Required Filters** — Per-table mandatory WHERE conditions the SQL agent must always apply
- **Column Value Mappings** — Integer-to-meaning maps (e.g., status: 0=pending, 1=processed, 2=failed)

These are stored in `code_db_sync.required_filters_json` and `code_db_sync.column_value_mappings_json`, and injected into the SQL agent's system prompt as critical warnings.

**Project Knowledge Overview:**

A unified "Agent Briefing" document (`ProjectOverviewService`) that synthesizes all knowledge sources into a single, compact markdown summary (~500–1000 tokens). Automatically regenerated after DB indexing, Code-DB sync, repo indexing, and custom rule changes. Contents:
- **Database Structure** — table count, key tables with row counts, DISTINCT values for categorical columns
- **Data Conventions** — from Code-DB sync: required filters, column value mappings, conversion warnings
- **Custom Rules** — rule names with one-line descriptions
- **Agent Learnings** — counts by category, top high-confidence lessons
- **Session Notes & Benchmarks** — verified metric values, note category counts
- **Repository Profile** — language, frameworks, ORMs, key directories

Stored in `project_cache.overview_text` and injected into the orchestrator's system prompt for better routing decisions. Also available to the SQL agent via `get_db_index(scope="project_overview")`.

**Expanded DISTINCT value collection:**

During DB indexing, DISTINCT values are now collected more broadly:
- **Name heuristics** — 40+ pattern names (`status`, `type`, `region`, `locale`, `direction`, `protocol`, etc.) plus prefixes (`is_`, `has_`, `can_`, `allow_`) and suffixes (`_flag`, `_bool`, `_yn`, `_code`)
- **Type-based** — `tinyint`, `smallint`, `int2` types are always collected (likely hold flags/status codes)
- **Sample-data-driven** — Columns with <= 3 distinct values in sample rows (catches unlabeled flag columns like `processed: 0, 1`)
- DISTINCT values are included in `table_index_to_detail` output for the SQL agent

**Frontend components:** `ClarificationCard`, `DataValidationCard`, `VerificationBadge`, `WrongDataModal`, `InvestigationProgress`, `ResultDiffView` (all in `frontend/src/components/chat/`)

**API endpoints** (prefix `/api/data-validation/`):
- `POST /validate-data` — Record user validation feedback
- `GET /validation-stats/{connection_id}` — Aggregated accuracy statistics
- `GET /benchmarks/{connection_id}` — All verified benchmarks
- `POST /investigate` — Start "Wrong Data" investigation
- `GET /investigate/{id}` — Poll investigation progress
- `POST /investigate/{id}/confirm-fix` — Accept or reject investigation fix

### 9. Index the Repository (Knowledge Base)

If your project has a Git repo URL configured:

1. Click the **Index Repository** button in the sidebar
2. The backend immediately returns `202 Accepted` with a `workflow_id` and runs the pipeline as a background task (avoids Heroku's 30s request timeout)
3. The **WorkflowProgress** component shows each step in real-time via SSE:
   - `SSH Key` — Decrypting SSH key for Git access
   - `Git Clone/Pull` — Cloning or pulling the repo
   - `Detect Changes` — Computing which files changed since last index (per-branch)
   - `Cleanup Deleted` — Removing docs/chunks for files deleted from the repo
   - `Analyze Files` — Parsing ORM models (11 ORMs supported), migrations, SQL files
   - `Project Profile` — Auto-detecting framework, ORM, language, directory structure
   - `Cross-File Analysis` — Building entity map, table usage, enums, dead table detection
   - `Generate Docs` — LLM creates enriched documentation with cross-file context
   - `Store Vectors` — Stale chunks cleaned, new chunks stored in ChromaDB
   - `Record Index` — Saving the commit SHA + branch for incremental indexing

After indexing, the **Knowledge Docs** section in the sidebar shows all indexed documents (including a project-level summary). You can click any doc to view its generated content.

**Incremental indexing**: Re-indexing only processes files that changed since the last indexed commit. Cross-file analysis is also incremental — `ProjectKnowledge` is persisted between runs so only changed/deleted files are re-scanned. `ProjectProfile` is cached and only re-detected when marker files (e.g. `package.json`, `requirements.txt`) change. Indexing is per-project locked — rapid clicks are rejected with 409.

**Resumable indexing**: If the pipeline is interrupted (crash, deploy, timeout, LLM error), the next "Index Repository" click **automatically resumes** from the last completed step. Intermediate state is stored in the `indexing_checkpoint` table:
- Completed pipeline steps (SSH key, clone, detect changes, profile, etc.) are skipped on resume
- Each successfully generated doc is recorded per-file — the expensive `generate_docs` step (LLM calls per file) skips already-processed documents
- The checkpoint stores cached `ProjectProfile` and `ProjectKnowledge` to avoid re-computation
- On successful completion, the checkpoint is deleted (no garbage accumulation)
- `force_full=true` discards any existing checkpoint and starts fresh
- Stale checkpoints (>24h) are automatically cleaned up on app startup

**Check for updates**: Click the "Check" button next to "Index Repository" to fetch remote and see how many new commits are available without starting a full re-index.

**Staleness detection**: When chatting, the orchestrator automatically compares the last indexed commit with the current repo HEAD. If the knowledge base is behind, a warning badge appears on the assistant's response.

**Multi-pass pipeline**: The indexing runs 5 passes to understand the project holistically, not just per-file.

### 10. Active Tasks Widget (Header)

A real-time **Active Tasks** indicator appears in the top-right corner of the header whenever background operations are running:

1. The widget **automatically appears** when any background task starts (repository indexing, database indexing, or code-DB sync) and **disappears** when all tasks finish
2. **Collapsed state** — a small pill showing a spinner and task count (e.g. "2 tasks"). Click to expand.
3. **Expanded dropdown** — shows each task with:
   - Pipeline type icon and label (Repository Indexing, Database Indexing, Code-DB Sync)
   - Target name (project or connection)
   - Current step in progress (e.g. "Analyzing files...", "LLM Analysis")
   - Live elapsed time
   - Status indicator: blue spinner (running), green check (completed), red X (failed)
4. **Completed** tasks show briefly with a green check and auto-dismiss after 5 seconds
5. **Failed** tasks show the error message, stay visible for 30 seconds (or click dismiss to clear immediately)
6. If any task has failed, the pill turns red to draw attention
7. On page refresh, the widget queries `GET /api/tasks/active` to rediscover any tasks that were already running

The widget uses the same SSE event stream as the Activity Log (`GET /api/workflows/events`) for real-time updates.

### 11. Activity Log (Bottom Panel)

A real-time **Activity Log** panel is available at the bottom of the screen:

1. Click the **"Log"** button in the bottom-right corner to open it. This button is **always visible** — even when the Readiness Gate is displayed, when there is no chat input, or when no keyboard is present. It appears as a persistent floating button at the bottom-right of the content area.
2. The panel shows a live stream of ALL backend events across all pipelines:
   - **Indexing** (purple) — SSH key, git clone/pull, file analysis, doc generation, vector storage
   - **DB Indexing** (emerald) — schema introspection, sample fetching, LLM table analysis, summary
   - **Code-DB Sync** (teal) — knowledge loading, table matching, per-table LLM analysis, summary
   - **Query** (cyan) — schema introspection, SQL generation, execution, validation, repair
   - **Agent** (amber) — LLM calls, tool execution, knowledge search
3. Each log line shows: timestamp, pipeline, step name, status, detail, and elapsed time
4. All three pipelines (repo indexing, DB indexing, code-DB sync) emit **granular intermediate progress** events within each step, showing per-file/per-table/per-batch progress so you can track exactly where the pipeline is and identify where issues occur
5. The panel auto-scrolls to the latest entry. A badge shows unread count when closed.
6. Use **Clear** to reset the log, **Close** to hide the panel.
7. An additional toggle button also appears inside the chat input area (when visible).

The log connects via SSE to `GET /api/workflows/events` (global mode, no workflow filter).

### 12. Chat — Ask Questions

With a project selected (and optionally a connection):

1. Open a chat session (or create one via the session list in the sidebar)
2. Type your question in natural language. The **OrchestratorAgent** routes to the right sub-agent:

   **Data questions** (requires a database connection):
   - _"How many active plans were created last month?"_
   - _"Show me the top 10 users by transaction volume"_
   - _"What's the average order value by country?"_

   **Knowledge questions** (uses indexed Git repository):
   - _"How does the authentication flow work?"_
   - _"What ORM models define the users table?"_
   - _"Where are the migration files?"_

   **Conversational** (no tools needed):
   - _"Hi, what can you help me with?"_
   - _"Can you explain that result in more detail?"_
   - _"Thanks, that's very helpful"_

3. The agent decides which sub-agent to delegate to based on the question:

```
Your question
    ↓
[OrchestratorAgent] — LLM with meta-tools decides routing
    ↓
├── Data question → query_database → SQLAgent → VizAgent
│   SQLAgent: gather context → generate SQL → validation loop → execute
│   VizAgent: rule-based or LLM chart type selection
│     Supports `group_by` pivoting for multi-series charts (e.g. revenue by source over time)
│     Config keys are normalised so both LLM-style (x/y) and canonical (labels_column/data_columns) work
│     Auto-detects column types (numeric/temporal/categorical) and generates proper viz_config
│     Case-insensitive column matching with fallback to auto-detection when LLM config is wrong
│     NULL values in chart data are replaced with 0 (bar/line/pie) or skipped (scatter)
│   ↓
│   [Validation Loop] — Pre-validate → Safety check → EXPLAIN → Execute
│   ↓  (if error: Classify → Enrich → Repair → retry, up to 3 attempts)
│   Results + visualization config
│
├── Knowledge question → search_codebase → KnowledgeAgent
│   ↓
│   Returns answer with source citations
│
├── Rule management → manage_rules (handled directly by orchestrator)
│   ↓
│   Creates/updates/deletes a project rule, sidebar refreshes
│
└── Conversation → responds directly (no sub-agent calls)
```

4. Each assistant message shows:
   - The **answer** rendered as **Markdown** (headings, lists, bold, code blocks, links, tables) via `react-markdown`
   - The **SQL query** that was executed
   - **Metadata badges**: execution time, row count, visualization type, token usage
   - **Thumbs up/down feedback** buttons to rate answer quality
   - A **"show details"** expander with:
     - **Code Context** — which RAG documents were used (with similarity scores)
     - **Attempt History** — full retry details if validation loop triggered
     - **Token Usage** — prompt, completion, and total tokens consumed
   - A **table or chart** with the data, plus a **Visual / Text toggle** to switch between the rendered visualization and a DataTable showing raw query results
   - A **Viz Type Toolbar** on SQL result messages (when raw data is available) — switch between Table, Bar, Line, Pie, and Scatter views without re-querying the database. The toolbar calls `/api/visualizations/render` with the stored raw data to produce a new chart type on the fly.
   - **Export buttons** to download as CSV, JSON, or XLSX
5. **Session titles** are auto-generated by the LLM after the first response
6. **Identical queries** are served from a short-lived cache (2-minute TTL) to avoid re-executing the same SQL
7. **Chat persistence** — your active project, connection, and session survive page refreshes. Visualization data (charts, tables), raw tabular data, and all message metadata are stored in the database so you can return to any past chat session and see it exactly as it was, including rendered charts and data tables. Thumbs up/down ratings, tool call history, and query explanations are all preserved.
8. **Re-visualization** — when you ask the agent to "show that as a pie chart" or "make it a bar chart," the agent sees the prior SQL query, columns, and visualization type from the enriched chat history and can re-execute the query with the requested chart type. The `[Context]` block appended to assistant messages in history gives the agent full awareness of prior data.
9. **Chat-based rule creation** — you can ask the agent to remember conventions, create rules, or save guidelines directly from the chat. For example:
   - _"Remember that orders.amount is stored in cents — always divide by 100"_
   - _"Create a rule: always filter by deleted_at IS NULL for active records"_
   - _"Update the cents rule to say divide by 1000 instead"_
   
   The agent uses the `manage_custom_rules` tool to create, update, or delete project rules. After a rule is created/modified, the sidebar Rules section refreshes automatically. Only project **owners** can manage rules via chat (consistent with the sidebar RBAC). The `rules_changed` flag in the chat response triggers the frontend refresh.

### 13. Custom Rules

Rules inject additional context into the LLM prompt, guiding how queries are built:

- **File-based rules**: Place `.md` or `.yaml` files in `./rules/` directory
- **DB-based rules**: Create via the **Rules** section in the sidebar
- **Default rule**: Every new project is automatically created with a comprehensive **"Business Metrics & Guidelines"** rule that teaches the agent how to calculate common metrics:
  - Revenue (GMV, net revenue, AOV, ARPU, MRR, LTV)
  - ROI & profitability (ROAS, CAC, profit margin, payback period)
  - Traffic sources (source/medium, UTM attribution, organic vs paid)
  - Payment methods (breakdown, success/failure rates, refund rates)
  - User engagement (DAU/MAU, session duration, retention)
  - Conversion funnel (step-by-step drop-off, cart abandonment)
  - Churn & retention (monthly churn, cohort retention, reactivation)
  - Date/time conventions and general query guidelines

  The default rule is fully **editable** — customize it to match your project's specific schema and business logic. It can also be **deleted**, but once deleted it will not be re-created automatically.

  Existing projects that had no custom rules receive the default rule automatically on the next app startup (one-time backfill).

Example custom rules:
- _"The `created_at` field uses UTC timestamps. Always convert to user timezone."_
- _"Revenue = price × quantity − discount. Always use this formula."_
- _"Table `legacy_users` is deprecated. Use `users_v2` instead."_

Rules can be **global** or **project-scoped**.

### 14. Editing & Managing

- **Edit project**: Hover over a project and click the ✎ icon — change name, repo, LLM config
- **Edit connection**: Hover over a connection and click the ✎ icon — update host, credentials
- **Delete**: Click the × icon (projects, connections, SSH keys, rules, chat sessions)
- **SSH key protection**: Deleting a key that is used by a project or connection returns a 409 error

### 15. Sharing a Project (Email Invite System)

Project owners can invite other users to collaborate on a project via email:

1. **Invite a collaborator**: In the sidebar, hover over a project you own and click the 👥 icon. Enter their email address and select a role (**Editor** or **Viewer**), then click **Invite**.

2. **Roles**:
   - **Owner** — Full CRUD on project, connections, rules, invites. Can delete the project.
   - **Editor** — Can chat with the database, trigger re-indexing, manage their own sessions. Cannot modify project settings or connections.
   - **Viewer** — Can chat (query the database) and view connections. Same session isolation.

3. **How it works**:
   - When the invited user **registers** with the invited email, they are automatically added to the project with the specified role.
   - If the user already has an account, they can **accept the invite** from the "Pending Invitations" section that appears in the sidebar.
   - Each user has **their own isolated chat sessions** — they cannot see other users' conversation history.
   - All users share the **same project data**: connections, indexed knowledge base, and custom rules.

4. **Managing access**:
   - **Revoke** a pending invite before it's accepted
   - **Remove** a member (owners cannot be removed)
   - **View** all current members and their roles in the InviteManager panel

### 16. Saved Queries (Notes Panel)

The **Notes** panel lets you save SQL queries from agent responses for quick reference and re-execution. Each saved note now stores the **complete context** — SQL query, raw data, agent's answer text, and visualization config.

1. **Save a query**: When the agent returns SQL results, click the **bookmark icon** (🔖) next to the thumbs up/down feedback buttons. The following are saved:
   - SQL query
   - Raw result data (columns, rows, row count)
   - Agent's textual answer/interpretation
   - Visualization configuration (chart type, settings)
   - Title (auto-generated from the first line of the answer)

2. **View notes**: Click the **bookmark button** in the header bar (top-right) to toggle the Notes panel on the right side. The panel shows all saved queries for the active project, sorted by most recently updated. Each card shows:
   - Title and time since last execution
   - Visualization type badge (e.g. "bar_chart", "table") when applicable
   - Collapsible **Agent Response** section with the full answer text
   - Collapsible **SQL Query** section with copy button
   - Collapsible **Result** section with data table

3. **Refresh data**: Each saved note has a **🔄 Refresh** button (with label). Clicking it re-runs the SQL query against the original database connection and updates the stored result. This is useful for monitoring queries that you check regularly.

4. **Edit & manage**:
   - Click on a note's comment area to **add or edit a comment** — useful for annotating what the query does
   - Expand **Agent Response** to see the full answer text the agent gave
   - Expand **SQL Query** to view and **copy** the full SQL
   - Expand **Result** to see the data table (last 20 rows shown inline)
   - Click the **trash icon** to delete a saved note (with confirmation)

5. **How it works**:
   - Notes are **per-user, per-project** — each user has their own saved queries
   - The panel state (open/closed) persists in localStorage
   - Saved queries store the connection ID so re-execution uses the correct database
   - Results are capped at 500 rows to keep storage manageable
   - `answer_text` and `visualization_json` columns store the complete agent context

**API endpoints**: `POST /api/notes`, `GET /api/notes?project_id=X`, `GET /api/notes/{id}`, `PATCH /api/notes/{id}`, `DELETE /api/notes/{id}`, `POST /api/notes/{id}/execute`

---

## Architecture Deep Dive

This section is the authoritative reference for how every major flow works in code. It covers connection creation, the multi-agent chat pipeline, indexing, MCP integration (client and server), and a step-by-step extension protocol for adding new data sources and agents.

---

### 1. Connection Flow (End-to-End)

Every data source the system can talk to is represented by a `Connection` row. The flow from the user clicking "Create" to a usable `ConnectionConfig` at runtime is:

```
Frontend Form (ConnectionSelector.tsx)
    │
    │  POST /api/connections
    ▼
API Route — ConnectionCreate Pydantic validator
    │         validates required fields per db_type
    │         sets source_type = "mcp" for MCP connections
    ▼
ConnectionService.create()
    │  encrypts: db_password, connection_string, mcp_env
    │  JSON-serializes: mcp_server_args (list → JSON string)
    ▼
Connection ORM model → SQLite / PostgreSQL
```

At runtime, when the system needs to actually connect, it calls `ConnectionService.to_config(session, conn)`, which reverses the process — decrypting secrets and deserializing JSON back into a `ConnectionConfig` dataclass. For MCP connections, all MCP-specific fields are placed into `ConnectionConfig.extra`.

**Supported source types:**

| `source_type` | `db_type` values | Adapter class | Transport |
|---|---|---|---|
| `database` | `postgres`, `mysql`, `mongodb`, `clickhouse` | `PostgresConnector`, `MySQLConnector`, `MongoDBConnector`, `ClickHouseConnector` | Native driver (+ optional SSH tunnel) |
| `mcp` | `mcp` | `MCPClientAdapter` | stdio or SSE to external MCP server |

**Key files:**

| File | What it does |
|---|---|
| `frontend/src/components/connections/ConnectionSelector.tsx` | Renders form; `DB_TYPES` array controls the dropdown; conditional rendering shows MCP fields (transport type, command/args or URL, env vars JSON) when `db_type === "mcp"`, and hides DB/SSH fields |
| `backend/app/api/routes/connections.py` | `ConnectionCreate` Pydantic model with `@model_validator` — when `db_type == "mcp"`, requires either `mcp_server_command` (stdio) or `mcp_server_url` (SSE) and forces `source_type = "mcp"` |
| `backend/app/services/connection_service.py` | `create()` encrypts secrets and serializes lists; `to_config()` decrypts and builds `ConnectionConfig` with `extra` dict for MCP fields |
| `backend/app/models/connection.py` | ORM model with both database fields (`db_host`, `db_port`, etc.) and MCP fields (`mcp_server_command`, `mcp_server_args`, `mcp_server_url`, `mcp_transport_type`, `mcp_env_encrypted`) |
| `backend/app/connectors/base.py` | `ConnectionConfig` dataclass — the runtime config passed to adapters; `extra: dict` carries source-type-specific data |

**MCP connection fields on the `Connection` model:**

| Column | Type | Purpose |
|---|---|---|
| `mcp_server_command` | `Text` | Executable to spawn for stdio transport (e.g. `npx`, `python`) |
| `mcp_server_args` | `Text` | JSON-serialized `list[str]` of CLI arguments |
| `mcp_server_url` | `String(1024)` | URL for SSE transport |
| `mcp_transport_type` | `String(50)` | `"stdio"` or `"sse"` |
| `mcp_env_encrypted` | `Text` | Fernet-encrypted JSON `dict[str, str]` of env vars passed to the MCP subprocess |

---

### 2. Chat / Agent Orchestration Flow

When a user sends a question, the request travels through a multi-agent pipeline. The `OrchestratorAgent` is the central coordinator that uses LLM tool calling to decide which sub-agent handles the question.

**Request path:**

```
User sends question
    │
    │  POST /api/chat/ask  (or /ask/stream for SSE)
    ▼
Chat route (chat.py)
    │  loads ConnectionConfig from connection_id
    │  creates/fetches ChatSession, adds user message, loads history
    ▼
ConversationalAgent (core/agent.py)
    │  builds AgentContext, delegates to:
    ▼
OrchestratorAgent.run(context)
    │
    │  1. Trim chat history (token-budget-aware summarization)
    │  2. Check project state:
    │     has_connection = context.connection_config is not None
    │     has_kb = ChromaDB collection has documents
    │     has_mcp = any Connection with source_type == "mcp" in project
    │  3. Build table_map from DB index (if connection exists)
    │  4. Build system prompt with current date/time and meta-tools list
    │  5. Enter orchestrator LLM loop (max 5 iterations)
    ▼
┌──────── Orchestrator LLM Loop ────────┐
│                                        │
│  LLM receives the system prompt and   │
│  available meta-tools. It decides:     │
│                                        │
│  query_database  → _handle_query_database()  → SQLAgent.run()
│                    SQLAgent validates results with AgentResultValidator
│                    If SQL results exist → VizAgent.run() picks chart type
│                                                                  │
│  search_codebase → _handle_search_codebase() → KnowledgeAgent.run()
│                    Results validated before returning             │
│                                                                  │
│  manage_rules    → _handle_manage_rules()                        │
│                    Direct CRUD (no sub-agent)                    │
│                                                                  │
│  query_mcp_source → _handle_query_mcp_source()                   │
│                     Connects MCPClientAdapter → MCPSourceAgent.run()
│                     Disconnects adapter after completion         │
│                                                                  │
│  text response   → exit loop                                    │
│                                                                  │
│  Tool results are appended as tool messages.                     │
│  Loop continues until LLM responds without tool calls.           │
└────────────────────────────────────────┘
    │
    ▼
AgentResponse
    (answer, query, results, viz_type, viz_config,
     knowledge_sources, token_usage, tool_call_log)
```

**How meta-tools are selected** (`agents/tools/orchestrator_tools.py`):

The function `get_orchestrator_tools()` accepts three booleans and returns only the tools relevant to the current project state:

| Condition | Tools included |
|---|---|
| `has_connection = True` | `query_database`, `manage_rules` |
| `has_knowledge_base = True` | `search_codebase` |
| `has_mcp_sources = True` | `query_mcp_source` |

The LLM itself decides which tool to call based on the user's question — there is no hardcoded routing logic. If no tools are available, the LLM responds conversationally.

**Sub-agent retry logic:**

All three sub-agent handlers (`_handle_query_database`, `_handle_search_codebase`, `_handle_query_mcp_source`) retry up to `MAX_SUB_AGENT_RETRIES` (1 extra attempt) on transient failures. `AgentRetryableError` and retryable `LLMError` subclasses trigger retries with backoff. `AgentFatalError` and non-retryable LLM errors (auth, token limit) abort immediately.

**LLM error handling architecture (`llm/errors.py`):**

Provider-specific exceptions (openai, anthropic, httpx) are caught in each adapter and re-raised as a unified error hierarchy:

| Error class | Retryable | Trigger |
|---|---|---|
| `LLMRateLimitError` | Yes (5s backoff) | 429 from any provider |
| `LLMServerError` | Yes (2s backoff) | 5xx from any provider |
| `LLMTimeoutError` | Yes (2s backoff) | Request timeout |
| `LLMConnectionError` | Yes (2s backoff) | Network failure |
| `LLMAuthError` | No | 401/403, bad API key |
| `LLMTokenLimitError` | No | Context/output token limit exceeded |
| `LLMContentFilterError` | No | Content policy refusal |
| `LLMAllProvidersFailedError` | Yes (3s) | Every provider in the fallback chain failed |

The `LLMRouter` retries each provider up to 3 times with exponential backoff before falling through to the next provider. Non-retryable errors (auth, token limit) skip retries and immediately try the next provider. The `OrchestratorAgent` adds a second retry layer around the router call itself, and maps all LLM errors to user-friendly messages (e.g., "The AI service is temporarily overloaded" instead of raw stack traces).

**Resource management & resilience:**

- **MCP adapter cleanup** — `_handle_query_mcp_source` wraps the entire adapter lifecycle (connect → work → disconnect) in a `try/finally` block. The `disconnect()` call is itself wrapped in a safety `try/except` so a disconnect failure never masks the real error.
- **External call retry** — `ConnectionService.test_connection()` retries `connector.connect()` up to 3 times with exponential backoff for transient errors (`TimeoutError`, `ConnectionError`, `OSError`). The MCP pipeline's `adapter.connect()` uses the same retry pattern.
- **Pipeline failure cleanup** — `IndexingPipelineRunner.run()` catches exceptions from the entire step pipeline, marks the checkpoint as `pipeline_failed`, emits a tracker failure event, and returns a result with `status="failed"` instead of propagating the exception.
- **Streaming fallback safety** — `LLMRouter.stream()` tracks whether any tokens have been yielded. If the provider stream fails *after* tokens were sent, it raises immediately (to avoid duplicate/corrupted output). Fallback to the next provider only happens if the failure occurs before any tokens are yielded.
- **Streaming timeout** — The SSE endpoint (`/ask/stream`) wraps the agent task in `asyncio.wait_for()` with a 120-second timeout. On timeout, a structured error event is sent and the stream closes gracefully. An inner safety timeout (150s) in the event loop itself prevents indefinite hangs even if `pipeline_end` is lost.
- **Structured SSE error events** — Error events sent via SSE include `error_type`, `is_retryable`, and `user_message` fields so the frontend can display appropriate UI (retry buttons for retryable errors, no retry for permanent ones like auth or content policy violations).
- **Error toast duration** — Error toasts persist for 10 seconds (vs. 4 seconds for success/info) to ensure users can read the message.
- **Tracker failure isolation** — All `_tracker.end()` calls in orchestrator error handlers are wrapped in `try/except` so a tracker broadcast failure never prevents the `AgentResponse` from being returned to the user.
- **Sub-agent error containment** — All sub-agent handlers (`_handle_query_database`, `_handle_search_codebase`, `_handle_manage_rules`, `_handle_query_mcp_source`) catch exceptions and return error strings as tool results to the LLM, preventing tool dispatch failures from crashing the orchestrator loop.
- **Degraded context warnings** — When context helpers (`_has_mcp_sources`, `_build_table_map`, `_check_staleness`) fail, the orchestrator emits `orchestrator:warning` events via SSE so users can see that certain features are temporarily unavailable.
- **LLM adapter timeouts** — All three LLM adapters (OpenAI, Anthropic, OpenRouter) have explicit request timeouts (90s for OpenAI/Anthropic, 120s for OpenRouter) to prevent stuck provider calls from blocking the orchestrator indefinitely.

**Result validation:**

Every sub-agent result passes through `AgentResultValidator` before being returned:
- SQL results: checks for error status, empty results, query presence
- Knowledge results: checks for answer presence, source quality
- Viz results: checks config validity, falls back to `bar_chart` or `table` on warnings

**Key files:**

| File | What it does |
|---|---|
| `backend/app/api/routes/chat.py` | HTTP endpoint, session management, history loading |
| `backend/app/core/agent.py` | `ConversationalAgent` — thin wrapper that builds `AgentContext` and calls `OrchestratorAgent.run()` |
| `backend/app/agents/orchestrator.py` | `OrchestratorAgent.run()` (the main loop), `_handle_meta_tool()` dispatch, `_has_mcp_sources()` check |
| `backend/app/agents/tools/orchestrator_tools.py` | `get_orchestrator_tools()` — conditional tool list, tool definitions (`QUERY_DATABASE_TOOL`, `SEARCH_CODEBASE_TOOL`, `MANAGE_RULES_TOOL`, `QUERY_MCP_SOURCE_TOOL`, `ASK_USER_TOOL`) |
| `backend/app/agents/sql_agent.py` | `SQLAgent` — schema introspection, SQL generation, validation loop, execution, learning extraction, sanity checks, session notes |
| `backend/app/agents/viz_agent.py` | `VizAgent` — rule-based + LLM chart type selection, auto-generates viz_config, validates column references |
| `backend/app/agents/knowledge_agent.py` | `KnowledgeAgent` — RAG search, entity info, codebase Q&A |
| `backend/app/agents/mcp_source_agent.py` | `MCPSourceAgent` — LLM loop for external MCP tool calls |
| `backend/app/agents/investigation_agent.py` | `InvestigationAgent` — diagnoses data accuracy issues with diagnostic queries |
| `backend/app/agents/validation.py` | `AgentResultValidator` — validates sub-agent outputs |

**Agent hierarchy:**

| Agent | Location | Responsibility | Triggered by |
|---|---|---|---|
| **OrchestratorAgent** | `agents/orchestrator.py` | Routes questions, composes final response, manages VizAgent | Every chat request |
| **SQLAgent** | `agents/sql_agent.py` | Schema context, SQL gen, validation loop, execution, learnings | `query_database` meta-tool |
| **VizAgent** | `agents/viz_agent.py` | Chart type selection (rule-based + LLM fallback), config gen | Auto-runs after SQLAgent returns results |
| **KnowledgeAgent** | `agents/knowledge_agent.py` | RAG search, entity info, codebase Q&A | `search_codebase` meta-tool |
| **MCPSourceAgent** | `agents/mcp_source_agent.py` | Queries external MCP servers via MCPClientAdapter | `query_mcp_source` meta-tool |
| **InvestigationAgent** | `agents/investigation_agent.py` | Diagnoses data accuracy issues, runs diagnostic queries, identifies root causes | "Wrong Data" button / investigation API |

**Agent communication protocol (`agents/base.py`):**

- All agents implement `BaseAgent` with `async def run(context: AgentContext, **kwargs) -> AgentResult`
- `AgentContext` carries: `project_id`, `connection_config`, `user_question`, `chat_history`, `llm_router`, `tracker`, `workflow_id`, `user_id`, LLM model preferences, and an `extra` dict
- Each agent returns a typed `AgentResult` subclass (`SQLAgentResult`, `KnowledgeResult`, `VizResult`, `MCPSourceResult`)
- Token usage is accumulated via `BaseAgent.accum_usage()` and summed into the orchestrator's `total_usage`
- Errors are classified via the `agents/errors.py` hierarchy: `AgentRetryableError` (can retry), `AgentFatalError` (abort), `AgentValidationError` (data issue)

---

### 3. Indexing Flows

The system has three independent indexing pipelines: **repository indexing** (Git + ChromaDB), **database indexing** (schema + LLM analysis), and **MCP tool schema indexing**. Each operates on a different data source type and stores results in different backends.

#### 3a. Repository Indexing (Knowledge Base)

Covered in detail in the User Guide section "Index the Repository." This is the multi-pass pipeline: project profiling, entity extraction, cross-file analysis, LLM doc generation, and ChromaDB vector storage. Triggered via `POST /api/repos/{project_id}/index`.

#### 3b. Database Indexing

Triggered via `POST /api/connections/{connection_id}/index-db`. Runs `DbIndexPipeline` as a background task:

```
Trigger: POST /{connection_id}/index-db
    │
    ▼
_run_db_index_background() — background task
    │  uses DbIndexPipeline (knowledge/db_index_pipeline.py)
    ▼
Step 1: Connect via get_connector(db_type) → introspect schema
Step 2: Fetch sample data (3 newest rows per table)
Step 3: Load code context + custom rules
Step 4: LLM validation per table (active?, relevance 1-5, description, patterns)
Step 5: Persist via DbIndexService → db_index + db_index_summary tables
Step 6: LLM generates overall database summary + recommendations
```

Results are stored in the internal database (`db_index`, `db_index_summary` tables) and made available to the SQLAgent through the `get_db_index` and `get_query_context` tools.

#### 3c. MCP Tool Schema Indexing

`MCPPipeline` (`pipelines/mcp_pipeline.py`) handles indexing for MCP data sources. It connects to the external MCP server, discovers its tools, and stores the schemas in the project's ChromaDB collection:

```
MCPPipeline.index(source_id, context)
    │
    ▼
Connect via MCPClientAdapter → list_tools()
    │  gets tool names, descriptions, input schemas
    ▼
Format each tool as a text document:
    "MCP Tool: {name}\nDescription: {desc}\nInput Schema: {json}"
    │
    ▼
Upsert into ChromaDB collection for project
    with metadata: source="mcp:{conn_name}", type="mcp_tool_schema"
```

#### 3d. Pipeline Plugin System

All indexing pipelines implement the `DataSourcePipeline` abstract base class (`pipelines/base.py`):

```python
class DataSourcePipeline(ABC):
    source_type: str                                    # matches Connection.source_type
    async def index(source_id, context) -> PipelineResult
    async def sync_with_code(source_id, context) -> PipelineResult
    async def get_status(source_id) -> PipelineStatus
    def get_agent_tools() -> list[Tool]
```

Pipelines are registered in `PIPELINE_REGISTRY` (`pipelines/registry.py`):

| `source_type` | Pipeline class | What it indexes |
|---|---|---|
| `database` | `DatabasePipeline` | Wraps `DbIndexPipeline` + `CodeDbSyncPipeline` |
| `mcp` | `MCPPipeline` | MCP tool schemas into ChromaDB |

Use `get_pipeline(source_type)` to instantiate a pipeline, or `register_pipeline(source_type, cls)` to add a new one at runtime.

**Key types:**

| Type | Location | Purpose |
|---|---|---|
| `PipelineContext` | `pipelines/base.py` | Carries `project_id`, `workflow_id`, `force_full`, `extra` |
| `PipelineResult` | `pipelines/base.py` | `success`, `items_processed`, `error`, `metadata` |
| `PipelineStatus` | `pipelines/base.py` | `is_indexed`, `is_synced`, `is_stale`, `last_indexed_at`, `items_count` |

---

### 4. MCP Server (Exposing the Agent as MCP Tools)

The MCP server lets external clients (Claude Desktop, Cursor IDE, Python scripts) query databases, search codebases, and access project metadata through the standard Model Context Protocol.

**Architecture:**

```
External MCP Clients                        CheckMyData.ai
┌──────────────┐                           ┌─────────────────────────────────┐
│ Claude       │──stdio──────────────────▶│ FastMCP Server                  │
│ Desktop      │                           │ (app/mcp_server/server.py)      │
├──────────────┤                           │                                 │
│ Cursor IDE   │──SSE (port 8100)────────▶│ Tools:                          │
├──────────────┤                           │   query_database(project_id,    │
│ Python       │──streamable-http────────▶│     question, connection_id?)   │
│ script       │                           │   search_codebase(project_id,   │
└──────────────┘                           │     question)                   │
                                           │   list_projects()               │
                                           │   list_connections(project_id)  │
                                           │   get_schema(connection_id)     │
                                           │   execute_raw_query(            │
                                           │     connection_id, query)       │
                                           │                                 │
                                           │ Resources:                      │
                                           │   project://{id}/schema         │
                                           │   project://{id}/rules          │
                                           │   project://{id}/knowledge      │
                                           └─────────────────────────────────┘
```

**How tool calls are handled (`mcp_server/tools.py`):**

Each MCP tool handler creates an `AgentContext`, instantiates an `OrchestratorAgent`, and calls `orchestrator.run(ctx)`. The response is serialized to JSON and returned to the MCP client. This means MCP clients get the same multi-agent intelligence (SQL generation, validation loop, visualization) as the web UI.

Example flow for `query_database`:
1. Load project and connection from the internal DB
2. Build `ConnectionConfig` via `ConnectionService.to_config()`
3. Create `AgentContext` with `user_id="mcp-user"`, empty chat history
4. Run `OrchestratorAgent.run()` — full SQLAgent + VizAgent pipeline
5. Serialize `AgentResponse` to JSON (answer, query, results, viz config)

**Authentication (`mcp_server/auth.py`):**

| Method | How it works |
|---|---|
| **API key** | Set `CHECKMYDATA_API_KEY` (or `MCP_API_KEY`) env var on the server. Client sends the same key. Returns synthetic user `mcp-api-key-user`. |
| **JWT** | Client sends a JWT token issued by the auth system. Validated via `AuthService.decode_token()`. Returns the real user identity. |
| **No auth** | If no `CHECKMYDATA_API_KEY` is configured and no credentials are provided, requests proceed as `mcp-anonymous`. |

**Running the MCP server (`mcp_server/__main__.py`):**

```bash
# stdio (default) — for Claude Desktop, Cursor IDE
cd backend && python -m app.mcp_server

# SSE — for HTTP-based clients
cd backend && python -m app.mcp_server --transport sse --host 127.0.0.1 --port 8100

# streamable-http — for newer MCP clients
cd backend && python -m app.mcp_server --transport streamable-http --port 8100
```

**Configuring in Claude Desktop (`claude_desktop_config.json`):**

```json
{
  "mcpServers": {
    "checkmydata-agent": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/backend",
      "env": {
        "CHECKMYDATA_API_KEY": "your-secret-key"
      }
    }
  }
}
```

---

### 5. MCP Client (Consuming External MCP Servers)

The system can connect to any MCP-compliant server as a data source, enabling queries against services like Google Analytics, Stripe, Jira, or custom internal tools.

**Data flow:**

```
User asks about external data (e.g. "Show me GA pageviews")
    │
    ▼
OrchestratorAgent detects has_mcp_sources=True
    │  LLM calls query_mcp_source meta-tool
    ▼
_handle_query_mcp_source()
    │  1. Resolve MCP connection (by connection_id or first MCP conn in project)
    │  2. Build ConnectionConfig via to_config()
    │  3. Create MCPClientAdapter and connect()
    ▼
MCPClientAdapter.connect(config)
    │  reads config.extra: mcp_transport_type, mcp_server_command,
    │  mcp_server_args, mcp_server_url, mcp_env
    │
    │  stdio: spawn subprocess via StdioServerParameters
    │  SSE:   connect via sse_client(url)
    │
    │  Initialize ClientSession → list_tools()
    │  Store discovered tool schemas (name, description, input_schema)
    ▼
MCPSourceAgent.run(context, question, source_name)
    │
    │  1. Convert discovered MCP tool schemas → LLM Tool objects
    │     (each tool's input_schema.properties → ToolParameter list)
    │  2. Build system prompt with tool descriptions
    │  3. Enter LLM loop (max 5 iterations):
    │     - LLM sees tools and decides which to call
    │     - For each tool call: adapter.call_tool(name, arguments)
    │     - Tool result appended as tool message
    │     - Loop until LLM responds with text (no more tool calls)
    ▼
MCPSourceResult (answer, tool_calls_made, raw_results)
    │
    ▼
adapter.disconnect()  ← always runs (finally block)
    │
    ▼
Answer returned to OrchestratorAgent → user
```

**MCPClientAdapter (`connectors/mcp_client.py`):**

This is a `DataSourceAdapter` subclass that speaks the MCP protocol:

| Method | What it does |
|---|---|
| `connect(config)` | Starts stdio subprocess or SSE connection; initializes `ClientSession`; calls `list_tools()` to discover available tools |
| `disconnect()` | Closes the async exit stack (kills subprocess / closes HTTP) |
| `test_connection()` | Calls `list_tools()` — returns `True` if it succeeds |
| `list_entities()` | Returns tool names as the "entity" list |
| `get_tool_schemas()` | Returns full tool metadata (name, description, input_schema) |
| `query(tool_name, params)` | Calls an MCP tool; tries to parse JSON response into `QueryResult` rows/columns |
| `call_tool(name, arguments)` | Convenience method returning raw text from the MCP tool call |

**MCPSourceAgent (`agents/mcp_source_agent.py`):**

The agent has its own LLM loop (separate from the orchestrator's loop) with dynamically discovered tools. The key method `_build_llm_tools()` converts MCP `input_schema` JSON into `Tool` / `ToolParameter` objects that the LLM can call:

```
MCP tool schema:               →  LLM Tool object:
{                                  Tool(
  "name": "get_pageviews",           name="get_pageviews",
  "description": "...",              description="...",
  "input_schema": {                  parameters=[
    "properties": {                    ToolParameter(name="date_range", type="string", ...),
      "date_range": {                  ToolParameter(name="page_path", type="string", ...),
        "type": "string"            ]
      }                            )
    }
  }
}
```

**Adding an MCP source connection (frontend):**

1. In the sidebar Connections section, click **+ New**
2. Select **mcp** from the database type dropdown
3. Choose transport:
   - **stdio**: Enter the command (e.g. `npx`) and arguments (e.g. `-y @anthropic/mcp-server-filesystem /path`)
   - **SSE**: Enter the server URL (e.g. `http://localhost:8100/sse`)
4. Optionally add environment variables as JSON (e.g. `{"API_KEY": "sk-..."}`)
5. Click **Create Connection**

---

### 6. Data Source Adapter Hierarchy

All data source connectors implement a common interface defined in `connectors/base.py`:

```
DataSourceAdapter (ABC)          ← generic interface for ALL sources
    │
    │  source_type, connect(), disconnect(),
    │  test_connection(), list_entities(), query()
    │
    ├── DatabaseAdapter           ← adds introspect_schema(), execute_query(), db_type
    │   (alias: BaseConnector)
    │   ├── PostgresConnector
    │   ├── MySQLConnector
    │   ├── MongoDBConnector
    │   └── ClickHouseConnector
    │
    └── MCPClientAdapter          ← adds get_tool_schemas(), call_tool()
```

The `ADAPTER_REGISTRY` in `connectors/registry.py` maps type strings to adapter classes:

```python
ADAPTER_REGISTRY = {
    "postgres": PostgresConnector,
    "postgresql": PostgresConnector,
    "mysql": MySQLConnector,
    "mongodb": MongoDBConnector,
    "mongo": MongoDBConnector,
    "clickhouse": ClickHouseConnector,
    "mcp": MCPClientAdapter,
}
```

Use `get_adapter(source_type, db_type)` to instantiate an adapter. For SSH exec mode, pass `ssh_exec_mode=True` to get `SSHExecConnector` instead. The backward-compatible `get_connector(db_type)` function raises `TypeError` if the adapter is not a `DatabaseAdapter`.

---

### 7. Extension Protocol — Adding New Data Sources

This section documents the exact steps to add a new data source type to the system. Follow each step in order. The example below uses a hypothetical "google_analytics" source.

#### Step 1: Create the Adapter

Create `backend/app/connectors/google_analytics.py` implementing `DataSourceAdapter`:

```python
from app.connectors.base import ConnectionConfig, DataSourceAdapter, QueryResult

class GoogleAnalyticsAdapter(DataSourceAdapter):
    source_type = "google_analytics"

    async def connect(self, config: ConnectionConfig) -> None:
        # Read credentials from config.extra
        # Initialize API client
        ...

    async def disconnect(self) -> None:
        # Close API client
        ...

    async def test_connection(self) -> bool:
        # Make a lightweight API call to verify credentials
        ...

    async def list_entities(self) -> list[str]:
        # Return available data streams / property names
        ...

    async def query(self, query: str, params=None) -> QueryResult:
        # Execute an analytics query, return rows + columns
        ...
```

Register it in `backend/app/connectors/registry.py`:

```python
from app.connectors.google_analytics import GoogleAnalyticsAdapter

ADAPTER_REGISTRY = {
    ...
    "google_analytics": GoogleAnalyticsAdapter,
}
```

#### Step 2: Extend the Connection Model

Add any source-specific columns to `backend/app/models/connection.py`:

```python
ga_property_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
ga_credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Create an Alembic migration:

```bash
cd backend && alembic revision --autogenerate -m "add_google_analytics_fields"
```

#### Step 3: Update the API Layer

In `backend/app/api/routes/connections.py`:

1. Add `"google_analytics"` to the `ConnectionCreate.db_type` Literal type
2. Add optional fields to `ConnectionCreate` (`ga_property_id`, `ga_credentials`, etc.)
3. Add a validation branch in `@model_validator` for the new type
4. Add corresponding fields to `ConnectionUpdate` and `ConnectionResponse`

#### Step 4: Update ConnectionService

In `backend/app/services/connection_service.py`:

1. Handle encryption of new credentials in `create()`
2. Add the new fields to `_UPDATABLE_FIELDS`
3. In `to_config()`, populate `ConnectionConfig.extra` with the new fields when `source_type == "google_analytics"`

#### Step 5: Create a Pipeline (Optional)

If the data source needs indexing, create `backend/app/pipelines/google_analytics_pipeline.py`:

```python
from app.pipelines.base import DataSourcePipeline, PipelineContext, PipelineResult, PipelineStatus
from app.llm.base import Tool

class GoogleAnalyticsPipeline(DataSourcePipeline):
    source_type = "google_analytics"

    async def index(self, source_id: str, context: PipelineContext) -> PipelineResult:
        # Connect, discover available metrics/dimensions, store metadata
        ...

    async def sync_with_code(self, source_id: str, context: PipelineContext) -> PipelineResult:
        # Cross-reference analytics events with code (or no-op)
        ...

    async def get_status(self, source_id: str) -> PipelineStatus:
        ...

    def get_agent_tools(self) -> list[Tool]:
        # Return any extra tools this pipeline provides to agents
        return []
```

Register in `backend/app/pipelines/registry.py`:

```python
from app.pipelines.google_analytics_pipeline import GoogleAnalyticsPipeline

PIPELINE_REGISTRY = {
    ...
    "google_analytics": GoogleAnalyticsPipeline,
}
```

#### Step 6: Create an Agent (Optional)

If the source needs custom LLM interaction (beyond what the existing agents handle), create a sub-agent:

**6a. Agent class** (`backend/app/agents/ga_agent.py`):

```python
from app.agents.base import AgentContext, AgentResult, BaseAgent

class GAAgent(BaseAgent):
    name = "google_analytics"

    async def run(self, context: AgentContext, **kwargs) -> AgentResult:
        # Custom LLM loop for analytics queries
        ...
```

**6b. Meta-tool definition** (`backend/app/agents/tools/ga_tools.py`):

```python
from app.llm.base import Tool, ToolParameter

QUERY_ANALYTICS_TOOL = Tool(
    name="query_analytics",
    description="Query Google Analytics data for traffic, events, and conversions.",
    parameters=[
        ToolParameter(name="question", type="string", description="The analytics question"),
    ],
)
```

**6c. System prompt** (`backend/app/agents/prompts/ga_prompt.py`):

```python
def build_ga_system_prompt(**kwargs) -> str:
    return "You are an analytics assistant..."
```

**6d. Wire into OrchestratorAgent** (`backend/app/agents/orchestrator.py`):

1. Import the agent and result type in `__init__`
2. Add `ga_agent` parameter to `__init__` and store as `self._ga`
3. Add `_has_analytics(project_id)` helper method
4. Call it in `run()` and pass `has_analytics` to `get_orchestrator_tools()`
5. Add `if tc.name == "query_analytics":` branch in `_handle_meta_tool()`

**6e. Update `get_orchestrator_tools()`** (`backend/app/agents/tools/orchestrator_tools.py`):

```python
def get_orchestrator_tools(
    *,
    has_connection: bool = False,
    has_knowledge_base: bool = False,
    has_mcp_sources: bool = False,
    has_analytics: bool = False,    # new
) -> list[Tool]:
    ...
    if has_analytics:
        from app.agents.tools.ga_tools import QUERY_ANALYTICS_TOOL
        tools.append(QUERY_ANALYTICS_TOOL)
    return tools
```

#### Step 7: Update the Frontend

In `frontend/src/components/connections/ConnectionSelector.tsx`:

1. Add `"google_analytics"` to the `DB_TYPES` array
2. Add initial values for new fields in `EMPTY_FORM`
3. Update `connToForm()` to map existing connection data
4. Update `handleCreate()` to include new fields in the API payload
5. Add conditional rendering for the new source type's form fields (similar to the `isMCP` pattern)

#### Step 8: Write Tests

- Unit tests for the adapter (`backend/tests/unit/test_ga_connector.py`)
- Unit tests for the pipeline (`backend/tests/unit/test_ga_pipeline.py`)
- Unit tests for the agent (`backend/tests/unit/test_ga_agent.py`)
- Update `backend/tests/unit/test_api_routes.py` to include the new connection type in mock objects

---

### 8. Extension Protocol — Adding New Agents

To add a new agent that handles a specific type of question (without a new data source):

| Step | File(s) to modify / create |
|---|---|
| 1. Create agent class | `backend/app/agents/<name>_agent.py` — subclass `BaseAgent`, implement `run()` and `name` |
| 2. Define meta-tool | `backend/app/agents/tools/<name>_tools.py` — create `Tool` with parameters |
| 3. Create system prompt | `backend/app/agents/prompts/<name>_prompt.py` — build prompt function |
| 4. Wire into orchestrator | `backend/app/agents/orchestrator.py` — add to `__init__`, `_handle_meta_tool`, and capability check |
| 5. Update tool selection | `backend/app/agents/tools/orchestrator_tools.py` — add parameter to `get_orchestrator_tools()`, conditionally include the new tool |
| 6. Write tests | `backend/tests/unit/test_<name>_agent.py` |

The pattern is always the same: define the agent, define its meta-tool, create its prompt, and wire it into the orchestrator's dispatch table.

---

### Backend Directory Structure

```
app/
├── agents/             ← Multi-agent framework
│   ├── base.py         ← AgentContext, AgentResult, BaseAgent ABC
│   ├── errors.py       ← AgentError hierarchy (timeout, retryable, fatal, validation)
│   ├── validation.py   ← Inter-agent result validation
│   ├── orchestrator.py ← OrchestratorAgent: routes to sub-agents, composes responses
│   ├── sql_agent.py    ← SQLAgent: schema → SQL gen → validation → execution → learnings
│   ├── viz_agent.py    ← VizAgent: rule-based + LLM chart type selection
│   ├── knowledge_agent.py ← KnowledgeAgent: RAG search, entity info, codebase Q&A
│   ├── mcp_source_agent.py ← MCPSourceAgent: queries external MCP servers
│   ├── investigation_agent.py ← InvestigationAgent: diagnoses data accuracy issues
│   ├── tools/          ← Per-agent tool definitions
│   │   ├── orchestrator_tools.py ← Meta-tools (query_database, search_codebase, manage_rules, query_mcp_source, ask_user)
│   │   ├── sql_tools.py ← execute_query, get_schema_info, get_query_context, read_notes, write_note, etc.
│   │   ├── knowledge_tools.py ← search_knowledge, get_entity_info
│   │   ├── mcp_tools.py ← query_mcp_source meta-tool definition
│   │   ├── investigation_tools.py ← get_original_context, run_diagnostic_query, compare_results, etc.
│   │   └── viz_tools.py ← recommend_visualization
│   └── prompts/        ← Per-agent system prompts (all include current date/time)
│       ├── __init__.py ← get_current_datetime_str() helper
│       ├── orchestrator_prompt.py ← Includes DATA VERIFICATION PROTOCOL
│       ├── sql_prompt.py ← Includes SELF-IMPROVEMENT PROTOCOL + required filters/value mappings
│       ├── viz_prompt.py
│       ├── knowledge_prompt.py
│       ├── investigation_prompt.py ← Investigation checklist and diagnostic process
│       └── mcp_prompt.py ← System prompt for MCPSourceAgent
├── api/routes/         ← HTTP endpoints (FastAPI routers)
├── core/               ← Utilities + backward-compatible wrappers
│   ├── data_sanity_checker.py ← Automated anomaly detection on query results
│   ├── agent.py        ← ConversationalAgent wrapper → delegates to OrchestratorAgent
│   ├── tools.py        ← Deprecated: re-exports from agents/tools/
│   ├── prompt_builder.py ← Deprecated: delegates to agents/prompts/
│   ├── tool_executor.py← Executes tool calls (used by SQLAgent internally)
│   ├── orchestrator.py ← Original SQL pipeline (preserved, used by SQLAgent)
│   ├── query_builder.py← LLM prompt construction + tool calling
│   ├── validation_loop.py ← Self-healing query loop (pre/execute/post/repair)
│   ├── query_validation.py ← Data models (QueryAttempt, QueryError, etc.)
│   ├── pre_validator.py← Schema-aware pre-execution validator
│   ├── post_validator.py← Post-execution result validator
│   ├── explain_validator.py ← EXPLAIN dry-run validator
│   ├── error_classifier.py ← Dialect-aware DB error classification
│   ├── context_enricher.py ← Builds enriched context for LLM repair
│   ├── query_repair.py ← LLM-driven query repair
│   ├── retry_strategy.py ← Per-error-type retry decision logic
│   ├── schema_hints.py ← Fuzzy column/table matching utilities
│   ├── sql_parser.py   ← Lightweight SQL parser for pre-validation
│   ├── safety.py       ← Query safety validation
│   ├── workflow_tracker.py ← Event bus for pipeline tracking
│   ├── history_trimmer.py ← Token-budget-aware chat history summarization
│   ├── query_cache.py  ← LRU result cache (connection_key + query_hash)
│   ├── retry.py        ← Async retry decorator with backoff
│   ├── rate_limit.py   ← slowapi rate limiting config
│   ├── audit.py        ← Structured audit logging for sensitive operations
│   └── logging_config.py ← Structured logging setup
├── connectors/         ← Data source adapters
│   ├── base.py         ← DataSourceAdapter ABC → DatabaseAdapter → BaseConnector alias
│   ├── registry.py     ← ADAPTER_REGISTRY + backward-compatible get_connector
│   ├── mcp_client.py   ← MCPClientAdapter: connects to external MCP servers
│   ├── postgres.py     ← asyncpg + SSH tunnel via asyncssh
│   ├── mysql.py        ← aiomysql + SSH tunnel
│   ├── mongodb.py      ← motor (async MongoDB driver)
│   ├── clickhouse.py   ← clickhouse-connect (sync, wrapped in asyncio.to_thread)
│   ├── ssh_exec.py     ← SSH exec mode: run queries via CLI on remote server
│   ├── ssh_tunnel.py   ← SSH tunnel (port forwarding) with keepalive + timeout
│   ├── cli_output_parser.py ← Parse MySQL/psql/ClickHouse CLI tabular output
│   └── exec_templates.py    ← Predefined CLI command templates per db_type
├── pipelines/          ← Data source pipeline plugin system
│   ├── base.py         ← DataSourcePipeline ABC (index, sync, get_status, get_agent_tools)
│   ├── registry.py     ← Pipeline registry (register_pipeline, get_pipeline)
│   ├── database_pipeline.py ← Wraps DbIndexPipeline + CodeDbSyncPipeline
│   └── mcp_pipeline.py ← MCPPipeline: indexes MCP tool schemas in vector store
├── mcp_server/         ← MCP Server: exposes agent capabilities as MCP tools
│   ├── __init__.py
│   ├── __main__.py     ← CLI entry point (python -m app.mcp_server)
│   ├── server.py       ← FastMCP server with tools and resources
│   ├── auth.py         ← API key / JWT auth for MCP clients
│   ├── tools.py        ← MCP tool handlers → OrchestratorAgent
│   └── resources.py    ← MCP resources (schema, rules, knowledge)
├── knowledge/          ← Repository analysis & RAG (multi-pass pipeline)
│   ├── indexing_pipeline.py ← Multi-pass orchestrator (profile → extract → enrich → store)
│   ├── pipeline_runner.py  ← Resumable pipeline runner with checkpoint-based step skipping
│   ├── project_profiler.py  ← Pass 1: Auto-detect framework/ORM/language/dirs
│   ├── entity_extractor.py  ← Pass 2-3: Cross-file entity map, usage tracking, enums
│   ├── project_summarizer.py← Pass 4: Project-level summary + schema cross-reference
│   ├── file_splitter.py     ← Smart large-file splitting by class/model boundary
│   ├── repo_analyzer.py← Git clone, AST/regex parsing for ORM models (11 ORMs)
│   ├── doc_generator.py← LLM doc generation with cross-file enrichment context
│   ├── chunker.py      ← Semantic chunking for ChromaDB
│   ├── schema_indexer.py← Live DB schema → prompt context
│   ├── vector_store.py ← ChromaDB wrapper (embedded + server modes)
│   ├── git_tracker.py  ← Incremental indexing with branch tracking + deleted file handling
│   ├── custom_rules.py ← File + DB rule loading
│   ├── doc_store.py    ← Doc storage keyed by (project_id, source_path)
│   ├── db_index_pipeline.py  ← 6-step DB indexing pipeline (introspect → sample → validate → store)
│   ├── db_index_validator.py ← LLM-powered per-table analysis with structured output
│   └── learning_analyzer.py  ← Heuristic lesson extractors
├── llm/                ← LLM provider abstraction
│   ├── base.py         ← Message, LLMResponse, ToolCall types
│   ├── router.py       ← Provider chain with fallback + retry
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   └── openrouter_provider.py
├── models/             ← SQLAlchemy models (internal DB)
│   ├── project.py, connection.py (+source_type + MCP fields), ssh_key.py
│   ├── repository.py   ← ProjectRepository: multi-repo support per project
│   ├── chat_session.py, chat_message.py
│   ├── custom_rule.py, user.py
│   ├── project_member.py ← Role-based project membership (owner/editor/viewer)
│   ├── project_invite.py ← Email-based project invitations
│   ├── knowledge_doc.py, commit_index.py (branch-aware)
│   ├── project_cache.py ← Cached ProjectKnowledge + ProjectProfile per project
│   ├── agent_learning.py ← AgentLearning + AgentLearningSummary
│   ├── db_index.py     ← DbIndex + DbIndexSummary: per-table LLM analysis results
│   ├── rag_feedback.py ← RAG chunk quality tracking (version-scoped)
│   ├── saved_note.py   ← SavedNote: user-scoped saved SQL queries per project
│   ├── session_note.py ← SessionNote: agent working memory (per-connection observations)
│   ├── data_validation.py ← DataValidationFeedback + DataInvestigation models
│   └── benchmark.py    ← DataBenchmark: verified metric values for sanity-checking
├── services/           ← Business logic layer
│   ├── project_service.py, connection_service.py
│   ├── repository_service.py ← CRUD for ProjectRepository
│   ├── ssh_key_service.py, chat_service.py
│   ├── rule_service.py, default_rule_template.py, auth_service.py
│   ├── membership_service.py ← Role checking, member CRUD, accessible projects
│   ├── invite_service.py ← Create/accept/revoke invites, auto-accept on registration
│   ├── rag_feedback_service.py ← Record & query RAG effectiveness (version-scoped)
│   ├── project_cache_service.py ← Persist/load ProjectKnowledge + ProjectProfile between runs
│   ├── checkpoint_service.py ← CRUD for indexing checkpoints (resumable pipeline state)
│   ├── agent_learning_service.py ← CRUD, dedup, confidence management for learnings
│   ├── db_index_service.py  ← CRUD + formatting for database index entries
│   ├── note_service.py ← CRUD for saved notes (create, list, update, delete, update_result)
│   ├── session_notes_service.py ← CRUD, fuzzy dedup, prompt compilation for agent notes
│   ├── data_validation_service.py ← CRUD + accuracy stats for validation feedback
│   ├── benchmark_service.py ← Create/confirm/flag benchmarks for verified metrics
│   ├── feedback_pipeline.py ← Process validation feedback → learnings + notes + benchmarks
│   ├── investigation_service.py ← Lifecycle management for data investigations
│   ├── code_db_sync_service.py ← ... + add_runtime_enrichment() for investigation findings
│   └── encryption.py   ← Fernet encrypt/decrypt
└── viz/                ← Visualization & export
    ├── renderer.py     ← Auto-detect viz type (table/chart/text)
    ├── chart.py        ← Chart.js config generation (bar/line/pie/scatter) with auto-detection and error boundary
    ├── table.py        ← Tabular data formatting
    └── export.py       ← CSV, JSON, XLSX export
```

### How the SQLAgent Works

When the orchestrator delegates to the SQLAgent via `query_database`:

1. **Context gathering** — Check for DB index, sync context, learnings, session notes, required filters, column value mappings
2. **Tool loop** — SQLAgent has its own LLM loop (max 3 iterations) with SQL-specific tools (including `read_notes`, `write_note`)
3. **Validation loop** — Generated queries go through the self-healing cycle (see below)
4. **Sanity checks** — `DataSanityChecker` runs on results: zero/null detection, temporal anomalies, aggregation checks, benchmark comparisons
5. **Learning extraction** — After multiple attempts, patterns are recorded for future queries
6. **Result** — Returns `SQLAgentResult` with query, results, attempt history, and any sanity warnings

### Query Validation & Self-Healing Loop

The orchestrator runs every generated query through a **validation loop** that can detect errors, diagnose causes, and automatically repair queries — up to 3 attempts by default.

```
User Question
    ↓
[Build Query via LLM]
    ↓
┌─────────────── Validation Loop (max N attempts) ──────────────┐
│                                                                 │
│  1. Pre-Validate → check tables/columns exist in schema         │
│       ↓ (invalid → repair)                                      │
│  2. Safety Check → block DML in read-only mode                  │
│       ↓ (blocked → return immediately)                          │
│  3. EXPLAIN Dry-Run → catch syntax errors, warn on full scans   │
│       ↓ (error → repair)                                        │
│  4. Execute Query → run on actual database                      │
│       ↓ (DB error → repair)                                     │
│  5. Post-Validate → check for errors, empty results, slow query │
│       ↓ (invalid → repair)                                      │
│  6. Success → exit loop                                         │
│                                                                 │
│  Repair cycle:                                                  │
│    Classify Error → Enrich Context → LLM Repairs → Loop back    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
    ↓
[Interpret Results + Recommend Viz]
```

**Error types** recognized by the classifier (dialect-aware for PG, MySQL, ClickHouse, MongoDB):

| Error Type | Retryable | Repair Strategy |
|---|---|---|
| `column_not_found` | Yes | Fuzzy-match suggests correct column names from schema |
| `table_not_found` | Yes | Shows full table list, suggests similar names |
| `syntax_error` | Yes | Passes error + dialect hints to LLM |
| `type_mismatch` | Yes | Shows column types for correct casting |
| `ambiguous_column` | Yes | Hints to qualify with table name |
| `timeout` | Yes | Hints: add LIMIT, simplify aggregations |
| `empty_result` | Configurable | Hints: broaden WHERE, check date ranges |
| `permission_denied` | **No** | Returns error immediately |
| `connection_error` | **No** | Returns error immediately |

**Attempt history** is stored in each chat message's metadata and displayed in the frontend "show details" expander.

**Schema context** is built from three sources:
- **Live introspection** — tables, columns, types, foreign keys, indexes, comments, row counts (cached for 5 minutes)
- **RAG results** — ChromaDB semantic search for documentation chunks relevant to the question
- **Sample data** — optionally, `SELECT * FROM table LIMIT 3` per table (gated by `INCLUDE_SAMPLE_DATA` config)

**Query building** uses **LLM tool calling** (function calling). The LLM is given tools:
- `execute_query(query, explanation)` — to produce the SQL
- `recommend_visualization(viz_type, config, summary)` — to format results

The system prompt is **dialect-aware** — it includes specific guidance for MySQL (backtick quoting), PostgreSQL (double-quote quoting, schema prefixes), ClickHouse (approximate functions), and MongoDB (JSON pipeline format).

**Date/time awareness** — All agent system prompts (Orchestrator, SQL, Knowledge, Viz, MCP) receive the current UTC date and time (e.g. `"2026-03-19 14:30 UTC (Thursday)"`). This enables accurate handling of relative date queries ("yesterday", "last week", "last month") without relying on the LLM's potentially outdated internal clock. The SQL agent specifically uses this for precise date calculations in generated queries.

**Numeric format analysis** — During DB indexing, the LLM validator produces per-table `numeric_format_notes` that document:
- Whether monetary values are stored in cents (integer) or whole currency units (decimal)
- Which currency is used (single or multi-currency), and which column holds the currency code
- Decimal precision for financial columns
- Whether percentages are stored as 0-100 or 0.0-1.0
- Units of measurement (grams, kg, seconds, etc.)
- Value ranges inferred from sample data

These notes are surfaced to the SQL agent in the "Numeric formats" section of every table context, alongside column notes and conversion warnings.

### SSH Tunnel Architecture

The system supports **two SSH modes** for connecting to databases on remote servers:

**Mode 1 — Port Forwarding** (default): Uses `asyncssh` to create an in-process SSH tunnel with local port forwarding. The native async DB driver (e.g., `aiomysql`) connects through the forwarded port.

```
User's Machine                        Target Server
┌──────────────┐                      ┌──────────────────┐
│  Agent       │                      │  SSH Server      │
│  Backend     │  SSH tunnel          │  ┌────────────┐  │
│              ├──────────────────────┤  │  MySQL on   │  │
│  asyncssh    │  port forwarding     │  │  127.0.0.1  │  │
│  (in-memory  │  local:random ──►    │  │  :3306      │  │
│   key, no    │       remote:3306    │  └────────────┘  │
│   temp file) │                      │                  │
└──────────────┘                      └──────────────────┘
```

**Mode 2 — SSH Exec Mode** (new): SSHes into the server and runs the database CLI client directly via `asyncssh.run()`. Query is piped via stdin to avoid shell injection. Useful when port forwarding is blocked, the DB client is only on the server, or custom pre-commands are needed.

```
User's Machine                        Target Server
┌──────────────┐                      ┌──────────────────┐
│  Agent       │  SSH exec            │  SSH Server      │
│  Backend     ├──────────────────────┤                  │
│              │  conn.run(           │  ┌────────────┐  │
│  asyncssh    │    "echo QUERY |     │  │  mysql CLI  │  │
│  SSHExec     │     mysql ..."       │  │  on server  │  │
│  Connector   │  )                   │  └──────┬─────┘  │
│              │  ◄── stdout (TSV)    │         │        │
│  CLIOutput   │                      │  ┌──────▼─────┐  │
│  Parser      │                      │  │  MySQL DB   │  │
└──────────────┘                      └──┴────────────┴──┘
```

SSH keys are loaded directly into memory via `asyncssh.import_private_key()` — no temporary files needed for database connections. For Git operations (which use the `git` CLI), the key is briefly written to a temp file with `0600` permissions and deleted immediately after.

SSH connections include a 30-second connect timeout and 15-second keepalive interval. The `is_alive()` check first tries a unique stdout marker (`__SSH_TUNNEL_ALIVE__`) via shell echo. If the shell command fails (e.g. the SSH account uses a `nologin` shell), it falls back to checking whether the SSH transport is open and the port-forwarding listener is still active — this supports tunnel-only accounts that block shell access. The SSH test endpoint (`POST /connections/{id}/test-ssh`) also uses a stdout marker (`__SSH_TEST_OK__`) and returns the actual stdout on failure for debugging. If an SSH tunnel is recreated (new port), the MySQL and PostgreSQL connectors automatically detect the broken connection during schema introspection and reconnect with a single retry. If an SSH connection drops mid-query, the exec connector automatically attempts one reconnection before failing.

### Data Flow for Repository Indexing (Multi-Pass Pipeline)

```
Git repo (SSH clone / pull with branch tracking)
    ↓
Pass 1: Project Profiler
  • Detect framework (Django, Rails, Express, Spring, FastAPI, etc.)
  • Detect ORM (SQLAlchemy, TypeORM, Prisma, Drizzle, Mongoose, etc.)
  • Detect primary language, model/service/migration directories
    ↓
Pass 2: RepoAnalyzer — parses files for:
  • 11 ORM patterns (SQLAlchemy, Django, TypeORM, Sequelize, Drizzle, Mongoose, Peewee, GORM, ActiveRecord, Tortoise, Prisma)
  • Raw SQL in strings AND JS template literals (tagged templates)
  • Migration files, SQL files, query chain patterns
    ↓
Pass 3: Entity Extractor (cross-file analysis, incremental-capable)
  • Build Entity Relationship Map (models → columns → FKs → relationships)
  • Track table usage (which files read/write each table)
  • Extract enums, constants, validation rules across files
  • Detect dead/unused tables (in schema but not referenced in code)
  • Extract service-layer business logic (defaults, computed fields, state machines)
  • Extract data validation rules (Django validators, Prisma constraints, TypeORM @Check/@Unique)
  • Extract database config/environment variable references (DATABASE_URL, DB_HOST, etc.)
  • GraphQL schema parsing (type definitions, enums, field extraction)
  • Column extraction for Go (GORM struct tags), Ruby (ActiveRecord), Java (JPA @Column)
  • ORM-scoped extraction: only runs relevant regex patterns based on detected ORM
  • Incremental mode: load cached ProjectKnowledge, re-scan only changed/deleted files
    ↓
Pass 4: DocGenerator — enriched LLM documentation
  • Each model sent to LLM WITH cross-file context (relationships, enum values, usage data)
  • Large files split by class/model boundary (no blind truncation)
  • Diff-aware updates: small file changes use unified diff instead of full regeneration
  • Project-level summary document generated (entity map, dead tables, enums, config refs)
  • Schema cross-reference: compares code-discovered tables vs live DB tables (orphan/phantom detection)
    ↓
Pass 5: Chunker + VectorStore
  • Stale chunks cleaned before upserting new ones
  • Entity-aware chunk boundaries
  • Chunks tagged with source_path, models, tables, commit_sha
  • Per-table/model metadata entries for filtered ChromaDB queries
  • Table-to-model mapping included in chunk metadata
  • Configurable embedding model via CHROMA_EMBEDDING_MODEL
    ↓
ChromaDB — RAG retrieval (supports embedded + remote server mode)
    ↓
DocStore — one row per (project_id, source_path), updated in-place
```

### Frontend Architecture

```
Next.js 15 / React 19 / TypeScript / Tailwind CSS 4 / DM Sans + JetBrains Mono

src/
├── app/
│   ├── page.tsx           ← Main page: AuthGate → Sidebar + ChatPanel + LogPanel
│   ├── layout.tsx         ← Root layout: DM Sans + JetBrains Mono fonts, wraps in ClientShell
│   └── globals.css        ← Design tokens (CSS variables), animations, scrollbar styles
├── stores/
│   ├── app-store.ts       ← Zustand: projects, connections, sessions, messages, chatMode
│   ├── auth-store.ts      ← Zustand: user, token, login/register/logout, auto-refresh
│   ├── log-store.ts       ← Zustand: activity log entries, panel state, SSE connection status
│   ├── toast-store.ts     ← Zustand: toast notifications (success/error/info, 4s auto-dismiss)
│   └── task-store.ts      ← Zustand: active background tasks (index, sync) with auto-dismiss
├── hooks/
│   ├── useGlobalEvents.ts ← Global SSE subscription hook (all workflow events → log store + task store); re-seeds active tasks on reconnect
│   └── useRestoreState.ts ← Restore active project/connection/session from localStorage on mount
├── lib/
│   ├── api.ts             ← REST client (fetch wrapper + auth headers + 422 error parsing)
│   ├── sse.ts             ← SSE helpers: fetch-based streaming with auth (per-workflow + global)
│   └── viz-utils.ts       ← Viz type definitions + rerenderViz() utility for client-side viz switching
└── components/
    ├── ui/
    │   ├── Icon.tsx           ← Centralized SVG icon system (~30 Lucide-style icons, no npm dep)
    │   ├── SidebarSection.tsx ← Notion-style collapsible section: CSS grid animated expand/collapse, chevron-first header, hover-reveal action
    │   ├── StatusDot.tsx      ← Animated status indicator (success/warning/error/idle/loading, ARIA)
    │   ├── ActionButton.tsx   ← Consistent icon button (xs/sm/md sizes, ghost/danger/accent, tooltip, focus ring, a11y)
    │   ├── Tooltip.tsx        ← Accessible tooltip (hover + focus, role=tooltip, aria-describedby)
    │   ├── ClientShell.tsx    ← Client wrapper: ErrorBoundary + ToastContainer + ConfirmModal
    │   ├── ErrorBoundary.tsx  ← Global React error boundary (prevents white-screen crashes)
    │   ├── ToastContainer.tsx ← Toast notification renderer (bottom-right corner)
    │   ├── ConfirmModal.tsx   ← Reusable confirmation modal (replaces native confirm())
    │   ├── LlmModelSelector.tsx ← Reusable LLM provider+model selector (stacked layout)
    │   └── Spinner.tsx        ← Reusable loading spinner
    ├── auth/AuthGate.tsx   ← Login/register with branded header, Google OAuth
    ├── auth/AccountMenu.tsx ← Account settings: change password, sign out, delete account
    ├── Sidebar.tsx         ← Collapsible sidebar (w-64 ↔ w-16), Notion/Linear-style navigation with
    │                          single scroll area, grouped Setup/Workspace sections, subtle dividers
    ├── chat/
    │   ├── ChatPanel.tsx   ← Message list + knowledge-only mode toggle + error retry
    │   ├── ChatMessage.tsx ← Individual message with response_type-aware rendering + retry button
    │   ├── ChatSessionList.tsx ← Session switcher with active left bar, "Show all N" cap, inline hover delete
    │   └── ToolCallIndicator.tsx ← Real-time tool call progress during streaming
    ├── projects/
    │   ├── ProjectSelector.tsx  ← CRUD + role badges + active left bar + inline hover action overlay
    │   └── InviteManager.tsx    ← Invite users, manage members, error toasts
    ├── invites/PendingInvites.tsx ← Accept/decline incoming invites with error toasts
    ├── connections/ConnectionSelector.tsx ← CRUD + StatusDot + active left bar + compact badges + inline hover actions
    ├── ssh/SshKeyManager.tsx ← Add/list/delete SSH keys with inline icon + type badge + hover delete
    ├── rules/RulesManager.tsx ← CRUD with inline badges (default/global) + hover edit/delete overlay
    ├── knowledge/KnowledgeDocs.tsx ← Browse indexed docs with "Show all N" cap + active left bar
    ├── notes/
    │   ├── NotesPanel.tsx    ← Right-side panel: list of saved queries per project
    │   └── NoteCard.tsx      ← Individual saved query card: view/edit/execute/delete
    ├── tasks/ActiveTasksWidget.tsx ← Header widget: running background tasks with live progress
    ├── workflow/WorkflowProgress.tsx ← Real-time step tracking (SSE-based)
    ├── workflow/StreamWorkflowProgress.tsx ← Inline progress from SSE stream events
    ├── log/LogPanel.tsx ← Bottom panel: real-time activity log with color-coded pipeline events
    └── viz/ ← DataTable, ChartRenderer, VizToolbar, ExportButtons
```

**State management**: Zustand stores manage all app state. The active project ID, connection ID, and session ID are persisted to `localStorage` and automatically restored on page reload via `useRestoreState` — the app re-fetches the project, connections, sessions, and messages from the API so the user resumes exactly where they left off. Auth state (JWT token, user object) is also persisted in `localStorage`. Sidebar collapse state is persisted in `localStorage`.

**Error handling**: All API errors flow through a centralized parser that handles FastAPI 422 validation arrays (with fallback for missing `msg` fields). Destructive actions use a custom confirmation modal with Escape key and backdrop-click dismissal (race-condition safe for overlapping calls). Errors are surfaced via toast notifications instead of `console.error` or `alert()`. A global `ErrorBoundary` prevents white-screen crashes. The viz export endpoint includes 401 session-expiry handling matching the shared `request()` helper.

**Backend validation**: Project names are whitespace-stripped and require `min_length=1` on both create and update. Connection names and connection strings are whitespace-stripped. The connection update endpoint validates the merged state to prevent clearing required fields (must have either `connection_string` or `db_host + db_name`). Stale sessions/connections are cleared synchronously when switching projects to prevent race conditions.

**Loading states**: All data-fetching components show loading spinners during initial load. Empty states display helpful guidance messages.

### API Endpoints Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Create account (email, password) |
| `POST` | `/api/auth/login` | Login, returns JWT |
| `POST` | `/api/auth/google` | Google OAuth login (credential + optional nonce/CSRF) |
| `GET` | `/api/auth/me` | Get current user profile (validates token server-side) |
| `POST` | `/api/auth/change-password` | Change password (requires current password) |
| `POST` | `/api/auth/refresh` | Refresh JWT token (returns new token) |
| `DELETE` | `/api/auth/account` | Permanently delete account and all data |
| `POST/GET/PATCH/DELETE` | `/api/projects` | Project CRUD |
| `POST/GET/PATCH/DELETE` | `/api/connections` | Connection CRUD |
| `GET` | `/api/connections/project/{id}` | List connections for project |
| `POST` | `/api/connections/{id}/test` | Test database connectivity |
| `POST` | `/api/connections/{id}/test-ssh` | Test SSH connectivity independently (returns hostname) |
| `POST` | `/api/connections/{id}/refresh-schema` | Invalidate cached schema and re-introspect |
| `POST` | `/api/connections/{id}/index-db` | Trigger database indexing (returns 202, background) |
| `GET` | `/api/connections/{id}/index-db/status` | DB index status (is_indexed, table counts, is_indexing) |
| `GET` | `/api/connections/{id}/index-db` | Get full database index (all tables + summary) |
| `DELETE` | `/api/connections/{id}/index-db` | Clear database index (force re-index) |
| `GET` | `/api/connections/{id}/learnings` | List all agent learnings for a connection |
| `GET` | `/api/connections/{id}/learnings/status` | Learning status (count, last compiled) |
| `GET` | `/api/connections/{id}/learnings/summary` | Get compiled learning summary prompt |
| `PATCH` | `/api/connections/{id}/learnings/{lid}` | Edit a learning (lesson, confidence, active) |
| `DELETE` | `/api/connections/{id}/learnings/{lid}` | Delete a specific learning |
| `DELETE` | `/api/connections/{id}/learnings` | Clear all learnings for a connection |
| `POST` | `/api/connections/{id}/learnings/recompile` | Force recompile the learnings prompt |
| `POST/GET/DELETE` | `/api/ssh-keys` | SSH key management |
| `POST` | `/api/chat/sessions` | Create chat session |
| `GET` | `/api/chat/sessions/{project_id}` | List sessions |
| `PATCH` | `/api/chat/sessions/{id}` | Update session (title) |
| `POST` | `/api/chat/sessions/{id}/generate-title` | Auto-generate session title via LLM |
| `DELETE` | `/api/chat/sessions/{id}` | Delete session |
| `GET` | `/api/chat/sessions/{id}/messages` | Get session messages |
| `POST` | `/api/chat/feedback` | Submit thumbs up/down feedback on a message |
| `GET` | `/api/chat/analytics/feedback/{project_id}` | Aggregated feedback stats |
| `POST` | `/api/chat/ask` | Send question (blocking) |
| `POST` | `/api/chat/ask/stream` | Send question (SSE streaming) |
| `WS` | `/api/chat/ws/{project_id}/{connection_id}` | WebSocket chat |
| `POST` | `/api/repos/check-access` | Verify repo access + list branches (no project needed) |
| `POST` | `/api/repos/{project_id}/index` | Trigger repo indexing (returns 202, runs in background) |
| `GET` | `/api/repos/{project_id}/status` | Indexing status (commit, time, branch, doc count, is_indexing) |
| `POST` | `/api/repos/{project_id}/check-updates` | Check for new commits without indexing |
| `GET` | `/api/repos/{project_id}/docs` | List indexed docs |
| `GET` | `/api/repos/{project_id}/docs/{doc_id}` | Get doc content |
| `GET` | `/api/models?provider={name}` | List available LLM models for provider (openrouter fetched live, others static) |
| `POST/GET/PATCH/DELETE` | `/api/rules` | Custom rules CRUD |
| `POST` | `/api/notes` | Create saved note |
| `GET` | `/api/notes?project_id=X` | List notes (user-scoped) |
| `GET` | `/api/notes/{id}` | Get single note |
| `PATCH` | `/api/notes/{id}` | Update note (title, comment) |
| `DELETE` | `/api/notes/{id}` | Delete note |
| `POST` | `/api/notes/{id}/execute` | Re-execute SQL (10/min rate limit) |
| `POST` | `/api/invites/{project_id}/invites` | Invite a user by email (owner only) |
| `GET` | `/api/invites/{project_id}/invites` | List invites (owner only) |
| `DELETE` | `/api/invites/{project_id}/invites/{id}` | Revoke a pending invite (owner only) |
| `POST` | `/api/invites/accept/{invite_id}` | Accept an invite |
| `GET` | `/api/invites/pending` | List pending invites for current user |
| `GET` | `/api/invites/{project_id}/members` | List project members |
| `DELETE` | `/api/invites/{project_id}/members/{user_id}` | Remove a member (owner only) |
| `POST` | `/api/data-validation/validate-data` | Record structured validation feedback (confirmed/rejected/approximate) |
| `GET` | `/api/data-validation/validation-stats/{cid}` | Aggregated accuracy stats for a connection |
| `GET` | `/api/data-validation/benchmarks/{cid}` | List all verified benchmarks for a connection |
| `POST` | `/api/data-validation/investigate` | Start "Wrong Data" investigation |
| `GET` | `/api/data-validation/investigate/{id}` | Poll investigation status and progress |
| `POST` | `/api/data-validation/investigate/{id}/confirm-fix` | Accept or reject investigation fix |
| `POST` | `/api/visualizations/render` | Render visualization |
| `POST` | `/api/visualizations/export` | Export data (CSV/JSON/XLSX) |
| `GET` | `/api/workflows/events` | SSE workflow progress |
| `GET` | `/api/tasks/active` | List currently running background tasks |
| `GET` | `/api/health` | Basic health check |
| `GET` | `/api/health/modules` | Per-module health status |
| `POST` | `/api/backup/trigger` | Trigger a manual backup |
| `GET` | `/api/backup/list` | List available backups from disk |
| `GET` | `/api/backup/history` | List backup records from database |

### Security Model

| Concern | Implementation |
|---|---|
| **Authentication** | JWT tokens (HS256), 24h expiry with automatic proactive refresh, bcrypt password hashing. Google OAuth via GIS ID token verification. Password change and account deletion endpoints. All routes require auth (except `/auth/*` and `/health`). |
| **Authorization** | Role-based access control per project: owner, editor, viewer. Membership checked via `MembershipService.require_role()`. See permission matrix below. |
| **Project sharing** | Email-based invite system. Invites auto-accept on registration. Session isolation per user. |
| **Encryption at rest** | Fernet (AES-128-CBC + HMAC-SHA256) for SSH keys, passwords, connection strings |
| **Query safety** | SafetyGuard blocks DML/DDL in read-only mode, dialect-aware parsing |
| **Rate limiting** | slowapi: 5/min register, 10/min login, 20/min chat, 10/min note execute |
| **CORS** | Configurable origins via `CORS_ORIGINS` env var |
| **SSH key handling** | In-memory for DB tunnels, temp file (0600) for Git only, never returned via API. Keys are user-scoped (user_id FK). `get_decrypted()` enforces ownership when `user_id` is provided. |
| **Shell injection prevention** | SSH exec template variables (`db_name`, `db_user`, `db_host`, `db_password`) are shell-escaped via single-quoting before substitution. Queries are piped via stdin. |
| **Invite scoping** | `revoke_invite()` enforces `project_id` to prevent cross-project invite revocation by guessing IDs. |
| **WebSocket auth** | JWT token passed as query parameter, validated before connection acceptance. Project membership verified before granting access. |

**Permission Matrix (Role-Based Access Control):**

| Operation | Owner | Editor | Viewer |
|---|---|---|---|
| Delete project, connection, repository | Yes | No | No |
| Delete DB index, sync data, all learnings, single learning | Yes | No | No |
| Delete custom rules | Yes | No | No |
| Manage invites (create, revoke), remove members | Yes | No | No |
| Trigger backup, view backups | Yes | No | No |
| Create/edit custom rules | Yes | Yes | No |
| Trigger DB indexing, repo indexing, code-DB sync | Yes | Yes | No |
| Create chat sessions, send messages | Yes | Yes | Yes |
| Save/delete own notes | Yes | Yes | Yes |
| Train agent (create learnings via feedback) | Yes | Yes | No |
| View all project data | Yes | Yes | Yes |
| Delete own SSH keys | Own keys only | Own keys only | Own keys only |

The frontend enforces this via the `usePermission()` hook which reads the active project's `userRole` from the app store. Delete buttons are hidden for non-owner users.

### Database Schema (Internal)

The agent uses SQLite (default) or PostgreSQL (recommended for production) to store its own data:

```
users            — id, email, password_hash (nullable for Google users), display_name, is_active, auth_provider (email|google), google_id, picture_url, created_at
projects         — id, name, description, repo_url, repo_branch, ssh_key_id, owner_id, default_rule_initialized, indexing_llm_provider, indexing_llm_model, agent_llm_provider, agent_llm_model, sql_llm_provider, sql_llm_model
connections      — id, project_id, name, db_type, ssh_*, db_*, ssh_exec_mode, ssh_command_template, ssh_pre_commands, is_read_only, is_active
ssh_keys         — id, user_id (FK→users), name, private_key_encrypted, passphrase_encrypted, fingerprint, key_type
project_members  — id, project_id, user_id, role (owner|editor|viewer), created_at  [UNIQUE(project_id, user_id)]
project_invites  — id, project_id, email, invited_by, role, status (pending|accepted|revoked), created_at, accepted_at
chat_sessions    — id, project_id, user_id, connection_id (FK→connections, SET NULL), title, created_at
chat_messages    — id, session_id, role, content, metadata_json (includes visualization payload + raw_result for re-rendering), tool_calls_json, user_rating, created_at
custom_rules     — id, project_id, name, content, format, is_default, created_at, updated_at
knowledge_docs   — id, project_id, doc_type, source_path, content, commit_sha, updated_at
commit_index     — id, project_id, commit_sha, branch, commit_message, indexed_files, created_at
rag_feedback     — id, project_id, chunk_id, source_path, doc_type, distance, query_succeeded, commit_sha, created_at
project_cache    — id, project_id, knowledge_json, profile_json, overview_text, overview_generated_at, created_at, updated_at
db_index         — id, connection_id (FK→connections CASCADE), table_name, table_schema, column_count, row_count, sample_data_json, ordering_column, latest_record_at, is_active, relevance_score, business_description, data_patterns, column_notes_json, query_hints, code_match_status, code_match_details, indexed_at  [UNIQUE(connection_id, table_name)]
db_index_summary — id, connection_id (FK→connections CASCADE, UNIQUE), total_tables, active_tables, empty_tables, orphan_tables, phantom_tables, summary_text, recommendations, indexed_at
agent_learnings  — id, connection_id (FK→connections CASCADE), category, subject, lesson, lesson_hash, confidence, source_query, source_error, times_confirmed, times_applied, is_active  [UNIQUE(connection_id, category, subject, lesson_hash)]
agent_learning_summaries — id, connection_id (FK→connections CASCADE, UNIQUE), total_lessons, lessons_by_category_json, compiled_prompt, last_compiled_at
saved_notes      — id, project_id (FK→projects CASCADE), user_id (FK→users CASCADE), connection_id (FK→connections SET NULL), title, comment, sql_query, last_result_json, last_executed_at, created_at, updated_at  [INDEX(project_id), INDEX(user_id)]
session_notes    — id, connection_id (FK→connections CASCADE), project_id, category (data_observation|column_mapping|business_logic|calculation_note|user_preference|verified_benchmark), subject, note, note_hash, confidence, is_verified, source_session_id, created_at, updated_at  [UNIQUE(connection_id, note_hash), INDEX(connection_id, category)]
data_validation_feedback — id, connection_id, session_id, message_id, query, metric_description, agent_value, user_expected_value, deviation_pct, verdict (confirmed|rejected|approximate|unknown), rejection_reason, resolution, resolved, created_at  [INDEX(connection_id), INDEX(message_id)]
data_benchmarks  — id, connection_id (FK→connections CASCADE), metric_key, metric_description, value, value_numeric, unit, confidence, source (agent_derived|user_confirmed|cross_validated), times_confirmed, last_confirmed_at, created_at  [UNIQUE(connection_id, metric_key)]
data_investigations — id, validation_feedback_id (FK→data_validation_feedback), connection_id, session_id, trigger_message_id, status (active|completed|failed|cancelled), phase, user_complaint_type, user_complaint_detail, user_expected_value, problematic_column, investigation_log_json, original_query, original_result_summary, corrected_query, corrected_result_json, root_cause, root_cause_category, learnings_created_json, notes_created_json, benchmarks_updated_json, created_at, completed_at
code_db_sync     — ... + required_filters_json, column_value_mappings_json (new columns)
backup_records   — id, created_at, reason (scheduled|initial_sync|manual), status (success|failed), size_bytes, manifest_json, backup_path, error_message
```

Managed via **Alembic migrations** (36 revisions: initial → custom_rules → users → branch_and_rag_feedback → project_cache_and_rag_commit_sha → user_rating → project_members_invites_ownership → google_oauth_fields → tool_calls_json → ssh_exec_mode → indexing_checkpoint → cascade_delete_project_fks → add_user_id_to_ssh_keys → per_purpose_llm_models → add_connection_id_to_chat_sessions → add_default_rule_fields → add_db_index_tables → add_indexing_status_to_summary → add_code_db_sync_tables → add_column_distinct_values → add_agent_learning_tables → ... → hardening_indexes_fk_constraints → add_saved_notes_table → ... → add_self_improvement_tables → add_picture_url_to_users → add_backup_records_table → add_overview_to_project_cache).

All child tables referencing `projects.id` use `ON DELETE CASCADE` so deleting a project automatically removes all related rows (connections, chat sessions, knowledge docs, commit indices, project cache, RAG feedback, members, invites, indexing checkpoints, saved notes).

---

## Legal Pages

The site includes publicly accessible Terms of Service and Privacy Policy pages:

| Route | File | Description |
|---|---|---|
| `/terms` | `frontend/src/app/(legal)/terms/page.tsx` | Terms of Service — covers acceptable use, data handling, open-source license, third-party services, liability |
| `/privacy` | `frontend/src/app/(legal)/privacy/page.tsx` | Privacy Policy — details what data is collected, what is NOT collected, LLM provider data sharing, retention, user rights |

Both pages share a layout (`frontend/src/app/(legal)/layout.tsx`) with navigation back to the app, cross-links between pages, and the contact email `contact@checkmydata.ai`.

Key points emphasized in both pages:
- CheckMyData.ai is **open source** — all data handling is auditable in the source code
- **No access to user database content** — query results are transient and not persisted
- **No analytics/tracking** — no third-party cookies, pixels, or behavioral profiling
- Credentials (database passwords, SSH keys) are **encrypted at rest**
- Users can **self-host** for full data sovereignty

Links to these pages appear on the login screen (AuthGate) and in the sidebar footer.

---

## Configuration

Copy `backend/.env.example` to `backend/.env` and set:

| Variable | Required | Description |
|---|---|---|
| `MASTER_ENCRYPTION_KEY` | **Yes** | Fernet key for encrypting stored credentials. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `JWT_SECRET` | **Yes (prod)** | Secret for signing JWT tokens. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `GOOGLE_CLIENT_ID` | No | Google OAuth Client ID from [Google Cloud Console](https://console.cloud.google.com/apis/credentials). Enables "Sign in with Google" button. No `GOOGLE_CLIENT_SECRET` needed (GIS ID-token flow). |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | No | Same value as above, set in `frontend/.env.local` for the GIS JavaScript SDK. |
| `OPENAI_API_KEY` | One of three | OpenAI API key (for GPT-4o, etc.) |
| `ANTHROPIC_API_KEY` | One of three | Anthropic API key (for Claude) |
| `OPENROUTER_API_KEY` | One of three | OpenRouter API key (multi-model proxy) |
| `DATABASE_URL` | No | Default: `sqlite+aiosqlite:///./data/agent.db`. For production: `postgresql+asyncpg://...` |
| `JWT_EXPIRE_MINUTES` | No | Token expiry (default: 1440 = 24h) |
| `CORS_ORIGINS` | No | JSON array of allowed origins (default: `["http://localhost:3000", "http://localhost:3100", "https://checkmydata.ai"]`) |
| `CHROMA_SERVER_URL` | No | Remote ChromaDB server URL. If empty (default), uses embedded PersistentClient |
| `CHROMA_EMBEDDING_MODEL` | No | Custom sentence-transformer model for ChromaDB embeddings (e.g. `nomic-ai/nomic-embed-text-v1`). If empty, uses ChromaDB's default `all-MiniLM-L6-v2` |
| `MAX_HISTORY_TOKENS` | No | Token budget for chat history before summarization kicks in (default: 4000) |
| `INCLUDE_SAMPLE_DATA` | No | Include sample rows in LLM prompt (default: false) |
| `DB_INDEX_TTL_HOURS` | No | How long before the database index is considered stale (default: 24) |
| `DB_INDEX_BATCH_SIZE` | No | Number of small/empty tables to batch per LLM call during DB indexing (default: 5) |
| `AUTO_INDEX_DB_ON_TEST` | No | Auto-trigger DB indexing after a successful connection test (default: false) |
| `CUSTOM_RULES_DIR` | No | Directory for file-based rules (default: `./rules`) |
| `LOG_FORMAT` | No | `text` (default, human-readable with timestamps) or `json` (structured, for production log aggregation) |
| `LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`. At INFO level, logs show: app startup/shutdown, user auth events, project/connection CRUD, chat request/response summaries, indexing pipeline start/end, SSH tunnel creation, connection test results, and all warnings/errors. Third-party library noise (SQLAlchemy queries, asyncssh handshakes, httpx requests) is silenced at INFO level. Set to DEBUG to see all internal details including workflow steps, SQL queries, and SSH lifecycle events. |

---

## Development Commands

### Local (no Docker)

| Command | Description |
|---|---|
| `make setup` | Full setup: venv, deps, .env, encryption key, migrations |
| `make dev` | Start backend (:8000) + frontend (:3100) |
| `make stop` | Stop background dev servers |
| `make logs` | Tail backend + frontend logs |
| `make test` | Run backend unit tests |
| `make test-integration` | Run backend integration tests |
| `make test-all` | Run all backend tests |
| `make test-frontend` | Run frontend vitest |
| `make lint` | Run ruff linter |
| `make check` | Run lint + all backend tests |
| `make migrate` | Apply Alembic migrations |
| `make clean` | Remove logs, caches, .next |

### Docker (OrbStack / Docker Desktop)

Requires [OrbStack](https://orbstack.dev) (recommended on macOS) or Docker Desktop.

| Command | Description |
|---|---|
| `make docker-up` | Build images, start containers, wait for healthchecks, print URLs |
| `make docker-down` | Stop and remove containers |
| `make docker-clean` | Stop containers **and remove volumes** (DB, repos, vectors) |
| `make docker-logs` | Tail backend + frontend container logs |

You can also run the scripts directly:

```bash
./scripts/dev-up.sh              # start
./scripts/dev-down.sh            # stop
./scripts/dev-down.sh --volumes  # stop + wipe data
```

---

## Testing

### Automated Tests

```bash
make check            # backend lint + all tests
make test-frontend    # frontend vitest
```

**Test counts:**
- Backend unit tests: 918 across 69 test files
- Backend integration tests: 153 across 19 test files
- Frontend tests: 135 across 18 test files
- **Grand total: 1,206 tests**

### Test Coverage by Module

| Module | Unit Tests | Integration Tests |
|---|---|---|
| Orchestrator | 8 (process_question, connector key, disconnect, enricher receives sync/rules/distinct_values) | — |
| Query Builder | 6 (dialect-aware prompts) | — |
| Validation Loop | 8 (first-try, retry, max attempts, safety, schema) | 6 (E2E retry flows) |
| Error Classifier | 18 (PG, MySQL, CH, Mongo, fallback) | — |
| Pre-Validator | 8 (valid, wrong col/table, ambiguous, fuzzy, MongoDB) | — |
| Post-Validator | 5 (success, error, empty, slow) | — |
| EXPLAIN Validator | 6 (PG, MySQL, error, warning, MongoDB skip) | — |
| SQL Parser | 16 (tables, columns, subqueries, CTEs, aggregations) | — |
| Schema Hints | 11 (fuzzy col/table, related tables, detail) | — |
| Retry Strategy | 16 (should_retry × 8, repair_hints × 8) | — |
| Context Enricher | 13 (column/table error, RAG, RAG filtering, sync context, rules context, distinct values, schema-qualified tables, column substring safety, history) | — |
| Query Repairer | 3 (success, no tool call, LLM exception) | — |
| Query Validation | 9 (data models, serialization) | — |
| Safety Guard | 17 (read-only, DML, DDL, MongoDB) | — |
| SSH Key Service | 10 (CRUD, validation, passphrase, in-use) | 3 |
| SSH Key Routes | 9 (list, create, delete, duplicate, in-use) | — |
| SSH Exec Connector | 15 (connect, execute, test, build_command, pre-commands, custom template) | — |
| CLI Output Parser | 17 (TSV, CSV, psql tuples, MySQL batch, generic, edge cases) | — |
| Exec Templates | 12 (structure, format, defaults, substitution, special chars) | — |
| SSH Exec Connections | — | 6 (CRUD with exec mode, test-ssh, ssh_user in response) |
| Viz/Export | 19 (table, chart, text, CSV, JSON, _build_raw_result) | — |
| Workflow Tracker | 18 (events, subscribe, step, queue, active workflows tracking, background pipeline filter, pipeline propagation in step/emit) | — |
| Workflow Routes | 4 (SSE format, filtering, pipeline) | — |
| Repo Analyzer | 18 (SQL files, ORM models, migrations, binary file filter, null-byte content guard, extra dirs, list_remote_refs: branches, default selection, access denied, timeout, empty) | 7 (check-access: success, denied, bad key, validation, auth, empty, many branches) |
| Project Profiler | 10 (Django, FastAPI, Express, Prisma, language, dirs, skip) | — |
| Entity Extractor | 15 (SQLAlchemy, Django, Prisma, TypeORM, Sequelize, Mongoose, Drizzle, entity map, dead tables, enums, usage, incremental) | — |
| File Splitter | 9 (Python, Prisma, JS/TS, Drizzle, generic, syntax error, names) | — |
| Indexing Pipeline | 9 (profile, knowledge, enrichment, dead warnings, service funcs, summary) | — |
| Project Summarizer | 12 (entities, tables, dead tables, enums, services, profile, cross-ref) | — |
| Incremental Indexing | 10 (knowledge serialization, profile serialization, deleted file handling, cache logic) | — |
| Doc Generator | 13 (LLM output, fallback, truncation, binary fallback placeholder, oversized fallback truncation, null-byte sanitization, binary detection, content sanitization) | — |
| Chunker | 5 (small doc, large doc, headings, empty) | — |
| Schema Indexer | 4 (markdown, prompt context, relationships) | — |
| DB Index Pipeline | 36 (ordering column, sample query, sample-to-json, detect-latest-record, is_enum_candidate, build_distinct_query, sqlite quoting) | — |
| DB Index Validator | 24 (fallback analysis, build prompt, analyze table, batch analysis, generate summary, code_match_status clamping) | — |
| Code-DB Sync Analyzer | 14 (analyze table, batch, summary, fallback, column notes dict, confidence clamping, sync_status clamping) | — |
| DB Index Service | 25 (prompt context, table detail, response format, status check, is_indexed guard, stale status handling) | — |
| Learning Analyzer | 10 (table extraction, table preference, column correction, format discovery, schema gotcha, performance hint) | — |
| Agent Learning Service | 4 (compile prompt empty/with learnings, category labels, invalid category) | — |
| MCP Server | 19 (auth: API key/JWT/anonymous, tools: list/query/schema/raw, resources: rules/knowledge/schema, server creation) | — |
| Custom Rules | 16 (file loading, YAML, context generation, default template, DB rule IDs in context) | 9 (CRUD, access control, default rule auto-creation) |
| Retry | 5 (success, retry, max attempts, callback) | — |
| LLMRouter | 14 (primary succeeds, fallback on failure, all-fail raises LLMAllProvidersFailedError, non-retryable stops chain, retries within provider, fallback chain ordering/filtering/default, unknown provider, no keys, close, OpenRouter/OpenAI format messages) | — |
| ConversationalAgent / OrchestratorAgent | 12 (text reply, text with connection, knowledge search, max iterations, error handling, LLM error friendly message, token accumulation, workflow_id, tool_call_log, thinking events on tool call, thinking events on final answer, thinking includes tool name) | 13 (full chat: text/SQL/knowledge flow, optional connection, stream events, rules_changed flag, user_id forwarding) |
| ToolExecutor | 52 (execute_query, search_knowledge, get_schema_info, get_custom_rules, get_entity_info, unknown tool, RAG threshold, get_db_index, get_sync_context, get_query_context, _format_table_context, auto_detect_tables, manage_custom_rules CRUD/validation/RBAC) | — |
| Prompt Builder | 13 (all combinations of connection/knowledge flags, re-visualization prompt, manage_rules capability/guideline) | — |
| Alembic | 2 (upgrade head, downgrade base) | — |
| API Routes | 23 (projects, connections, viz routes, active tasks, stale index/sync status reset, pipeline failure propagation, sync background failure propagation, startup stale reset) | — |
| Models Routes | 11 (sorting, cache, static providers, error fallback) | — |
| Connection Service | 25 (create, encrypt, sanitize, get, list, update, delete, test_connection, to_config: basic/SSH/MCP) | — |
| Repository Service | 10 (create, get, list_by_project, update, delete, error cases) | — |
| Rule Service | 15 (create, get, list_all scoping, update, delete, ensure_default_rule) | — |
| Project Cache Service | 8 (load_knowledge, load_profile, save create/update, deserialization error) | — |
| RAG Feedback Service | 7 (record single/multi/empty, truncation, get_stats aggregation/scoping) | — |
| Membership Service | 12 (add, get_role, require_role, remove, list, accessible) | — |
| Invite Service | 11 (create, duplicate, reject, revoke, accept, pending, auto-accept) | — |
| Auth | — | 11 (register, login, duplicate, wrong password, Google login, account linking, token validation) |
| Projects | — | 9 (CRUD lifecycle + RBAC: owner/viewer/non-member, member-scoped list) |
| Invites (routes) | — | 9 (create, list, revoke, accept, pending, members, remove, non-owner restrictions) |
| Connections | — | 5 (CRUD lifecycle + viewer access control) |
| Rules | — | 5 (CRUD + viewer access control) |
| Chat Sessions | — | 8 (create, delete, not found, session isolation, cross-user protection, connection_id, tool_calls_json in messages) |
| Chat Extended | — | 10 (update title, generate title, messages empty/not found, feedback submit/missing/analytics, auth checks) |
| AgentLearningService CRUD | 19 (create/dedup/fuzzy match/confirm/contradict/apply/deactivate/get/count/decay) | — |
| LearningAnalyzer Extended | 13 (full pipeline, negative feedback, edge cases, LLM analyzer cooldown/format) | — |
| SQLAgent ALM | 4 (extract_learnings fire/skip, no connection_id, track_applied) | — |
| Connection Operations | — | 18 (test connection: not found/mock success/failure, test-ssh, refresh-schema, index-db CRUD/status, learnings CRUD/status/summary/recompile, RBAC, auth) |
| Repo Operations | — | 12 (repo status, docs list/get, check-updates, repository CRUD, auth) |
| Visualizations | — | 8 (export CSV/JSON/XLSX, missing data, empty rows, render table, missing fields, auth) |
| Models | — | 5 (list default/openai/anthropic/openrouter mocked, auth) |
| WebSocket Auth | — | 4 (valid/invalid/empty/tampered token) |
| Learnings API | — | 11 (list/status/summary/update/toggle/delete/clear/recompile/auth) |
| Health | — | 2 (basic, modules) |
| Frontend (api) | 4 (fetch mock, auth headers) | — |
| Frontend (auth-store) | 4 (login, error, logout, restore) | — |
| Frontend (app-store) | 10 (setActiveProject, addMessage, localStorage persistence, updateMessageId, userRating, rawResult) | — |
| Frontend (task-store) | 13 (processEvent lifecycle, pipeline filtering, step updates with/without pipeline field, completed/failed, auto-dismiss timers, seedFromApi merge, manual dismiss, untracked pipeline_end ignored) | — |
| Frontend (ProjectSelector) | 8 (render, new button, list items, click selects project, edit form, delete button, create form, empty state) | — |
| Frontend (ConnectionSelector) | 10 (render, create button, list items, DB type badge, test button, index button, sync button, delete button, form fields, DB type switch) | — |
| Frontend (ChatPanel) | 9 (render, empty state, user/assistant messages, loading indicator, error display, scroll-to-bottom, input area, thinking log bouncing dots) | — |
| Frontend (ChatMessage) | 8 (user/assistant content, feedback buttons, no feedback for user, SQL query block, visualization, error+retry, markdown) | — |
| Note Service | 10 (create, get, list_by_project, update, delete, update_result, filtering, ordering) | — |
| Notes API | — | 12 (create, list, get, update, delete, execute, connection validation, membership checks, audit logging, auth) |
| SQLAgent | 20 (name, no config raises, text response, execute_query success/failure, get_schema_info overview/detail, custom rules, db_index, sync_context, query_context, learnings get/record, unknown tool, exception, max iterations, token usage, tool_call_log, learning extraction) | — |
| DataSanityChecker | 9 (all null, all zero, future dates, percentage sums, benchmark deviations, format warnings) | — |
| SessionNotesService | 10 (create, invalid category, duplicate, similar merge, context filtering, prompt compilation, verify, deactivate, delete all) | — |
| DataValidationService | 7 (record basic, record with rejection, get by id/message, unresolved filter, resolve, accuracy stats) | — |
| BenchmarkService | 6 (normalize key, create new, user confirmed, confirm existing, find, flag stale, get all) | — |
| FeedbackPipeline | 4 (confirmed → benchmark, approximate → benchmark+note, rejected → learning+note+stale, unknown) | — |
| InvestigationService | 8 (create basic, create all fields, update phase, append log, record finding, complete, fail, get active) | — |
| Entity Extractor Enhanced | 7 (query patterns SQL/ORM, constant mappings Python/JS/dict, scope filters Rails/Laravel, serialization roundtrip) | — |
| Feedback Loop Integration | 3 (rejection creates learning+note, confirmation strengthens benchmark, accuracy stats aggregate) | — |
| Frontend (ClarificationCard) | 5 (yes_no, multiple_choice, free_text, numeric_range rendering, onSubmit, context display) | — |
| Frontend (DataValidationCard) | 3 (quick actions, confirmation flow, rejection form) | — |
| Frontend (VerificationBadge) | 3 (verified, unverified, flagged rendering) | — |
| KnowledgeAgent | 12 (name, text response, search_knowledge results/empty/below threshold, get_entity_info list/detail/table_map/enums, unknown tool, max iterations, token usage) | — |
| VizAgent | 15 (name, empty/error results, single value numeric/text, preferred viz bar/pie cap, LLM recommendation/no tool, post-validate pie/line/bar, token usage, truncation, invalid JSON config) | — |
| MCPSourceAgent | 10 (name, no adapter, no tools, text response, tool call success/multiple/error, max iterations, set_adapter, token usage) | — |
| DatabasePipeline | 8 (index delegates, error propagates, sync delegates, get_status combines/no index/no sync, source_type, constructor) | — |
| MCPPipeline | 8 (index stores schemas/no tools/connection failure, sync noop, get_status with/without docs, source_type, constructor) | — |
| Pipeline Registry | 6 (get database/mcp/unknown/case-insensitive, registry entries, subclass check) | — |
| Multi-Stage Pipeline | 36 (complexity detection, plan validation, StageContext, StageValidator, QueryPlanner, StageExecutor, serialization, validation outcome) | — |
| Frontend (AuthGate) | 8 (login/register form, inputs, submit, google SSO, error, loading, auth passthrough) | — |
| Frontend (ChatInput) | 6 (render, typing, submit, empty guard, disabled, placeholder) | — |
| Frontend (RulesManager) | 8 (new button, empty state, rule items, edit/delete buttons, create form, cancel edit) | — |
| Frontend (SshKeyManager) | 6 (add button, empty state, key items, delete button, create form, submit) | — |
| Frontend (ReadinessGate) | 8 (status dashboard, bypass button, callback, warning, auto-bypass when ready, green indicators, staleness warning, last indexed time) | — |
| Frontend (Sidebar) | 5 (render, nav sections, collapse, workspace sections, sign out) | — |
| Frontend (InviteManager) | 6 (render, email+role inputs, invite button, members list, remove button except owner, pending invites) | — |

---

## Deployment

### Production — Heroku (primary)

The production environment runs on **Heroku** as two Docker container apps with Heroku Postgres.

**Live URLs:**

| Service | URL |
|---|---|
| Backend API | `https://api.checkmydata.ai/api` |
| Frontend | `https://checkmydata.ai` |
| Health check | `https://api.checkmydata.ai/api/health` |

**Architecture on Heroku:**
- `checkmydata-api` — container stack, `Dockerfile.backend`, Heroku Postgres (Essential-0)
- `checkmydata-web` — container stack, `Dockerfile.frontend`, connects to the API app

**Auto-deploy (CI/CD):**

Every push to `main` triggers automatic deployment via GitHub Actions (`.github/workflows/deploy.yml`):

1. CI workflow runs (lint, tests, type check)
2. If CI passes, deploy workflow starts automatically
3. Builds both Docker images for `linux/amd64`
4. Pushes to Heroku Container Registry
5. Releases both apps
6. Verifies backend health check

Required GitHub secret: `HEROKU_API_KEY` (already configured).

**Manual redeploy (if needed):**

```bash
# Login to container registry
heroku container:login

# Build for linux/amd64 (required on Apple Silicon)
docker build --platform linux/amd64 -t registry.heroku.com/checkmydata-api/web -f Dockerfile.backend .
docker build --platform linux/amd64 -t registry.heroku.com/checkmydata-web/web \
  --build-arg NEXT_PUBLIC_API_URL=https://api.checkmydata.ai/api \
  --build-arg NEXT_PUBLIC_WS_URL=wss://api.checkmydata.ai/api/chat/ws \
  -f Dockerfile.frontend .

# Push and release
docker push registry.heroku.com/checkmydata-api/web
docker push registry.heroku.com/checkmydata-web/web
heroku container:release web --app checkmydata-api
heroku container:release web --app checkmydata-web
```

**Setting up a new Heroku deployment from scratch:**

```bash
# 1. Create apps with container stack
heroku create checkmydata-api --stack container
heroku create checkmydata-web --stack container

# 2. Add Postgres to backend (replaces SQLite)
heroku addons:create heroku-postgresql:essential-0 --app checkmydata-api

# 3. Set backend env vars
heroku config:set \
  MASTER_ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  DEFAULT_LLM_PROVIDER=openai \
  OPENAI_API_KEY=sk-... \
  CORS_ORIGINS='["https://checkmydata.ai"]' \
  --app checkmydata-api

# 4. Set frontend env vars
heroku config:set \
  NEXT_PUBLIC_API_URL=https://api.checkmydata.ai/api \
  NEXT_PUBLIC_WS_URL=wss://api.checkmydata.ai/api/chat/ws \
  --app checkmydata-web

# 5. Build, push, and release (see "Redeploying" above)
```

**Heroku-specific details:**
- Heroku provides `DATABASE_URL` automatically via the Postgres addon; `config.py` converts `postgres://` to `postgresql+asyncpg://`
- Alembic migrations run automatically on every container startup
- Frontend `NEXT_PUBLIC_*` vars must be passed as `--build-arg` since Next.js bakes them into the bundle at build time
- Both Dockerfiles respect Heroku's dynamic `$PORT` environment variable

### Local Docker

```bash
docker compose up --build
```

Both services are containerized with health checks. The backend runs Alembic migrations before starting.

### DigitalOcean App Platform

App spec at `.do/app.yaml`. Set secrets in the dashboard:
- `MASTER_ENCRYPTION_KEY`, `JWT_SECRET`, `OPENAI_API_KEY`

### CI/CD

Two GitHub Actions workflows in `.github/workflows/`:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | Every push/PR to `main` | Backend lint (ruff), unit + integration tests, frontend type check + build |
| `deploy.yml` | After CI passes on `main` | Builds Docker images, pushes to Heroku, releases both apps, health check |

GitHub secret required: `HEROKU_API_KEY` — long-lived OAuth token for Heroku Container Registry access.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `MASTER_ENCRYPTION_KEY is not set` | Run `make setup` or manually generate and add to `.env` |
| `no such table: users` | Run `make migrate` to apply Alembic migrations |
| SSH key validation fails | Ensure you paste the *private* key in PEM format (starts with `-----BEGIN`) |
| LLM health check fails | Set at least one API key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENROUTER_API_KEY`) |
| Connection test fails | Verify SSH tunnel config: SSH host/user/key must reach the server, DB host should be `127.0.0.1` for tunneled connections. Check backend logs — all connector `test_connection()` failures and SSH errors are now logged with `logger.warning()`. |
| 429 Too Many Requests | Rate limiting active. Wait and retry. Limits: 20 chat/min, 5 register/min |
| Indexing returns 409 | Indexing is already running as a background task. Wait for it to finish (check `/status` endpoint or SSE events) |
| Indexing interrupted, want to restart fresh | Click "Index Repository" with `force_full=true` to discard the checkpoint and start from scratch |
| Stale checkpoint blocking indexing | Checkpoints older than 24h are auto-cleaned on startup. You can also use `force_full=true` to discard manually |
| `CharacterNotInRepertoireError` during indexing | Binary files (ELF, images) could leak null bytes into PostgreSQL. Multi-layer fix: (1) git-sourced `changed_files` now filtered by `DB_RELEVANT_EXTENSIONS` matching `_find_db_relevant_files()`, (2) `is_binary_file()` checks extension + null bytes, (3) post-read null-byte content guard in `analyze()`, (4) `doc_store.upsert()` strips `\x00` before INSERT, (5) `doc_generator` fallback detects binary content and returns placeholder, (6) `pipeline_runner` pre-filters binary files from `changed_files` before analysis and skips binary-looking enriched docs |
| `NotImplementedError: No support for ALTER of constraints in SQLite` | Migration `c7d2e8f31a45` now uses `op.batch_alter_table()` with `naming_convention` for SQLite compatibility. Pull latest and re-run `make migrate`. For Docker, run `docker compose down -v && docker compose up --build` to start fresh |

---

## Backup, Restore, and Migration Runbook

### Automated Daily Backups

The system includes an automated backup mechanism that runs daily at 00:00 UTC (configurable). It backs up the database (SQLite `.backup` or PostgreSQL `pg_dump`), ChromaDB vectors (local only), and custom rules directory. Backups are stored in `backend/data/backups/{timestamp}/` with a JSON manifest. The retention policy keeps the last 7 daily backups (configurable).

**Configuration (environment variables / `.env`):**

| Setting | Default | Description |
|---|---|---|
| `BACKUP_ENABLED` | `true` | Enable/disable automated backups |
| `BACKUP_HOUR` | `0` | Hour (UTC) to run daily backup |
| `BACKUP_RETENTION_DAYS` | `7` | Number of backups to retain |
| `BACKUP_DIR` | `./data/backups` | Backup storage directory |

**API endpoints (authenticated, owner only):**

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/backup/trigger` | Trigger a manual backup |
| `GET` | `/api/backup/list` | List available backups from disk |
| `GET` | `/api/backup/history` | List backup records from database |

An initial backup runs automatically on first startup if no backups exist yet.

### Manual Database Backup

**SQLite (development):**

```bash
cp backend/data/agent.db backend/data/agent.db.bak
```

**PostgreSQL (production):**

```bash
pg_dump -Fc "$DATABASE_URL" > backup_$(date +%Y%m%d_%H%M%S).dump
```

### Database Restore

**SQLite:**

```bash
cp backend/data/agent.db.bak backend/data/agent.db
```

**PostgreSQL:**

```bash
pg_restore --clean --if-exists -d "$DATABASE_URL" backup_YYYYMMDD_HHMMSS.dump
```

### Alembic Migrations

**Apply all pending migrations:**

```bash
cd backend && alembic upgrade head
```

**Check current migration state:**

```bash
cd backend && alembic current
```

**Rollback last migration:**

```bash
cd backend && alembic downgrade -1
```

**Rollback to a specific revision:**

```bash
cd backend && alembic downgrade <revision_id>
```

**Generate a new migration after model changes:**

```bash
cd backend && alembic revision --autogenerate -m "description_of_changes"
```

### Disaster Recovery

1. **Stop the service:** `docker compose down`
2. **Restore the database** from the latest backup (see above)
3. **Apply migrations:** `cd backend && alembic upgrade head`
4. **Restart:** `docker compose up -d`
5. **Verify health:** `curl http://localhost:8000/api/health`

### Vector Store (ChromaDB)

ChromaDB data is stored in `backend/data/chroma/`. To reset:

```bash
rm -rf backend/data/chroma/
# Restart the backend — it will recreate collections on next index
```

To back up ChromaDB, copy the directory:

```bash
cp -r backend/data/chroma/ backup_chroma_$(date +%Y%m%d)/
```

---

## Changelog

### 2026-03-21 — Multi-Stage Query Pipeline

**Complex query decomposition:**

- **QueryPlanner** (`backend/app/agents/query_planner.py`) — Detects complex queries using a fast heuristic (no LLM call) and decomposes them into 2-5 stages via a single LLM tool call. Each stage specifies the tool (query_database, search_codebase, analyze_results, synthesize), dependencies, validation criteria, and whether to checkpoint for user confirmation.

- **StageExecutor** (`backend/app/agents/stage_executor.py`) — Executes pipeline stages sequentially with validation gates. On failure: retries up to `max_stage_retries` (default 2) with error context injected, then pauses for user intervention. On checkpoint: returns intermediate results for user review before continuing.

- **StageValidator** (`backend/app/agents/stage_validator.py`) — Per-stage validation: expected columns, row count bounds, cross-stage consistency checks (e.g. `row_count <= stage1.row_count * 2`), and business rules (e.g. "no negative amounts").

- **StageContext** (`backend/app/agents/stage_context.py`) — In-memory state carrying structured `QueryResult` objects between stages. Serialises to compact summaries for DB persistence; restores on resume.

- **PipelineRun** (`backend/app/models/pipeline_run.py`) — DB model tracking execution plan, stage results, user feedback, and pipeline status. Auto-cleaned after `PIPELINE_RUN_TTL_DAYS` (default 7). Final answers are permanent in `chat_messages`.

**Orchestrator integration:**

- `OrchestratorAgent.run()` now detects complexity before entering the flat loop. Complex queries branch into QueryPlanner → StageExecutor. Simple queries are unaffected (zero overhead — heuristic only, no LLM call).
- Pipeline resume: when a user responds to a checkpoint or failure, the orchestrator loads the `PipelineRun`, restores `StageContext` from persisted summaries, and resumes execution from the appropriate stage.
- `ChatRequest` now accepts `pipeline_action`, `pipeline_run_id`, and `modification` fields for resume actions.

**SSE events (backend):**

- New event types: `plan`, `stage_start`, `stage_result`, `stage_validation`, `stage_complete`, `checkpoint`, `stage_retry`. Existing SSE events unchanged.

**Frontend:**

- **StageProgress** (`frontend/src/components/chat/StageProgress.tsx`) — Vertical step list showing per-stage status (pending/running/passed/failed/checkpoint/skipped), row counts, column names, and error messages. Checkpoint and failure states show Continue/Modify/Retry action buttons.
- **ChatPanel** integration — Pipeline events update `StageProgress` in real-time. Checkpoint/failure actions send pipeline resume requests.

**Prompts:**

- Orchestrator system prompt now mentions multi-stage capabilities to set user expectations.
- New planner prompt (`backend/app/agents/prompts/planner_prompt.py`) instructs the LLM to decompose queries with validation criteria and checkpoint placement.

**Tests:**

- 36 new tests in `backend/tests/unit/test_pipeline.py` covering: complexity detection, plan validation (cycles, missing deps, invalid tools), StageContext persistence roundtrip, StageValidator (columns, bounds, cross-stage), QueryPlanner (success, fallback, LLM failure), StageExecutor (checkpoint, resume, failure, validation retry), and serialization.

| Component | Tests | Notes |
|---|---|---|
| ComplexityDetection | 5 | heuristic scoring |
| PlanValidation | 6 | structure, cycles, deps |
| StageContext | 4 | set/get, context builder, persistence |
| StageValidator | 5 | columns, bounds, cross-stage, errors |
| QueryPlanner | 4 | success, invalid, exception, no-tool |
| StageExecutor | 5 | checkpoint, full run, resume, failure, retry |
| Serialization | 5 | plan, result roundtrips |
| ValidationOutcome | 3 | fail/warn/to_dict |

### 2026-03-20 — Agent Thinking Stream

**Real-time narration of agent reasoning in the chat UI:**

- The orchestrator, SQL agent, and knowledge agent now emit lightweight `thinking` events via `WorkflowTracker.emit()` at every decision point: before/after LLM calls, tool selection rationale, sub-agent dispatch, query execution results, schema loading, validation outcomes, visualization selection, and error/retry paths.
- A new SSE event type `thinking` is routed from the backend through `chat.py` to the frontend.
- `frontend/src/lib/api.ts` `askStream` accepts an `onThinking` callback for receiving thinking events.
- New `ThinkingLog` component (`frontend/src/components/chat/ThinkingLog.tsx`) renders a compact, auto-scrolling narration log with monospace font, max 120px height, animated entry dots, and the latest entry highlighted.
- `ChatPanel` integrates `ThinkingLog` as the primary thinking indicator: bouncing dots appear until the first thinking event arrives, then the log takes over. Tool call indicators appear alongside the log. The log is cleared on each new user message and on response completion.
- Backend: zero new infrastructure — reuses existing `tracker.emit()`. Frontend: capped at 50 entries to prevent memory bloat.
- 3 new backend tests (`TestThinkingEvents`) verify thinking events are emitted on tool calls, final answers, and include tool names. 1 new frontend test verifies bouncing dots when no thinking log is present.

### 2026-03-20 — Token Usage Tracking and Statistics

**Token usage tracking system:**

- New `TokenUsage` database table (`backend/app/models/token_usage.py`) persists per-request token usage: user, project, session, message, provider, model, prompt/completion/total tokens, and estimated cost in USD. Indexed on `(user_id, created_at)` for fast aggregation.
- Alembic migration `b3c4d5e6f7g8` creates the table with foreign keys to users, projects, and chat_sessions.
- `UsageService` (`backend/app/services/usage_service.py`) provides `record_usage()` for persistence and `get_period_comparison()` for 30-day aggregation with previous-period comparison and daily breakdown.
- Usage is automatically recorded after every chat response (both `/ask` and `/ask/stream` endpoints).
- LLM provider and model are now propagated through the agent pipeline (`LLMResponse.provider`, `AgentResponse.llm_provider/llm_model`) so each request is tagged with the actual provider used.
- Cost estimation uses cached OpenRouter pricing data (prompt + completion price per token). For direct OpenAI/Anthropic calls, cost is null since their pricing is not tracked.

**Usage API:**

- `GET /api/usage/stats?days=30` returns aggregated token stats for the authenticated user:
  - `current_period` / `previous_period`: prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, request_count
  - `change_percent`: percentage change for each metric vs the previous period
  - `daily_breakdown`: per-day totals for charting

**Enhanced per-message token display:**

- Chat messages now show "X in / Y out" tokens (input/output breakdown) instead of just total.
- Estimated cost badge shown when available (violet badge, e.g. "$0.0032").
- Expandable details include provider, model, and cost.

**Usage statistics panel in sidebar:**

- New `UsageStatsPanel` component (`frontend/src/components/usage/UsageStatsPanel.tsx`) with:
  - 2x2 grid of stat cards (input tokens, output tokens, total tokens, estimated cost)
  - Period-over-period change badges (green for decrease, amber for increase)
  - Mini bar chart showing daily token usage over the last 30 days
  - Request count summary
- Integrated as a collapsible "Usage" section in the sidebar (collapsed by default).

**Files changed:**

- `backend/app/models/token_usage.py` — new TokenUsage model
- `backend/app/models/__init__.py` — register model
- `backend/app/models/base.py` — register model in fallback/init
- `backend/alembic/env.py` — register model
- `backend/alembic/versions/b3c4d5e6f7g8_add_token_usage_table.py` — new migration
- `backend/app/services/usage_service.py` — new service
- `backend/app/api/routes/usage.py` — new API routes
- `backend/app/main.py` — register usage router
- `backend/app/llm/base.py` — add `provider` field to LLMResponse
- `backend/app/llm/router.py` — stamp provider on LLMResponse
- `backend/app/agents/orchestrator.py` — add `llm_provider`/`llm_model` to AgentResponse, capture from LLM calls
- `backend/app/api/routes/chat.py` — record usage, enrich token_usage metadata with provider/model/cost, cost estimation helper
- `frontend/src/lib/api.ts` — usage types and API client
- `frontend/src/components/chat/ChatMessage.tsx` — enhanced token display (in/out, cost, provider/model details)
- `frontend/src/components/usage/UsageStatsPanel.tsx` — new component
- `frontend/src/components/Sidebar.tsx` — usage section

### 2026-03-20 — Enhanced DISTINCT Values & Project Knowledge Overview

**Broader DISTINCT value collection during DB indexing:**

- Expanded `_is_enum_candidate` heuristic with ~15 additional name patterns (`region`, `locale`, `stage`, `direction`, `protocol`, `variant`, etc.), prefix patterns (`is_`, `has_`, `can_`, `allow_`), suffix patterns (`_code`), and type-based detection (`tinyint`, `smallint`, `int2`).
- New `_detect_low_cardinality_columns` function: scans sample data for columns with <= 3 distinct values not already caught by name/type heuristics. Catches unlabeled flag columns (e.g., `processed` with values `0, 1`).
- DISTINCT values are now injected into `table_index_to_detail` output, making them visible to the SQL agent when it examines individual tables.

**Project Knowledge Overview ("Agent Briefing"):**

- New `ProjectOverviewService` (`backend/app/services/project_overview_service.py`): generates a unified markdown overview combining all knowledge sources — DB index (table structure, row counts, DISTINCT values), Code-DB sync (data conventions, required filters, column value mappings, conversion warnings), custom rules, agent learnings (counts by category, top lessons), session notes and benchmarks, and repository profile (language, frameworks, ORMs, key directories).
- Overview stored in `project_cache.overview_text` with `overview_generated_at` timestamp. New Alembic migration `z3a4b5c6d7e8`.
- Auto-regenerated after: DB indexing completion, Code-DB sync completion, repo indexing completion, and custom rule create/update/delete.
- Injected into the orchestrator's system prompt (`PROJECT KNOWLEDGE OVERVIEW` section) so it can make better routing decisions.
- Available to the SQL agent via `get_db_index` with `scope="project_overview"`.

**Files changed:**

- `backend/app/knowledge/db_index_pipeline.py` — expanded patterns, type detection, low-cardinality detection
- `backend/app/services/db_index_service.py` — DISTINCT values in `table_index_to_detail`
- `backend/app/services/project_overview_service.py` — new
- `backend/app/models/project_cache.py` — `overview_text`, `overview_generated_at`
- `backend/alembic/versions/z3a4b5c6d7e8_add_overview_to_project_cache.py` — new migration
- `backend/app/api/routes/connections.py` — overview regeneration after DB index and sync
- `backend/app/api/routes/repos.py` — overview regeneration after repo index
- `backend/app/api/routes/rules.py` — overview regeneration after rule changes
- `backend/app/agents/prompts/orchestrator_prompt.py` — `project_overview` parameter
- `backend/app/agents/orchestrator.py` — loads and injects overview
- `backend/app/agents/sql_agent.py` — `project_overview` scope support
- `backend/app/core/tool_executor.py` — `project_overview` scope support
- `backend/app/agents/tools/sql_tools.py` — updated tool description/enum

**Tests:**

- `backend/tests/unit/test_distinct_expanded.py` — 26 tests for expanded heuristics and low-cardinality detection
- `backend/tests/unit/test_table_detail_distinct.py` — 5 tests for DISTINCT values in detail output
- `backend/tests/unit/test_project_overview_service.py` — 14 tests for overview service and prompt integration

### 2026-03-20 — UI, Backup, and Permissions Hardening

**Chat input redesign:**

- Restyled `ChatInput` to be narrower (`max-w-2xl`), centered on screen, with transparent background, softer borders (`border-zinc-700/50`, `rounded-xl`), and an icon-only send button for a cleaner look.

**Automated daily backup system:**

- New `BackupManager` class (`backend/app/core/backup_manager.py`): supports SQLite (`.backup` command) and PostgreSQL (`pg_dump`), ChromaDB directory copy, and custom rules directory copy. Includes retention policy (default 7 days) and JSON manifest per backup.
- Asyncio-based cron loop in `main.py` runs daily at 00:00 UTC (configurable via `BACKUP_HOUR`). Initial backup runs on first startup if no backups exist.
- New `BackupRecord` model and Alembic migration (`y2z3a4b5c6d7`) track backup history.
- API endpoints: `POST /api/backup/trigger`, `GET /api/backup/list`, `GET /api/backup/history`.
- Config settings: `BACKUP_ENABLED`, `BACKUP_HOUR`, `BACKUP_RETENTION_DAYS`, `BACKUP_DIR`.

**Delete confirmation hardening:**

- Enhanced `ConfirmModal` with `detail` text, `severity` levels (normal/warning/critical), and optional `confirmText` (type-to-confirm) for critical operations.
- Connection deletion now shows affected data and requires typing "DELETE".
- Project deletion requires typing the project name to confirm.
- SSH key deletion warns about lost tunnel access.
- Learnings "Clear all" requires typing "DELETE".
- Invite revoke now has a confirmation dialog.

**Permission system hardening:**

- Backend: repository delete changed from `editor` to `owner`; single learning delete changed from `editor` to `owner`; rule create/update changed from `owner` to `editor`.
- Frontend: new `usePermission()` hook returns `{ role, isOwner, canDelete, canEdit, canManageMembers }`.
- Delete buttons hidden for non-owner users in `ConnectionSelector`, `RulesManager`, `LearningsPanel`.
- Create/edit rule buttons hidden for viewers.
- Full permission matrix documented in Security Model section.

**Files changed:**

- `frontend/src/components/chat/ChatInput.tsx` — restyled
- `frontend/src/components/ui/ConfirmModal.tsx` — severity, detail, type-to-confirm
- `frontend/src/hooks/usePermission.ts` — new hook
- `frontend/src/components/connections/ConnectionSelector.tsx` — permission check, detailed warning
- `frontend/src/components/rules/RulesManager.tsx` — permission check
- `frontend/src/components/learnings/LearningsPanel.tsx` — permission check, detailed warning
- `frontend/src/components/projects/ProjectSelector.tsx` — detailed warning
- `frontend/src/components/projects/InviteManager.tsx` — revoke confirmation
- `frontend/src/components/ssh/SshKeyManager.tsx` — detailed warning
- `backend/app/api/routes/repos.py` — owner-only delete
- `backend/app/api/routes/connections.py` — owner-only learning delete
- `backend/app/api/routes/rules.py` — editor create/update
- `backend/app/core/backup_manager.py` — new
- `backend/app/api/routes/backup.py` — new
- `backend/app/models/backup_record.py` — new
- `backend/app/config.py` — backup settings
- `backend/app/main.py` — backup cron loop, initial backup

### 2026-03-19 — Terms of Service & Privacy Policy Pages

**New legal pages:**

- **`(legal)/layout.tsx`:** Shared layout for legal pages with header (logo + back-to-app link), centered content area (`max-w-3xl`), and footer with links to Terms, Privacy, and `contact@checkmydata.ai`.
- **`(legal)/terms/page.tsx`:** Comprehensive Terms of Service (16 sections) covering acceptance, service description, user accounts, open-source license, user data & database connections, SSH keys, acceptable use, intellectual property, third-party services, warranties disclaimer, liability limitation, indemnification, modifications, governing law, severability, and contact.
- **`(legal)/privacy/page.tsx`:** Comprehensive Privacy Policy (14 sections) covering collected information, information NOT collected, data usage, storage & security, third-party services (with LLM data-sharing table), open-source transparency, data retention & deletion, cookies, children's privacy, international transfers, user rights (GDPR), changes, and contact.
- **AuthGate.tsx:** Added Terms/Privacy/Contact links below the login form.
- **Sidebar.tsx:** Added Terms/Privacy links in the account footer.

### 2026-03-19 — Indexing Pipeline Parallelization & Optimization

**Repo indexing speed (backend):**

- **pipeline_runner.py:** LLM doc generation (Step 9) now runs in parallel batches of 5 with `asyncio.Semaphore(3)` concurrency. Expected 3-5x speedup on the slowest pipeline step.
- **pipeline_runner.py:** Pre-fetches all existing docs in a single query before the doc generation loop instead of N individual lookups.
- **pipeline_runner.py:** Caches the `git.Repo` instance for `_git_show` calls instead of re-creating it per file.

**DB indexing speed (backend):**

- **postgres.py:** Consolidated schema introspection from 4N+1 per-table queries to 5 bulk queries (columns, PKs, FKs, indexes all fetched in single queries). For 100 tables: 401 queries → 5.
- **mysql.py:** Same bulk query consolidation as Postgres.
- **db_index_pipeline.py:** Sample data and distinct value fetching now runs in parallel across tables with `asyncio.Semaphore(5)`.
- **db_index_pipeline.py:** Large-table LLM analysis calls now run in parallel with `asyncio.Semaphore(3)` instead of sequentially.

**SSH exec mode parity (backend):**

- **exec_templates.py:** Added `introspect_fks` and `introspect_indexes` templates for Postgres SSH exec mode.
- **ssh_exec.py:** Postgres exec introspection now fetches foreign keys, indexes, and row counts — matching native connector feature parity.

**Quality & cost (backend):**

- **doc_generator.py:** Capped `enrichment_context` to 3,000 chars to prevent token overflow and improve LLM output quality.
- **chunker.py:** Added 150-char overlap between adjacent chunks so RAG queries spanning boundaries get proper context.

**Caching & overhead reduction (backend):**

- **vector_store.py:** ChromaDB collection objects are now cached per `project_id`, eliminating 100+ redundant `get_or_create_collection` calls per indexing run.
- **ssh_tunnel.py:** Added 30-second time-based caching to `SSHTunnel.is_alive()`, eliminating repeated SSH echo checks during intensive operations.

**Cleanup & unification:**

- **code_db_sync_pipeline.py:** Replaced hardcoded `BATCH_SIZE=5` with `settings.db_index_batch_size` from config.
- **polling.ts (frontend):** Created shared `POLL_INTERVAL_MS` (3s) and `MAX_POLL_MS` (15min) constants used by both `ConnectionSelector` and `ReadinessGate`.
- **sql_agent.py:** Removed unused `SchemaIndexer` import and instance.
- **tool_executor.py:** Made `schema_indexer` parameter optional (unused internally but kept for backward compat).

### 2026-03-19 — Sync/Index Polling Never Detects Completion (frontend)

**Status polling not resumed on page reload:**

- **ConnectionSelector.tsx:** Extracted polling logic into reusable `startIndexPoll(id)` and `startSyncPoll(id)` helpers. The initial status `useEffect` now starts polling automatically when it detects an in-progress index or sync (`is_indexing === true` / `is_syncing === true`). Previously, polling only started when the user clicked the button, so a page refresh during sync left the UI stuck on "SYNC..." forever.

**Poll timeout too short for large databases:**

- **ConnectionSelector.tsx:** Increased `POLL_TIMEOUT_MS` from 10 minutes to 30 minutes. Databases with 150+ tables can take 15–20 minutes to sync; the old timeout fired a misleading "timed out" error while the backend was still processing successfully.

**SyncStatusIndicator stuck on "Syncing...":**

- **SyncStatusIndicator.tsx:** Added a 5-second polling interval while `sync_status === "running"`. Previously the indicator only fetched on connection change or task-store events, so it could miss completion if SSE events were lost or the page was reloaded mid-sync.

### 2026-03-19 — Sync Status & WorkflowProgress Fixes

**Sync status never marked as completed (backend):**

- **connections.py:** Fixed `_run_sync_background` setting `final_status = "idle"` on success, which overwrote the pipeline's `"completed"` status. The readiness endpoint (`is_synced()`) checks for `sync_status == "completed"`, so the ReadinessGate step 5 ("Sync code ↔ database") would never show as done. Changed to `final_status = "completed"`.

**WorkflowProgress compact spinner persists after completion (frontend):**

- **WorkflowProgress.tsx:** Fixed compact mode always showing the last step with `status === "started"` regardless of pipeline completion. The `pipeline_resume` meta-step stays `"started"` forever since it has no corresponding `"completed"` event. Compact mode now checks `pipelineStatus` and renders a checkmark/X icon when the pipeline finishes, instead of showing a perpetual spinner.

### 2026-03-19 — Sync System Accuracy Improvements

**Expanded repair context (backend):**

- **context_enricher.py:** Added `sync_query_tips` parameter. Repair context now includes a "Query Recommendations (from sync)" section alongside the existing "Data Format Warnings" section. Increased sync context budget from 1500 to 2000 chars for warnings, plus 1500 for tips.
- **sql_agent.py, orchestrator.py, tool_executor.py:** Replaced `_load_sync_warnings` / `_get_sync_warnings` with `_load_sync_for_repair` / `_get_sync_for_repair` that returns both warnings and query tips (including `query_recommendations` and `business_logic_notes`).

**Proactive sync injection into system prompt (backend):**

- **sql_prompt.py:** Added `sync_conventions` and `sync_critical_warnings` parameters. When sync data is available, a "CRITICAL DATA FORMAT RULES" section is injected directly into the system prompt with project-wide conventions and high-confidence conversion warnings.
- **sql_agent.py:** Added `_load_sync_for_prompt` method that loads `data_conventions` from sync summary and `conversion_warnings` from entries with confidence >= 4.

**Business logic and global notes surfaced (backend):**

- **sql_agent.py, tool_executor.py:** `_format_table_context` now includes `business_logic_notes` (truncated to 200 chars) per table.
- **sql_agent.py, tool_executor.py:** `_build_query_context` now includes `global_notes` from sync summary as "Data overview" header.
- **code_db_sync_service.py:** `sync_to_prompt_context` now renders `global_notes` as "Project Data Overview" section.

**Enriched sync analyzer inputs (backend):**

- **code_db_sync_pipeline.py:** `_build_db_context` now includes `column_distinct_values_json` (actual DB enum values) and `column_count`. Sample data budget increased from 500 to 800 chars. `_build_code_context` now includes service function snippets (truncated to 300 chars) and custom project rules relevant to each table. Pipeline loads rules via `CustomRulesEngine`.

**ALM deduplication with sync (backend):**

- **learning_analyzer.py:** Before storing `data_format` or `schema_gotcha` learnings, checks if an equivalent `conversion_warning` already exists in sync data. Skips duplicate learnings to reduce noise and save LLM calls.

**Cross-table join intelligence (backend):**

- **code_db_sync_analyzer.py:** Added `join_recommendations` parameter to `SYNC_SUMMARY_TOOL` and `SyncSummaryResult`. Summary generation prompt now receives FK relationships and co-usage patterns.
- **code_db_sync_pipeline.py:** Added `_build_fk_context` that collects FK relationships from code entities and identifies tables commonly used together. Passed to summary generation.
- **code_db_sync.py:** Added `join_recommendations` field to `CodeDbSyncSummary` model.
- **Migration:** `t5u6v7w8x9y0_add_join_recommendations_to_sync.py` adds the column.
- **sql_agent.py, tool_executor.py:** `_build_query_context` now includes "Recommended JOIN Paths" section from sync summary.

**Table map enrichment (backend):**

- **sql_agent.py:** `_build_table_map` now annotates tables with sync warning tags (e.g. `orders(~10K, order records) [!cents]`). Added `_extract_warning_tag` and `_build_enriched_table_map` helpers.

### 2026-03-19 — Sync Pipeline Bug Fixes

**Status overwrite fix (backend):**

- **connections.py:** Fixed `_run_db_index_background` overwriting successful `"completed"` status with `"idle"` in the finally block. DB index now correctly persists `"completed"` on success, matching the sync background task.

**Pipeline plugin signatures (backend):**

- **database_pipeline.py:** Fixed `DatabasePipeline.index()` — removed wrong `session=`, `workflow_id=`, `force_full=` kwargs and added missing `connection_config` resolution via `ConnectionService`. Fixed `sync_with_code()` — removed wrong kwargs, now calls `CodeDbSyncPipeline.run()` with correct `connection_id` and `project_id` parameters.

**Concurrent poll fix (frontend):**

- **ConnectionSelector.tsx:** Replaced single `indexPollRef` and `syncPollRef` refs with per-connection `Map<string, Timeout>` refs. Starting a poll for connection B no longer kills connection A's active poll. Cleanup on `setSyncing`/`setIndexing` is now connection-aware (only clears if the current value matches the finished connection).

**Sync indicator reactivity (frontend):**

- **SyncStatusIndicator.tsx:** Now detects both newly started (`running`) and newly finished tasks. Previously only refetched sync status when a task transitioned to a non-running state, so navigating to a connection with an active sync would not show "Syncing..." until completion.

**Workflow tracker safety (backend):**

- **workflow_tracker.py:** Wrapped `_broadcast` call in `end()` with try/except to ensure `workflow_id_var` is always cleaned up even if broadcasting the `pipeline_end` event fails.

### 2026-03-19 — UI Progress State and Label Fixes

**Stale progress state (frontend):**

- **Sidebar.tsx:** Fixed repo indexing progress widget and result message staying visible permanently after completion. Added auto-dismiss timer (5s for success, 15s for failure) that clears both `indexWorkflowId` and `indexResult`. Timer is properly cleaned up on project switch and re-index.

**Missing step labels (frontend):**

- **WorkflowProgress.tsx:** Added missing step labels for `pipeline_resume`, `no_changes`, `cleanup_deleted`, `project_profile`, `cross_file_analysis`, `enrich_docs`, `fetch_samples`, `load_context`, `validate_tables`, `store_results`, `generate_summary`. Removed stale `chunk_and_store` entry.
- **LogPanel.tsx:** Added `db_index`, `code_db_sync`, and `orchestrator` pipeline color/label mappings. Added full `STEP_LABELS` map so step names display as human-readable text instead of raw identifiers. Failed event details now render in error color.

**Sync status refresh (frontend):**

- **SyncStatusIndicator.tsx:** Now subscribes to the task store and auto-refreshes sync status when a `code_db_sync` or `db_index` task completes for the active connection.

### 2026-03-19 — Indexing Performance Fixes

**SSH tunnel health check (backend):**

- **ssh_tunnel.py:** Fixed `is_alive()` always returning `false` for SSH accounts with restricted shells (e.g. `nologin`). The check now treats a completed SSH command with an active listener as "alive" even when the echo marker fails. Previously, every `get_or_create()` call killed and recreated the tunnel, causing connection losses for concurrent MySQL queries and adding ~2.5 minutes of startup delay.

**Indexing pipeline performance (backend):**

- **pipeline_runner.py:** Added early exit when `detect_changes` reports 0 changed + 0 deleted files and a previous index exists. Skips all expensive steps (analyze, cross-file analysis, enrich, generate_docs) and jumps directly to `record_index`. Reduces no-change re-index from ~50 minutes to ~30 seconds.
- **pipeline_runner.py:** During incremental indexing, unchanged files with existing docs are now skipped entirely in the `generate_docs` loop — no LLM call is made. Only files in `changed_files` are sent to the LLM.
- **pipeline_runner.py:** Wired up `prev_content` for the diff-based doc update path. For changed files with existing docs, the previous raw content is loaded via `git show` so `DocGenerator.generate()` can use a lighter diff-based prompt instead of regenerating from scratch.
- **pipeline_runner.py:** Extracted `_record_and_finish()` method to share the record_index + cleanup logic between the normal path and the early-exit path. Code-DB stale markers are now only set when there are actual file changes.

**Log noise reduction (backend):**

- **vector_store.py:** Changed `VectorStore.__init__` log from INFO to DEBUG. Since new instances are created per status-polling request, the INFO-level "ChromaDB: using local PersistentClient" message was spamming logs every ~4 seconds.

### 2026-03-19 — Chat Session Persistence Fixes

**Critical fixes (frontend):**

- **useRestoreState:** Fixed aggressive localStorage wipe on transient errors (network timeout, 500, etc.). Now only clears persisted IDs on 403/404 (permanent access errors). Transient failures preserve IDs for retry on next refresh and reset the `ran.current` guard so the restore can re-run.
- **ChatPanel:** Added `restoringState` loading indicator — users now see a "Restoring your session..." animation instead of an empty app while the async restore runs.
- **Sidebar:** Chat History section shows skeleton placeholders during restore instead of an empty state.
- **auth-store:** `restore()` now validates JWT `exp` claim before setting the user as authenticated. Expired tokens are cleared immediately, preventing the cascade where all API calls fail with 401 and `handleSessionExpired` nukes all localStorage.
- **ChatSessionList:** `handleDelete` now calls `setActiveSession(null)` (with `persistId`) instead of raw `setState`, ensuring `active_session_id` is cleared from localStorage when the active session is deleted.
- **ProjectSelector:** `handleDelete` now calls proper setter functions (`setActiveProject`, `setActiveConnection`, `setActiveSession`, etc.) instead of raw `setState`, ensuring all three localStorage keys are cleared when the active project is deleted.

**Minor improvements:**

- **SessionResponse (backend):** Added `created_at` field with `from_attributes=True` so frontend can display session age and sort locally.
- **ChatSession (frontend):** Added `created_at` to the TypeScript interface.
- **api.ts:** Removed unused `createSession` method (dead code — sessions are created implicitly via the streaming ask endpoint).

### 2026-03-18 — Comprehensive Audit Fixes

**Critical runtime fixes (backend):**

- **main.py:** Fixed shutdown crash — `chat._orchestrator` did not exist; corrected to `chat._agent._orchestrator._sql._connectors`. Made `run_migrations()` non-blocking via `asyncio.to_thread()`.
- **models/base.py:** Fixed `_fallback_create_all()` calling `asyncio.run()` inside an already-running event loop; now delegates to a thread pool when a loop is active.
- **chat.py (streaming):** Fixed SSE streaming generator using the request-scoped DB session after it was closed; the generator now creates its own session via `async_session_factory()`. Awaited WebSocket `relay_task` cancellation properly.
- **connections.py:** Fixed `_run_sync_background` never setting status to `"completed"` (now `"idle"`) on success — status was stuck at `"running"` forever.
- **workflow_tracker.py:** Increased subscriber queue size from 256 to 1024 and added logging when subscribers are dropped due to full queues.

**Critical fixes (frontend):**

- **ConnectionSelector:** `handleUpdate` now includes all MCP fields (`mcp_transport_type`, `mcp_server_command`, `mcp_server_args`, `mcp_server_url`, `mcp_env`) and MCP validation on update path.
- **ReadinessGate:** No longer silently bypasses the gate when the readiness fetch fails; shows an error state with Retry and Chat Anyway options.
- **useRestoreState:** Now toasts on all restore failures (not just 403). Resets the `ran` flag when `isAuthenticated` becomes false so restore re-runs after logout/login.

**Medium fixes (backend):**

- **connection_service.py:** Added `mcp_env` encryption/handling in `update()`, `mcp_server_args` serialization in update path, and null-guard for `ssh_pre_commands` slicing.
- **orchestrator.py:** Guarded `tc.arguments` for `None` in all handler methods; improved unknown tool error message to list available tools and added a `logger.warning`.

**UX improvements (frontend):**

- **AuthGate:** Added email regex validation, clear error on mode switch, descriptive loading text ("Signing in..." / "Creating account..."), and a loading state during `restore()` to avoid a flash of the login form.
- **ChatMessage:** Synced `userRating` state with the message prop via `useEffect`; added loading/disabled state on feedback buttons; replaced non-null assertions with optional chaining for metadata access. Fixed stale closure in `handleVizTypeChange`.
- **ProjectSelector:** Added loading spinner and error toast during project selection.
- **ConfirmModal:** Now supports a `destructive` option — non-destructive confirmations show an accent-colored button instead of red.
- **API client:** Added 60-second request timeout, explicit 403 handling with user-friendly message, and ensured `askStream` rejects its promise on 401/403.
