# CheckMyData.ai

[![CI](https://github.com/CheckMyData-AI/checkmydata-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/CheckMyData-AI/checkmydata-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AI-powered database query agent that analyzes Git repositories, understands database schemas, and lets you query databases through natural language chat with rich data visualization.

**Supported databases**: PostgreSQL, MySQL, ClickHouse, MongoDB
**LLM providers**: OpenAI, Anthropic, OpenRouter

## Quick Start

```bash
git clone https://github.com/CheckMyData-AI/checkmydata-ai.git
cd checkmydata-ai
make setup    # Install deps, create .env, run migrations
make dev      # Backend on :8000, frontend on :3100
```

Open `http://localhost:3100` to see the landing page, then click **Get Started** to register. See [INSTALLATION.md](INSTALLATION.md) for detailed setup instructions.

### Website Structure

| Route | Description |
|-------|-------------|
| `/` | Public landing page with product overview |
| `/login` | Login / registration page |
| `/app` | Main application (requires authentication) |
| `/about` | About page — mission, tech stack |
| `/contact` | Contact information and channels |
| `/support` | FAQ, documentation links, support channels |
| `/terms` | Terms of Service |
| `/privacy` | Privacy Policy |
| `/dashboard/[id]` | Shared dashboard viewer |
| `/sitemap.xml` | Auto-generated sitemap |

## Documentation

| Document | Description |
|----------|-------------|
| [vision.md](vision.md) | Product vision and guiding principles |
| [INSTALLATION.md](INSTALLATION.md) | Setup and deployment instructions |
| [USAGE.md](USAGE.md) | How to use the application |
| [API.md](API.md) | REST API reference |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design and module overview |
| [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) | Deep-dive: orchestrator, memory, LLM routing, feedback loops |
| [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) | UI design system, tokens, and component guidelines |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [ROADMAP.md](ROADMAP.md) | Future plans and priorities |
| [FAQ.md](FAQ.md) | Common questions and troubleshooting |
| [SECURITY.md](SECURITY.md) | Security policy and reporting |
| [SUPPORT.md](SUPPORT.md) | Getting help |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community standards |

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
│  │  batch · dashboards · usage · data-graph · insights · demo    │   │
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

The system has **five main flows**:

1. **Onboarding flow**: New users see a guided 5-step wizard (connect database -> test connection -> index schema -> connect code repo -> ask first question). Users can skip any step or try a demo project with sample data via `POST /api/demo/setup`. The `is_onboarded` flag on the User model tracks completion (`POST /api/auth/complete-onboarding`).
2. **Setup flow**: Register/login -> add SSH keys -> create project (with Git repo) -> create database connection (with SSH tunnel) -> index repository
3. **Chat flow**: Ask a question in natural language (or click a smart suggestion) -> the **OrchestratorAgent** routes to the appropriate sub-agent (SQLAgent for DB queries, KnowledgeAgent for codebase Q&A, or direct text response) -> VizAgent picks the best chart type for SQL results -> results returned with visualization and follow-up suggestions. Uses SSE streaming with agent-level progress events. Chat history is token-budget-managed and older messages are summarized to stay within limits. New sessions show schema-based and history-based query suggestions as clickable chips. A cost/performance preview below the chat input shows estimated token usage, context budget utilization, and session running totals. The orchestrator uses an **adaptive step budget** (default 25 iterations) with step-aware wrap-up prompts, final LLM synthesis on exhaustion, per-project/per-request step overrides, and a **continuation protocol** that lets users resume analysis cut short by the step limit.
4. **Knowledge flow**: Git repo is analyzed via a multi-pass pipeline (project profiling -> entity extraction -> cross-file analysis -> enriched LLM doc generation) -> chunks stored in ChromaDB for RAG retrieval
5. **Sharing flow**: Project owner invites collaborators by email -> invitee receives an email notification via Resend -> invited users register and are auto-accepted (the owner gets an acceptance confirmation email) -> each user gets isolated chat sessions while sharing the same project data and connections. New users also receive a welcome email on registration.

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

### 2a. Guided Onboarding Wizard

First-time users (before `is_onboarded` is set) see a 5-step onboarding wizard:

1. **Connect your database** — select db type (PostgreSQL, MySQL, ClickHouse, MongoDB), enter host/port/credentials, optionally configure SSH tunnel
2. **Test connection** — auto-runs on mount, shows animated status (spinner -> checkmark/error), auto-advances on success
3. **Index your database** — kicks off schema analysis so the AI understands your tables; can be skipped
4. **Connect your code (Optional)** — link a Git repo for deeper codebase understanding
5. **Ask your first question** — pre-populated example question to try the chat immediately

Additional options:
- **"Try demo instead"** button on step 1 calls `POST /api/demo/setup` to create a sample project
- **"Skip setup entirely"** link at the bottom marks onboarding complete without any setup
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
- Click the badge to open the **LearningsPanel** popup — view, edit, deactivate, or delete individual lessons
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

**Self-Improvement System Enhancements (v2):**

- **InvestigationAgent wired up** — The "Wrong Data" button now launches `InvestigationAgent.run()` as a background task; the agent diagnoses issues, updates investigation status in real time, and records findings
- **Benchmark comparison active** — `DataSanityChecker.check_against_benchmark()` now runs after every SQL query, comparing results against stored verified metrics and flagging deviations
- **Periodic learning decay** — `decay_stale_learnings()` and `decay_stale_notes()` run daily via the backup cron loop, preventing outdated advice from persisting indefinitely
- **Live learning injection** — The orchestrator prompt now includes a "RECENT AGENT LEARNINGS" section with the top 15 high-confidence learnings, updated per-query
- **Expanded sanity checks** — DataSanityChecker now detects: negative values in positive-metric columns, duplicate GROUP BY keys, single-row results for breakdown questions, date range mismatches vs. question intent
- **Learning prioritization** — `compile_prompt()` sorts learnings by composite score (confidence × 0.4 + log(confirmed) × 0.4 + log(applied) × 0.2), caps at 30 learnings, marks ★CRITICAL for 5+ confirmations
- **Cross-connection learning transfer** — `schema_gotcha` and `performance_hint` learnings from sibling connections in the same project are included in the prompt (deduplicated, marked as `[from sibling]`)
- **Proactive data probes** — After DB indexing, `ProbeService` runs sample queries on the top 5 tables by row count, checking for NULL rates, empty tables, and sanity anomalies. Creates session notes for findings
- **Learning conflict detection** — When creating a new learning, the system detects conflicting lessons (same category/subject with negation flips) and deactivates the weaker one
- **Investigation → sync enrichment** — When a user confirms an investigation fix with `missing_filter` or `column_format` root cause, the findings are pushed into `CodeDbSync` via `add_runtime_enrichment()`
- **Feedback analytics API** — `GET /data-validation/analytics/{project_id}` returns aggregated stats: accuracy rate, verdict breakdown, top error patterns, learnings by category, benchmark count, investigation status counts. Lightweight `GET /data-validation/summary/{project_id}` returns just accuracy_rate, total_validations, active_learnings, benchmark_count
- **Data Quality Dashboard** — `FeedbackAnalyticsPanel` integrated into the sidebar Analytics section. Shows Data Confidence Score (color-coded progress bar), first-try success rate, total learnings/validations/benchmarks, horizontal verdict breakdown bar (confirmed/approximate/rejected/unknown), top error patterns, and empty state guidance
- **Incremental overview updates** — `ProjectOverviewService.save_overview()` now hashes each section (DB, sync, rules, learnings, notes, profile) and only regenerates changed sections, with section hashes persisted in `project_cache.section_hashes_json`

**New files:**
- `backend/app/services/probe_service.py` — Data health probe runner
- `backend/tests/unit/test_probe_service.py` — Unit tests for `ProbeService` (table limits, session notes, disconnect on error, `_probe_table` paths)
- `backend/alembic/versions/c5d6e7f8g9h0_add_section_hashes_to_project_cache.py` — Migration for `section_hashes_json`
- `frontend/src/components/analytics/FeedbackAnalyticsPanel.tsx` — Feedback analytics dashboard component

**Frontend components:** `ClarificationCard`, `DataValidationCard`, `InsightCards`, `VerificationBadge`, `WrongDataModal`, `InvestigationProgress`, `ResultDiffView` (all in `frontend/src/components/chat/`), `FeedbackAnalyticsPanel` (in `frontend/src/components/analytics/`)

**API endpoints** (prefix `/api/data-validation/`):
- `POST /validate-data` — Record user validation feedback
- `GET /validation-stats/{connection_id}` — Aggregated accuracy statistics
- `GET /benchmarks/{connection_id}` — All verified benchmarks
- `GET /summary/{project_id}` — Compact analytics summary (accuracy_rate, total_validations, active_learnings, benchmark_count)
- `POST /investigate` — Start "Wrong Data" investigation
- `GET /investigate/{id}` — Poll investigation progress
- `POST /investigate/{id}/confirm-fix` — Accept or reject investigation fix

### 8c. Natural Language Data Insights and Trend Narration

Every SQL query result is automatically analyzed for patterns using pure Python computation (no LLM calls). The `InsightGenerator` (`backend/app/core/insight_generator.py`) detects:

1. **Trends** — When a temporal column is present (date, month, year, etc.), checks if numeric columns show >10% change from first to last value. Reports upward/downward trends with percentage change.
2. **Outliers** — For numeric columns with 5+ values, flags rows where values are >2 standard deviations from the mean. Reports the outlier value, direction, and average.
3. **Concentration** — Checks if the top 3 entries account for >50% of the total in the first numeric column. Reports the concentration percentage.
4. **Totals summary** — For single-row results, describes each numeric value in context.

Each insight includes a `type`, `title`, `description`, and `confidence` score (0.0-1.0). Insights are generated after query execution in the SQL agent pipeline and passed through the orchestrator to the SSE stream.

**Frontend: InsightCards** (`frontend/src/components/chat/InsightCards.tsx`) renders insights as a compact card strip below the visualization. Cards are color-coded by type (blue for trends, amber for outliers, purple for concentration). Each card expands on click to show the full description and a "Drill down" button that sends a contextual follow-up question.

**Executive Summary** — A "Summary" button appears on SQL result messages. Clicking it calls `POST /api/chat/summarize` which generates a one-paragraph executive summary using a lightweight LLM call, displayed inline below the button.

**New files:**
- `backend/app/core/insight_generator.py` — Pure-Python insight detection (trends, outliers, concentration, totals)
- `frontend/src/components/chat/InsightCards.tsx` — Compact insight card strip component

**API endpoint:**
- `POST /api/chat/summarize` — Generate executive summary for a SQL result message (requires `message_id` and `project_id`)

**Modified files:**
- `backend/app/agents/sql_agent.py` — Added `insights` field to `SQLAgentResult`, calls `InsightGenerator.analyze()` after successful query execution
- `backend/app/agents/orchestrator.py` — Added `insights` field to `AgentResponse`, passes insights from SQL results
- `backend/app/api/routes/chat.py` — Includes insights in message metadata and SSE stream payload, added `/summarize` endpoint
- `frontend/src/components/chat/ChatMessage.tsx` — Renders `InsightCards` below visualization, adds "Summary" button with inline display
- `frontend/src/components/chat/ChatPanel.tsx` — Passes insights through metadata to ChatMessage
- `frontend/src/lib/api.ts` — Added `chat.summarize()` API method

### 8d. Data Processing & Enrichment Pipeline

The orchestrator can enrich query results with derived data between query steps using the `process_data` meta-tool. This enables multi-step analysis workflows where raw data is transformed, enriched, filtered, and aggregated before further analysis. Multiple `process_data` calls can be chained sequentially.

**Available operations:**

- **`ip_to_country`** — Converts IP address columns to country codes (ISO 3166-1 alpha-2) and country names using an offline GeoIP database (`geoip2fast`). No external API calls required. Results are cached in a two-tier cache (in-memory LRU + SQLite persistent) so repeated lookups across requests and restarts are near-instant even at millions of unique IPs. Adds `{column}_country_code` and `{column}_country_name` columns to the result.
- **`phone_to_country`** — Converts phone number columns to country codes and names using an offline E.164 international dialing code prefix mapping (~250 countries/territories). Includes Canadian area code disambiguation (US vs CA within the NANP +1 zone). Adds `{column}_country_code` and `{column}_country_name` columns.
- **`aggregate_data`** — Groups rows by one or more columns and computes aggregation functions. **Multiple functions per column supported** (e.g., `amount:sum,amount:avg,user_id:count_distinct,*:count`). Supported functions: `count`, `count_distinct`, `sum`, `avg`, `min`, `max`, `median`. Optional `sort_by` and `order` (asc/desc) params for controlling result ordering.
- **`filter_data`** — Filters rows by column value after enrichment. Supports operators: `eq`, `neq`, `contains`, `not_contains`, `gt`, `gte`, `lt`, `lte`, `in`. Can exclude empty/null values with `exclude_empty`.

**Typical chained workflow:**

1. `query_database` — fetch raw data (e.g., purchases with buyer IPs)
2. `process_data(ip_to_country)` — enrich with country columns
3. `process_data(filter_data)` — optionally exclude Unknown countries
4. `process_data(aggregate_data)` — group by country, compute multiple stats (sum, avg, count_distinct, etc.), sort by value descending
5. VizAgent automatically produces a chart/table for aggregated results
6. LLM analyzes the compact aggregated result

**Cross-message persistence:** Enriched data survives across conversation turns for 5 minutes, enabling follow-up questions without re-running the full enrichment pipeline.

**Architecture:**
- `backend/app/services/geoip_service.py` — Singleton `GeoIPService` wrapping `geoip2fast` for offline IP-to-country lookups with two-tier cache
- `backend/app/services/geoip_cache.py` — `GeoIPCache` with in-memory LRU (100k entries) + SQLite persistent storage (millions of records). Config: `GEOIP_CACHE_ENABLED`, `GEOIP_CACHE_DIR`, `GEOIP_MEMORY_CACHE_SIZE`
- `backend/app/services/phone_country_service.py` — Singleton `PhoneCountryService` with offline E.164 dialing code mapping (including Canadian area codes)
- `backend/app/services/data_processor.py` — `DataProcessor` with pluggable operations (`ip_to_country`, `phone_to_country`, `aggregate_data`, `filter_data`) that transform `QueryResult` objects
- The `process_data` tool is available in both the simple orchestrator loop (up to 25 iterations, configurable) and the complex multi-stage pipeline (`QueryPlanner` + `StageExecutor`, up to 10 stages)
- When `process_data` is included in parallel tool calls, the orchestrator forces sequential execution to prevent race conditions on shared state
- After `aggregate_data`, VizAgent is triggered to produce visualizations for the aggregated result
- Pipeline `process_data` stages emit fine-grained progress events for UI feedback

**Example user queries this enables:**
- _"Find the pattern between buyer country (by IP) and which product they buy"_
- _"From which countries do users make outgoing calls, and to which countries do they call?"_
- _"What is the average check by buyer country? Show total revenue, count, and unique buyers too"_
- _"Group outgoing calls by source country and destination country, sort by count descending"_
- _"How many unique buyers per country? Exclude unknown countries"_

### 8b. Query Cost and Performance Preview

Before sending a query, the chat interface shows an estimated token cost and context budget utilization so users can understand resource usage.

**How it works:**
- `GET /api/chat/estimate?project_id=X&connection_id=Y` computes approximate prompt token counts by measuring the size of each context component: schema/table map, custom rules, agent learnings, and project overview. It uses the user's 30-day average completion tokens for the completion estimate. If OpenRouter pricing data is cached, it returns an estimated USD cost.
- The response includes a `context_utilization_pct` showing what percentage of the `MAX_HISTORY_TOKENS` budget is consumed by fixed context (schema + rules + learnings + overview), and a `breakdown` with per-component token counts.

**Frontend components:**
- `CostEstimator` — Displays "~{tokens} tokens" with a tooltip showing the full breakdown, a cost badge (when pricing is available), and a thin utilization bar (green < 60%, amber 60-80%, red > 80%). Fetches the estimate once when project/connection changes.
- `ContextBudgetIndicator` — A thin stacked horizontal bar showing color-coded segments: schema (blue), rules (purple), learnings (amber), overview (teal), history remaining (gray). Each segment shows a tooltip with its token count on hover.
- **Session cost tracking** — The Zustand store tracks cumulative `sessionTokens` and `sessionCost` for the active session. These are incremented from each assistant message's `token_usage` metadata and displayed next to the cost estimator. Values reset on session change.
- **Rotation imminent flag** — The estimate response includes `rotation_imminent: true` when context utilization approaches the session rotation threshold (default 90%).

**New files:**
- `frontend/src/components/chat/CostEstimator.tsx` — Token/cost estimate display with tooltip breakdown
- `frontend/src/components/chat/ContextBudgetIndicator.tsx` — Stacked bar visualization of context budget allocation

**API endpoint:**
- `GET /api/chat/estimate?project_id=X&connection_id=Y` — Returns estimated token counts, cost, utilization percentage, and per-component breakdown

**Modified files:**
- `backend/app/api/routes/chat.py` — Added `/estimate` endpoint with `CostEstimateResponse` model
- `frontend/src/lib/api.ts` — Added `CostEstimate`, `CostEstimateBreakdown` types and `chat.estimate()` method
- `frontend/src/stores/app-store.ts` — Added `sessionTokens`, `sessionCost`, `addSessionUsage()`, `resetSessionUsage()` to the store
- `frontend/src/components/chat/ChatPanel.tsx` — Integrated CostEstimator, ContextBudgetIndicator, and session usage display

### 8c. Auto-Session Rotation

When a conversation approaches the LLM context window limit, the system automatically summarizes the current session and seamlessly continues in a new session, preserving all context.

**How it works:**
- Before each agent run, the backend estimates the token count of the chat history. If usage reaches the configured threshold (default 95% of `MAX_CONTEXT_TOKENS`), session rotation triggers automatically.
- The system generates a rich LLM-based summary of the current session, capturing: main questions asked, SQL queries and results, data insights, and any rules or preferences established.
- A new session is created with title "Continued: {old title}" and the summary injected as a system message. The user's current question is forwarded to the new session.
- An SSE event `session_rotated` is emitted with `{old_session_id, new_session_id, summary_preview, message_count, topics}`. The frontend silently switches to the new session.
- A visual `SessionContinuationBanner` appears inline in the chat as a thin divider showing "Conversation continued (N messages summarized)". Clicking it expands to show the summary text and topic tags.
- No popup, no modal, no toast — the transition is smooth and non-intrusive.

**Configuration (environment variables):**
- `SESSION_ROTATION_ENABLED` — Enable/disable auto-rotation (default: `true`)
- `SESSION_ROTATION_THRESHOLD_PCT` — Context usage percentage that triggers rotation (default: `95`)
- `SESSION_ROTATION_SUMMARY_MAX_TOKENS` — Maximum tokens for the carry-over summary (default: `500`)

**New files:**
- `backend/app/services/session_summarizer.py` — Rich LLM-based session summary generation with fallback
- `frontend/src/components/chat/SessionContinuationBanner.tsx` — Expandable inline banner for session boundaries

**Modified files:**
- `backend/app/config.py` — Added `session_rotation_enabled`, `session_rotation_threshold_pct`, `session_rotation_summary_max_tokens`
- `backend/app/api/routes/chat.py` — Session rotation logic in `ask_stream`, `rotation_imminent` in estimate response
- `backend/app/agents/orchestrator.py` — `context_usage_pct` in `AgentResponse`, suppressed noisy context usage thinking emissions
- `backend/app/llm/errors.py` — Improved `LLMTokenLimitError` user message
- `backend/app/core/backup_manager.py` — Heroku-aware backup skip for managed Postgres
- `frontend/src/lib/api.ts` — `session_rotated` SSE event handling, `onSessionRotated` callback
- `frontend/src/components/chat/ChatPanel.tsx` — Session rotation handler, removed context budget toast
- `frontend/src/components/chat/ChatMessage.tsx` — Renders `session_continuation` messages as `SessionContinuationBanner`
- `frontend/src/components/connections/ConnectionHealth.tsx` — Fixed polling storm (ref-based callback, 30s min interval)
- `backend/app/main.py` — Added retry logic to lifespan migration step

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
├── Data enrichment → process_data (ip_to_country / phone_to_country / aggregate_data)
│   ↓
│   Enriches/aggregates last query result with derived columns or grouped stats
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
10. **Chat History Search** — press **Cmd+K** (Mac) or **Ctrl+K** (Windows/Linux) to open the search bar in the Chat History sidebar section. Type at least 2 characters to search across all your chat messages and SQL queries in the current project. Results appear in a dropdown with:
    - Session title and relative timestamp
    - Content snippet with the matching text highlighted
    - SQL query preview (if the message contained a query)
    - Keyboard navigation (Arrow Up/Down, Enter to select, Escape to close)
    - Clicking a result loads that session and its full message history

    The search uses SQL LIKE queries against `chat_messages.content` and `metadata_json` (which stores the SQL query). It is rate-limited to 30 requests/minute. The input is debounced (300ms) to avoid excessive API calls while typing.

11. **SQL Explanation and Learning Mode** — every SQL result message includes tools to help you understand the generated queries:
    - **Complexity badge** — a small color-coded pill (Simple/Moderate/Complex/Expert) shown next to the "View SQL Query" toggle, computed client-side via regex (counts JOINs, detects CTEs, window functions, recursive queries)
    - **"Explain SQL" link** — click to request an LLM-powered plain-English explanation of the query. The explanation panel shows the complexity badge and a markdown-rendered breakdown of each clause. Explanations are cached server-side per SQL hash (up to 100 entries) so repeated clicks are instant.
    - **"Executive Summary" button** — generates a one-paragraph summary of the query results suitable for sharing in Slack or email. Uses the question, answer text, and first 20 rows of data as context. The summary appears in a collapsible violet panel with a copy button.
    - Both features use the project's configured LLM model and are rate-limited (30/min for explain, 20/min for summarize).

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
   - When an invite is created, the invitee receives an **email notification** (via [Resend](https://resend.com)) with the project name, inviter name, role, and a link to sign up.
   - When the invited user **registers** with the invited email, they are automatically added to the project with the specified role. New users also receive a **welcome email**.
   - If the user already has an account, they can **accept the invite** from the "Pending Invitations" section that appears in the sidebar.
   - When an invite is accepted, the **project owner receives a confirmation email** with the new member's name and email.
   - Each user has **their own isolated chat sessions** — they cannot see other users' conversation history.
   - All users share the **same project data**: connections, indexed knowledge base, and custom rules.
   - Email notifications require `RESEND_API_KEY` to be configured. Without it, the invite flow works normally but no emails are sent.
   - All user-provided values in email templates are HTML-escaped to prevent injection. Transient Resend errors (429 rate-limit, 500 server) are retried up to 3 times with exponential backoff. Emails include category tags (`welcome`, `invite`, `invite-accepted`) for Resend dashboard analytics.

4. **Managing access**:
   - **Delete** a pending invite before it's accepted (revokes the invitation)
   - **Resend** a pending invite email if the invitee hasn't received it or needs a reminder (rate-limited to 5/min, uses a unique idempotency key per resend to bypass Resend dedup)
   - **Remove** a member (owners cannot be removed). The removed user loses access immediately.
   - **View** all current members and their roles in the InviteManager panel. Pending invites show relative timestamps (e.g. "Sent 2h ago").

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
   - Collapsible **Chart** section with interactive chart visualization (bar, line, pie, scatter) rendered from stored `visualization_json`
   - Collapsible **Agent Response** section with the full answer text
   - Collapsible **SQL Query** section with copy button
   - Collapsible **Result** section with data table

3. **Refresh data**: Each saved note has a **🔄 Refresh** button (with label). Clicking it re-runs the SQL query against the original database connection and updates the stored result. The refreshed result is also posted as a message in the currently active chat session (prefixed with `[Refreshed]`) so you can see it in context alongside your conversation. This is useful for monitoring queries that you check regularly.

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

6. **Collaborative sharing**:
   - Each note card has a **Share with team** toggle (users icon). When shared, the note becomes visible to all project members.
   - Shared notes display a "Shared" badge and the sharer's display name.
   - The Notes panel has **scope tabs**: **All** (own + shared), **Mine** (own only), **Shared** (only notes shared by others).
   - `GET /api/notes?project_id=X&scope=mine|shared|all` controls which notes are returned.

**API endpoints**: `POST /api/notes`, `GET /api/notes?project_id=X&scope=mine|shared|all`, `GET /api/notes/{id}`, `PATCH /api/notes/{id}`, `DELETE /api/notes/{id}`, `POST /api/notes/{id}/execute`

### 16a. Team Dashboards

The **Dashboards** feature lets you compose saved queries into grid-based dashboard views for team-wide monitoring.

1. **Create a dashboard**: In the Sidebar under "Dashboards", click "New Dashboard". Enter a title, choose a 2-column or 3-column grid layout, and add cards by selecting from your saved queries (including shared ones).

2. **Dashboard cards**: Each card on the dashboard displays:
   - Note title
   - Visualization type badge
   - Last refreshed time
   - Data table with results (up to 50 rows inline)

3. **Actions**:
   - **Add Card** — opens a picker to select from available saved notes
   - **Remove Card** — removes a card from the dashboard
   - **Refresh All** — re-executes all card queries to get fresh data
   - **Save Dashboard** — persists the layout and card configuration
   - **Edit** — opens the dashboard builder (editor/owner only)

4. **Viewing**: Click a dashboard in the sidebar to navigate to `/dashboard/{id}` — a full-screen page with the grid layout, header with title and last-updated time, and refresh controls.

5. **Sharing & Permissions**: Dashboards are shared with the team by default (`is_shared = true`). All project members with at least "viewer" role can see shared dashboards. Only **editors** and **owners** can create, edit, or delete dashboards. Viewers have read-only access.

6. **Auto-refresh**: Cards can have a `refresh_interval` (seconds) configured per card. The dashboard page sets up intervals to automatically re-execute queries.

**API endpoints**: `POST /api/dashboards`, `GET /api/dashboards?project_id=X`, `GET /api/dashboards/{id}`, `PATCH /api/dashboards/{id}`, `DELETE /api/dashboards/{id}`

### 17. Scheduled Queries and Data Alerts

The **Schedules** sidebar section lets you set up recurring SQL queries that run automatically on a cron schedule. When configured with alert conditions, the system evaluates results and fires in-app notifications.

**Creating a schedule:**
1. Click "New Schedule" in the Schedules sidebar section
2. Enter a title and SQL query
3. Choose a cron preset (every hour, daily at 9 AM, every Monday, etc.) or enter a custom cron expression
4. Optionally add alert conditions: pick a column name, comparison operator (`>`, `<`, `=`, `>=`, `<=`, `% change`), and threshold value
5. The schedule runs automatically; you can also click "Run Now" for manual execution

**Alert conditions** support:
- Standard comparisons: `gt`, `lt`, `eq`, `gte`, `lte` — compare any numeric column against a threshold
- Percentage change: `pct_change` — triggers when the value changes by more than X% between the last two rows

**Notification system:**
- A notification bell icon in the sidebar header shows the unread count
- Clicking it opens a dropdown listing recent notifications with timestamps
- Alerts from scheduled queries appear as "alert" type notifications with the triggered condition message
- "Mark all read" clears the unread counter

**Schedule management:**
- Toggle active/inactive with the pause/play button
- View run history (last 50 runs) with status, duration, and timestamps
- Edit any schedule's title, SQL, cron expression, or alert conditions
- Delete schedules with confirmation

**Background scheduler loop:**
- Runs every 60 seconds as a background task in the FastAPI lifespan
- Picks up all active schedules where `next_run_at <= now`
- Connects to the configured database, executes the SQL, evaluates alert conditions
- Records each run with status (`success`, `failed`, `alert_triggered`) and timing
- Automatically computes the next run time after each execution

**Technical details:**
- Cron parsing via `croniter` library
- Models: `ScheduledQuery` (schedule config + state), `ScheduleRun` (execution history), `Notification` (in-app alerts)
- All tables use `ON DELETE CASCADE` from their parent foreign keys
- Frontend: `ScheduleManager` component in sidebar, `NotificationBell` in header

**API endpoints**: `POST /api/schedules`, `GET /api/schedules?project_id=X`, `GET /api/schedules/{id}`, `PATCH /api/schedules/{id}`, `DELETE /api/schedules/{id}`, `POST /api/schedules/{id}/run-now`, `GET /api/schedules/{id}/history`, `GET /api/notifications`, `GET /api/notifications/count`, `PATCH /api/notifications/{id}/read`, `POST /api/notifications/read-all`

### 18. Smart Connection Health Monitoring and Auto-Reconnect

The system continuously monitors database connection health in the background and automatically recovers from failures.

**How it works:**
- A background task (`_health_check_loop`) runs every 5 minutes, checking all active connectors via lightweight `test_connection()` calls
- Each connection is assigned a health status: **healthy** (responding normally), **degraded** (high latency >3s or single failure), or **down** (2+ consecutive failures)
- Health state tracks: latency in ms, last check timestamp, consecutive failure count, and last error message
- Status changes are broadcast as `connection_health` SSE events via WorkflowTracker, enabling real-time frontend updates

**SSH tunnel auto-reconnect:**
- When `SSHTunnelManager.get_or_create()` detects a dead tunnel via `is_alive()`, it automatically attempts reconnection
- Up to 3 retry attempts with exponential backoff (2s, 4s, 6s) before raising an error
- Each reconnection attempt is logged for debugging

**Frontend indicators:**
- **ConnectionSelector**: Each connection shows a small health dot next to the test-status dot. Green = healthy, amber = degraded, red = down. A "RECONNECT" button appears when a connection is down. A warning banner shows below unreachable connections.
- **ChatPanel**: An amber bar ("Connection may be slow") appears when the active connection is degraded. A red bar ("Connection is down. Attempting reconnect...") with a retry button appears when the connection is down.
- All health indicators update in real-time via SSE events without polling.

**Manual reconnect:**
- Users can trigger a manual reconnection attempt via `POST /api/connections/{id}/reconnect`
- This creates a fresh connector, tests the connection, and returns the updated health state

**Technical details:**
- `ConnectionHealthMonitor` class in `backend/app/core/health_monitor.py` manages all health state in-memory
- Health checks use `asyncio.wait_for` with a 10-second timeout to avoid blocking
- The monitor only checks connectors that are currently in the active connector pool (recently used connections)
- `ConnectionHealth.tsx` component subscribes to SSE events for live updates and renders inline health status

**API endpoints**: `GET /api/connections/{id}/health`, `GET /api/connections/health?project_id=X`, `POST /api/connections/{id}/reconnect`

### 19. Bulk Operations and Batch Query Execution

The **Batch Query Runner** lets you execute multiple SQL queries in sequence against a single database connection, collect all results, and export them as a multi-sheet XLSX workbook.

**Opening the batch runner:**
- Click the **layers icon** in the chat area header to open an empty batch runner
- Click the **"Batch"** button in the Saved Queries panel header to pre-populate the batch with all saved notes

**Creating a batch:**
1. Enter a batch title and select a connection from the dropdown
2. Add queries manually: click "Add Query", enter a title and SQL for each
3. Add from saved notes: click "From Saved Notes", select notes from a checklist picker
4. Reorder queries with up/down arrow buttons, remove with the trash button
5. Click "Run All" to execute

**Execution behavior:**
- Queries run sequentially (not in parallel) to avoid overloading the database
- A progress bar shows X/N completed in real-time (polled every 1.5s)
- If a query fails, the error is recorded and execution continues with the next query
- Final batch status: `completed` (all succeeded), `partially_failed` (some failed), `failed` (all failed)
- SSE progress events are emitted via WorkflowTracker for each query

**Viewing results:**
- After execution completes, the **BatchResults** modal opens automatically
- Tabbed view: each tab shows a query's title, status dot (green/red), and row count
- Each tab displays a sortable data table with the query results
- Failed queries show the error message and the SQL that was attempted
- **Report View** toggle shows all results vertically in a printable layout
- **Export All as XLSX** creates a multi-sheet Excel file (one sheet per query, sheet names truncated to 31 chars)

**Batch history:**
- Previous batches are stored in the `batch_queries` table and can be listed/retrieved via API
- Each batch records: user, project, connection, queries, results, status, and timestamps

**Technical details:**
- Model: `BatchQuery` with JSON fields for queries and results
- Service: `BatchService` handles creation, execution (with SSE events), and XLSX export
- XLSX export uses `openpyxl` (same dependency as single-query export)
- Frontend: `BatchRunner` (modal for creating/running), `BatchResults` (tabbed results viewer)
- API returns `202 Accepted` immediately; execution happens in a background `asyncio.create_task`

**API endpoints**: `POST /api/batch/execute`, `GET /api/batch/{id}`, `GET /api/batch?project_id=X`, `DELETE /api/batch/{id}`, `POST /api/batch/{id}/export`

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
│  process_data    → _handle_process_data()                        │
│                    Enriches/aggregates last QueryResult in-memory │
│                    Operations: ip_to_country, phone_to_country,  │
│                    aggregate_data (group_by + sum/avg/count/…)    │
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
| `has_connection = True` | `query_database`, `process_data`, `manage_rules` |
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
| `LLMTokenLimitError` | No (per-provider); falls back to next provider | Context/output token limit exceeded |
| `LLMContentFilterError` | No | Content policy refusal |
| `LLMAllProvidersFailedError` | Yes (3s) | Every provider in the fallback chain failed |

The `LLMRouter` retries each provider up to 3 times with exponential backoff before falling through to the next provider. Non-retryable errors skip retries on the same provider: `LLMAuthError` stops the entire chain, while `LLMTokenLimitError` falls back to the next provider (which may have a larger context window). The `OrchestratorAgent` adds a second retry layer around the router call itself, catches token limit errors specifically for trim-and-retry recovery, and maps all LLM errors to user-friendly messages.

**Resource management & resilience:**

- **MCP adapter cleanup** — `_handle_query_mcp_source` wraps the entire adapter lifecycle (connect → work → disconnect) in a `try/finally` block. The `disconnect()` call is itself wrapped in a safety `try/except` so a disconnect failure never masks the real error.
- **External call retry** — `ConnectionService.test_connection()` retries `connector.connect()` up to 3 times with exponential backoff for transient errors (`TimeoutError`, `ConnectionError`, `OSError`). The MCP pipeline's `adapter.connect()` uses the same retry pattern.
- **Pipeline failure cleanup** — `IndexingPipelineRunner.run()` catches exceptions from the entire step pipeline, marks the checkpoint as `pipeline_failed`, emits a tracker failure event, and returns a result with `status="failed"` instead of propagating the exception.
- **Streaming fallback safety** — `LLMRouter.stream()` tracks whether any tokens have been yielded. If the provider stream fails *after* tokens were sent, it raises immediately (to avoid duplicate/corrupted output). Fallback to the next provider only happens if the failure occurs before any tokens are yielded.
- **Streaming timeout** — The SSE endpoint (`/ask/stream`) wraps the agent task in `asyncio.wait_for()` with a 120-second timeout. On timeout, a structured error event is sent and the stream closes gracefully. An inner safety timeout (150s) in the event loop itself prevents indefinite hangs even if `pipeline_end` is lost.
- **Structured SSE error events** — Error events sent via SSE include `error_type`, `is_retryable`, and `user_message` fields so the frontend can display appropriate UI (retry buttons for retryable errors, no retry for permanent ones like auth or content policy violations).
- **Error toast duration** — Error toasts persist for 10 seconds (vs. 4 seconds for success/info) to ensure users can read the message.
- **Context window resilience** — A `ContextBudgetManager` allocates token budgets for system prompt, schema, rules, learnings, and overview (configured via `max_context_tokens`). Before each LLM call, `trim_loop_messages()` condenses old tool results and collapses assistant+tool pairs into summaries. When usage exceeds 70%, a wrap-up instruction is injected. On `LLMTokenLimitError`, the router falls back to providers with larger context windows and the orchestrator trims aggressively and retries once. `MODEL_CONTEXT_WINDOWS` maps model names to their context sizes.
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
| `backend/app/core/context_budget.py` | `ContextBudgetManager` — priority-based token budget allocation for system prompt elements |
| `backend/app/core/history_trimmer.py` | `trim_history()` for chat history, `trim_loop_messages()` for in-loop context management |
| `backend/app/llm/router.py` | `LLMRouter` — provider fallback chain, health checks, `get_context_window()`, `MODEL_CONTEXT_WINDOWS` |

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
│   ├── insight_generator.py ← Pure-Python trend/outlier/concentration detection
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
│   ├── saved_note.py   ← SavedNote: user-scoped saved SQL queries per project (with team sharing)
│   ├── dashboard.py    ← Dashboard: team dashboard with grid layout of note cards
│   ├── session_note.py ← SessionNote: agent working memory (per-connection observations)
│   ├── data_validation.py ← DataValidationFeedback + DataInvestigation models
│   ├── benchmark.py    ← DataBenchmark: verified metric values for sanity-checking
│   └── request_trace.py ← RequestTrace + TraceSpan: persisted orchestrator execution traces
├── services/           ← Business logic layer
│   ├── project_service.py, connection_service.py
│   ├── repository_service.py ← CRUD for ProjectRepository
│   ├── ssh_key_service.py, chat_service.py
│   ├── rule_service.py, default_rule_template.py, auth_service.py
│   ├── membership_service.py ← Role checking, member CRUD, accessible projects
│   ├── invite_service.py ← Create/accept/revoke/resend invites, auto-accept on registration
│   ├── email_service.py ← Transactional emails via Resend (welcome, invite, acceptance) with HTML-escaped user input, retry on transient errors, and category tags
│   ├── rag_feedback_service.py ← Record & query RAG effectiveness (version-scoped)
│   ├── project_cache_service.py ← Persist/load ProjectKnowledge + ProjectProfile between runs
│   ├── checkpoint_service.py ← CRUD for indexing checkpoints (resumable pipeline state)
│   ├── agent_learning_service.py ← CRUD, dedup, confidence management for learnings
│   ├── db_index_service.py  ← CRUD + formatting for database index entries
│   ├── note_service.py ← CRUD for saved notes (create, list, update, delete, update_result) with scope filtering
│   ├── dashboard_service.py ← CRUD for dashboards (create, list_for_project, update, delete)
│   ├── scheduler_service.py ← CRUD + cron logic for scheduled queries and run history
│   ├── session_notes_service.py ← CRUD, fuzzy dedup, prompt compilation for agent notes
│   ├── data_validation_service.py ← CRUD + accuracy stats for validation feedback
│   ├── benchmark_service.py ← Create/confirm/flag benchmarks for verified metrics
│   ├── feedback_pipeline.py ← Process validation feedback → learnings + notes + benchmarks
│   ├── investigation_service.py ← Lifecycle management for data investigations
│   ├── code_db_sync_service.py ← ... + add_runtime_enrichment() for investigation findings
│   ├── trace_persistence_service.py ← Persist WorkflowTracker events as request traces + spans
│   ├── logs_service.py  ← Query service for request logs (users, requests, trace detail, summary)
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
All components use semantic design tokens from DESIGN_SYSTEM.md (no raw Tailwind palette classes).

src/
├── app/
│   ├── (marketing)/       ← Public marketing pages (shared header/footer layout)
│   │   ├── layout.tsx     ← Marketing layout: sticky header, footer with nav columns
│   │   ├── page.tsx       ← Landing page: hero, features, how-it-works, open-source CTA
│   │   ├── about/page.tsx ← About page: mission, tech stack, open-source philosophy
│   │   ├── contact/page.tsx ← Contact page: email channels, GitHub links
│   │   ├── support/page.tsx ← Support page: FAQ, docs links, support channels
│   │   ├── terms/page.tsx ← Terms of Service
│   │   └── privacy/page.tsx ← Privacy Policy
│   ├── login/page.tsx     ← Dedicated login/register page (CheckMyData.ai branded)
│   ├── app/page.tsx       ← Main app: AuthGate → Sidebar + ChatPanel + LogPanel
│   ├── layout.tsx         ← Root layout: DM Sans + JetBrains Mono fonts, SEO metadata, wraps in ClientShell
│   ├── sitemap.ts         ← Dynamic sitemap.xml for all public pages
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
    │   ├── FormModal.tsx      ← Reusable form modal shell (title, close, focus trap, backdrop)
    │   ├── LlmModelSelector.tsx ← Reusable LLM provider+model selector (stacked layout)
    │   └── Spinner.tsx        ← Reusable loading spinner
    ├── auth/AuthGate.tsx   ← Route guard: redirects unauthenticated users to /login
    ├── auth/AccountMenu.tsx ← Account settings: change password, sign out, delete account
    ├── Sidebar.tsx         ← Collapsible sidebar (w-64 ↔ w-16), Notion/Linear-style navigation with
    │                          single scroll area, grouped Setup/Workspace sections, subtle dividers
    ├── chat/
    │   ├── ChatPanel.tsx   ← Message list + knowledge-only mode toggle + error retry
    │   ├── ChatMessage.tsx ← Individual message with response_type-aware rendering + retry button
    │   ├── ChatSearch.tsx  ← Cmd+K searchable chat history with debounced LIKE search, highlighted snippets, SQL query preview
    │   ├── ChatSessionList.tsx ← Session switcher with active left bar, "Show all N" cap, inline hover delete
    │   └── ToolCallIndicator.tsx ← Real-time tool call progress during streaming
    ├── projects/
    │   ├── ProjectSelector.tsx  ← CRUD + role badges + active left bar + inline hover action overlay
    │   └── InviteManager.tsx    ← Invite users, resend/delete invites, manage members, timestamps, toasts
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
| `GET` | `/api/chat/search?project_id=X&q=term&limit=20` | Search chat messages and SQL queries across project sessions |
| `POST` | `/api/chat/feedback` | Submit thumbs up/down feedback on a message |
| `GET` | `/api/chat/analytics/feedback/{project_id}` | Aggregated feedback stats |
| `POST` | `/api/chat/ask` | Send question (blocking) |
| `POST` | `/api/chat/ask/stream` | Send question (SSE streaming) |
| `POST` | `/api/chat/explain-sql` | LLM-powered SQL explanation with complexity rating |
| `POST` | `/api/chat/summarize` | Generate executive summary of a message's query results |
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
| `POST` | `/api/invites/{project_id}/invites/{id}/resend` | Resend invite email (owner only, 5/min) |
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
| `POST` | `/api/data-validation/anomaly-analysis` | Run Anomaly Intelligence on provided data |
| `POST` | `/api/data-validation/anomaly-scan/{cid}` | Scan connection tables for anomalies |
| `POST` | `/api/visualizations/render` | Render visualization |
| `POST` | `/api/visualizations/export` | Export data (CSV/JSON/XLSX) |
| `GET` | `/api/workflows/events` | SSE workflow progress |
| `GET` | `/api/tasks/active` | List currently running background tasks |
| `GET` | `/api/health` | Basic health check |
| `GET` | `/api/health/modules` | Per-module health status |
| `POST` | `/api/backup/trigger` | Trigger a manual backup |
| `GET` | `/api/backup/list` | List available backups from disk |
| `GET` | `/api/backup/history` | List backup records from database |
| `GET` | `/api/data-graph/{project_id}/summary` | Data Graph summary (metric/relationship counts) |
| `GET` | `/api/data-graph/{project_id}/metrics` | List discovered metrics |
| `POST` | `/api/data-graph/{project_id}/metrics` | Create or update a metric definition |
| `DELETE` | `/api/data-graph/{project_id}/metrics/{id}` | Delete a metric |
| `GET` | `/api/data-graph/{project_id}/relationships` | List metric relationships |
| `POST` | `/api/data-graph/{project_id}/relationships` | Add a metric relationship |
| `POST` | `/api/data-graph/{project_id}/discover/{conn_id}` | Auto-discover metrics from DB index |
| `GET` | `/api/insights/{project_id}` | List active insights |
| `GET` | `/api/insights/{project_id}/summary` | Insight summary (counts by type/severity) |
| `POST` | `/api/insights/{project_id}` | Create an insight record |
| `PATCH` | `/api/insights/{project_id}/{id}/confirm` | Confirm an insight |
| `PATCH` | `/api/insights/{project_id}/{id}/dismiss` | Dismiss an insight |
| `PATCH` | `/api/insights/{project_id}/{id}/resolve` | Mark an insight as resolved |
| `GET` | `/api/insights/{project_id}/actions` | Generate prioritized action recommendations from active insights |
| `POST` | `/api/feed/{project_id}/scan/{conn_id}` | Trigger autonomous insight scan for a connection |
| `POST` | `/api/feed/{project_id}/scan` | Trigger full-project insight scan |
| `POST` | `/api/feed/{project_id}/opportunities/{conn_id}` | Scan for growth opportunities |
| `POST` | `/api/feed/{project_id}/losses/{conn_id}` | Scan for revenue leaks and conversion drops |
| `POST` | `/api/reconciliation/{project_id}/row-counts` | Compare row counts between two sources |
| `POST` | `/api/reconciliation/{project_id}/values` | Compare aggregate metric values between two sources |
| `POST` | `/api/reconciliation/{project_id}/schemas` | Compare table schemas between two sources |
| `POST` | `/api/reconciliation/{project_id}/full` | Full reconciliation (counts + values + schemas) |
| `POST` | `/api/semantic-layer/{project_id}/build/{conn_id}` | Build semantic catalog from DB index |
| `POST` | `/api/semantic-layer/{project_id}/normalize` | Normalize metrics across all connections |
| `GET` | `/api/semantic-layer/{project_id}/catalog` | Browse the metric catalog |
| `POST` | `/api/explore/{project_id}` | Autonomous investigation — "What's wrong?" |
| `POST` | `/api/temporal/{project_id}/analyze` | Time series analysis (trend, seasonality, anomalies) |
| `POST` | `/api/temporal/{project_id}/lag` | Detect lag/lead between two time series |

### Security Model

| Concern | Implementation |
|---|---|
| **Authentication** | JWT tokens (HS256), 24h expiry with automatic proactive refresh, bcrypt password hashing. Google OAuth via GIS ID token verification. Password change and account deletion endpoints. All routes require auth (except `/auth/*` and `/health`). |
| **Authorization** | Role-based access control per project: owner, editor, viewer. Membership checked via `MembershipService.require_role()`. See permission matrix below. |
| **Project sharing** | Email-based invite system. Invites auto-accept on registration. Session isolation per user. |
| **Encryption at rest** | Fernet (AES-128-CBC + HMAC-SHA256) for SSH keys, passwords, connection strings |
| **Query safety** | SafetyGuard blocks DML/DDL in read-only mode, dialect-aware parsing. Applied to all execution paths: agent queries, note execution, scheduled queries, and MCP raw queries. |
| **Rate limiting** | slowapi: 5/min register, 10/min login, 20/min chat, 10/min note execute, 5/min change-password, 3/min delete-account, 10/min create-session, 10/min accept-invite, 5/min resend-invite |
| **MCP authentication** | API key or JWT required for all MCP tool calls. Anonymous access is rejected when no credentials are provided. |
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
| Manage invites (create, revoke, resend), remove members | Yes | No | No |
| Trigger backup, view backups | Yes | No | No |
| Create/edit connections | Yes | No | No |
| Trigger DB indexing, repo indexing, code-DB sync | Yes | No | No |
| Manage schedules (create, edit, delete, run) | Yes | No | No |
| Manage insights (create, confirm, dismiss, resolve) | Yes | No | No |
| Build/normalize semantic layer | Yes | No | No |
| Trigger feed scan | Yes | No | No |
| Manage data graph (metrics, relationships, discover) | Yes | No | No |
| Manage repositories (add, edit) | Yes | No | No |
| Create/edit custom rules (Knowledge) | Yes | Yes | No |
| Edit/toggle learnings, recompile (Learn) | Yes | Yes | No |
| Create/edit/delete dashboards | Yes | Yes | No |
| View dashboards | Yes | Yes | Yes |
| View analytics & usage stats | Yes | No | No |
| Create chat sessions, send messages | Yes | Yes | Yes |
| Save/delete own notes | Yes | Yes | Yes |
| Train agent (create learnings via feedback) | Yes | Yes | Yes |
| View all project data | Yes | Yes | Yes |
| Delete own SSH keys | Own keys only | Own keys only | Own keys only |

The frontend enforces this via the `usePermission()` hook which reads the active project's `userRole` from the app store. Infrastructure and management buttons are hidden for non-owner users. The `canEdit` flag (owner + editor) gates custom rules and learnings editing. The `canManageProject` flag (owner only) gates connections, indexing, sync, schedules, insights, and other project infrastructure.

#### Project Creation Eligibility

On the hosted version, project creation is restricted to users with `can_create_projects = true` in the database. By default, all new users have this flag set to `false`. Admins (`sergeysheleg4@gmail.com`, `sergey@appvillis.com`) are seeded with `can_create_projects = true` via an Alembic migration.

Non-eligible users who attempt to create a project see a **Request Access** modal with a form (email, description, message). Submitting the form sends an email to `contact@checkmydata.yay` via the `POST /api/projects/access-requests` endpoint. The backend enforces this with a 403 check in `create_project`.

Non-eligible users can still:
- Join existing projects via invite
- Use the demo project
- Use the self-hosted version where they control the database and can set the flag themselves

### Database Schema (Internal)

The agent uses SQLite (default) or PostgreSQL (recommended for production) to store its own data:

```
users            — id, email, password_hash (nullable for Google users), display_name, is_active, auth_provider (email|google), google_id, picture_url, can_create_projects (default false), created_at
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
saved_notes      — id, project_id (FK→projects CASCADE), user_id (FK→users CASCADE), connection_id (FK→connections SET NULL), title, comment, sql_query, last_result_json, is_shared, shared_by, last_executed_at, created_at, updated_at  [INDEX(project_id), INDEX(user_id)]
dashboards       — id, project_id (FK→projects CASCADE), creator_id (FK→users CASCADE), title, layout_json, cards_json, is_shared, created_at, updated_at  [INDEX(project_id), INDEX(creator_id)]
session_notes    — id, connection_id (FK→connections CASCADE), project_id, category (data_observation|column_mapping|business_logic|calculation_note|user_preference|verified_benchmark), subject, note, note_hash, confidence, is_verified, source_session_id, created_at, updated_at  [UNIQUE(connection_id, note_hash), INDEX(connection_id, category)]
data_validation_feedback — id, connection_id, session_id, message_id, query, metric_description, agent_value, user_expected_value, deviation_pct, verdict (confirmed|rejected|approximate|unknown), rejection_reason, resolution, resolved, created_at  [INDEX(connection_id), INDEX(message_id)]
data_benchmarks  — id, connection_id (FK→connections CASCADE), metric_key, metric_description, value, value_numeric, unit, confidence, source (agent_derived|user_confirmed|cross_validated), times_confirmed, last_confirmed_at, created_at  [UNIQUE(connection_id, metric_key)]
data_investigations — id, validation_feedback_id (FK→data_validation_feedback), connection_id, session_id, trigger_message_id, status (active|completed|failed|cancelled), phase, user_complaint_type, user_complaint_detail, user_expected_value, problematic_column, investigation_log_json, original_query, original_result_summary, corrected_query, corrected_result_json, root_cause, root_cause_category, learnings_created_json, notes_created_json, benchmarks_updated_json, created_at, completed_at
code_db_sync     — ... + required_filters_json, column_value_mappings_json (new columns)
backup_records      — id, created_at, reason (scheduled|initial_sync|manual), status (success|failed), size_bytes, manifest_json, backup_path, error_message
scheduled_queries   — id, user_id (FK→users), project_id (FK→projects), connection_id (FK→connections), title, sql_query, cron_expression, alert_conditions (JSON), notification_channels (JSON), is_active, last_run_at, last_result_json, next_run_at, created_at, updated_at
schedule_runs       — id, schedule_id (FK→scheduled_queries), status (success|failed|alert_triggered), result_summary, alerts_fired (JSON), executed_at, duration_ms
notifications       — id, user_id (FK→users), project_id (FK→projects), title, body, type (alert|info|system), is_read, created_at
```

Managed via **Alembic migrations** (36 revisions: initial → custom_rules → users → branch_and_rag_feedback → project_cache_and_rag_commit_sha → user_rating → project_members_invites_ownership → google_oauth_fields → tool_calls_json → ssh_exec_mode → indexing_checkpoint → cascade_delete_project_fks → add_user_id_to_ssh_keys → per_purpose_llm_models → add_connection_id_to_chat_sessions → add_default_rule_fields → add_db_index_tables → add_indexing_status_to_summary → add_code_db_sync_tables → add_column_distinct_values → add_agent_learning_tables → ... → hardening_indexes_fk_constraints → add_saved_notes_table → ... → add_self_improvement_tables → add_picture_url_to_users → add_backup_records_table → add_overview_to_project_cache).

All child tables referencing `projects.id` use `ON DELETE CASCADE` so deleting a project automatically removes all related rows (connections, chat sessions, knowledge docs, commit indices, project cache, RAG feedback, members, invites, indexing checkpoints, saved notes, scheduled queries, notifications).

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
| `RESEND_API_KEY` | No | [Resend](https://resend.com) API key for transactional emails (welcome, invite, acceptance). If empty, emails are silently skipped. |
| `RESEND_FROM_EMAIL` | No | Sender address for transactional emails (default: `CheckMyData <noreply@checkmydata.ai>`). Must match a [verified domain](https://resend.com/domains) in Resend. |
| `APP_URL` | No | Frontend URL used in email links (default: `http://localhost:3000`). Set to your production URL in prod. |
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

## UX & Accessibility Improvements

Twenty targeted UX/visual quality improvements applied across the frontend:

1. **Toast dismiss button** — added `aria-label`, increased touch target, `role="alert"` on toasts
2. **WrongDataModal close** — added `aria-label`, hover background, min click target
3. **DashboardBuilder picker close** — added `aria-label`, transition, min click target
4. **BatchRunner note picker close** — added `aria-label`, hover feedback, min click target
5. **Dashboard back button** — added `aria-label="Back to home"`, min 36px touch target
6. **Spinner** — added `role="status"`, `aria-live="polite"`, screen-reader text
7. **SuggestionChips** — `aria-hidden="true"` on decorative lightbulb SVG
8. **ActionButton sizes** — increased xs/sm/md minimum dimensions for better touch targets
9. **ConfirmModal** — added `role="dialog"`, `aria-modal`, `aria-labelledby`, fade-in animation
10. **ToastContainer** — elevated z-index to `z-[60]` (above modals), `aria-live` region
11. **ConnectionSelector** — added saving/loading state with spinner on Create/Save button
12. **AuthGate email** — inline validation on blur with red border and error message
13. **LlmModelSelector** — shows error state when model list fails to load
14. **ChatInput** — 4000-char limit with remaining count near limit, `maxLength` enforced
15. **Viewport** — changed `userScalable: true`, `maximumScale: 5` for accessibility (pinch-to-zoom)
16. **NoteCard buttons** — added `aria-label` to share/delete icon buttons, increased touch targets
17. **ErrorBoundary** — added focus ring, `autoFocus` on reload button, rounded-lg styling
18. **DataTable exports** — added `aria-label` and `title` tooltips on CSV/JSON/XLSX buttons
19. **ChatSearch** — added "Type at least 2 characters" hint for short queries
20. **Toast animation** — slide-in animation preserved, z-index layering fixed

---

## Testing

### Automated Tests

```bash
make check            # backend lint + all tests
make test-frontend    # frontend vitest
```

**Test counts:**
- Backend unit tests: 1,952 across 128 test files
- Backend integration tests: 411 across 47 test files
- Frontend tests: 345 across 39 test files
- **Grand total: 3,005 tests**
- Backend coverage: 72%+ (72.00% unit-only; enforced CI minimum: 72%)
- Zero flaky tests, zero skipped tests
- Performance smoke tests: 9 (latency budgets for health, auth, CRUD, list endpoints)

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
| Auth Service | 28 (register, login, JWT, Google OAuth, password hash, duplicate email, token decode) | — |
| Chat Service | 18 (session CRUD, message CRUD, history enrichment, user isolation, metadata parsing) | — |
| Project Service | 15 (CRUD, list ordering, update, delete, None-value handling) | — |
| Scheduler Service | 25 (cron validation, schedule CRUD, due schedules, record run, run history) | — |
| Note Service | 18 (CRUD, scope filtering: mine/shared/all, update allowed fields, result update) | — |
| Query Planner | 25 (complexity detection, adaptive LLM fallback, plan validation, cycle detection) | — |
| Agent Validation | 20 (SQL/viz/knowledge result validation, warnings, error states) | — |
| Stage Executor | 20 (execute, retry, dispatch, checkpoint, error handling, question builder) | — |
| Feedback Pipeline | 30 (confirmed/approximate/rejected verdicts, learning derivation, _try_float) | — |
| Query Cache | 18 (LRU, TTL, invalidation, schema-aware keys, eviction) | — |
| API Dependencies | 9 (auth header parsing, JWT validation, user lookup, inactive user) | — |
| Alembic | 2 (upgrade head, downgrade base) | — |
| API Routes | 23 (projects, connections, viz routes, active tasks, stale index/sync status reset, pipeline failure propagation, sync background failure propagation, startup stale reset) | — |
| Route coverage (backup, demo, metrics, health monitor, notifications, dashboards RBAC) | — | 8 |
| Models Routes | 11 (sorting, cache, static providers, error fallback) | — |
| Connection Service | 25 (create, encrypt, sanitize, get, list, update, delete, test_connection, to_config: basic/SSH/MCP) | — |
| Dashboard Service | 10 (create, get, list_for_project OR filter, update allowed/ignored/missing, delete, ALLOWED_UPDATE_FIELDS) | — |
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
| Security: Safety Guard | 41 (SQL injection patterns, CTE bypass, multi-statement, all dialects, MongoDB writes) | — |
| Security: RBAC | — | 31 (endpoint role matrix, JWT edge cases, encryption, unauthenticated access) |
| LLM Resilience | 18 (fallback chain, retry, auth/token errors, health marking) | — |
| Connection Lifecycle | 22 (registry, encryption round-trip, config, connector key) | — |
| Pipeline Resilience | 19 (binary filtering, checkpoint, pipeline registry, error handling) | — |
| History Trimmer | 15 (token estimation, condensing, trim with/without LLM, fallback summary) | — |
| Benchmark Service | — | 12 (normalize key, CRUD, confidence, staleness) |
| Usage Service | — | 6 (record, period comparison) |
| Batch Service | — | 6 (CRUD, list, delete) |
| Data Sanity Checker | 5 (healthy, duplicates, negatives, nulls) | — |
| Business Logic | — | 11 (schedules, notifications, notes, dashboards) |
| Schedule & Notes Routes | — | 21 (schedules CRUD, run-now, history, notes CRUD, execute, auth guards) |
| API Coverage | — | 12 (chat sessions, data validation, batch, usage, models, tasks, legal) |
| Auth Extended | — | 18 (change-password, refresh, me, onboarding, delete-account, registration validation) |
| Performance Smoke | — | 9 (health latency, auth latency, CRUD latency, list endpoints) |
| Dashboard Service | 10 (CRUD, allowed fields, visibility) | 8 (routes CRUD, RBAC, private visibility) |
| Probe Service | 8 (run probes, null rates, findings, errors) | — |
| Backup Routes | — | 4 (trigger, list, history, auth) |
| Demo Routes | — | 2 (setup, auth) |
| Metrics Route | — | 2 (shape, auth) |
| Health Monitor | — | 2 (connection health, reconnect) |
| Notification Routes | — | 3 (list/count, read-all, mark-read 404) |
| LLM Adapters | 24 (OpenAI/Anthropic/OpenRouter classifiers, complete, format) | — |
| MCP Client | 18 (connect, disconnect, test, list, query, call_tool) | — |
| Connectors (PG/MySQL/Mongo/CH) | 49 (execute, test, disconnect, params, errors) | — |
| Batch Routes | 7 (sheet name sanitization) | 9 (execute, CRUD, export, auth, cross-project) |
| Edge Cases | 10 (alert evaluator: null/zero/unknown/negative/string) | 12 (demo idempotency, dashboard privacy, notification edges) |
| Frontend (ErrorBoundary) | 3 (render ok, error UI, reload button) | — |
| Frontend (StatusDot) | 9 (all statuses, sizes, pulse) | — |
| Frontend (ToastContainer) | 5 (empty, success, error, multiple, dismiss) | — |
| Frontend (Spinner) | 3 (render, className, styles) | — |
| Frontend (VizRenderer) | 7 (table, chart, text, number, key_value, unknown, default) | — |
| Frontend (SuggestionChips) | 8 (loading, render, truncate, onSelect, empty, followups) | — |
| Frontend (NotificationBell) | 5 (bell, badge, dropdown, notifications) | — |
| Frontend (DashboardList) | 5 (loading, empty, list, new button) | — |
| Frontend (AccountMenu) | 5 (gear, menu, change password, google-only, sign out) | — |
| Frontend (api) | 4 (fetch mock, auth headers) | — |
| Frontend (auth-store) | 4 (login, error, logout, restore) | — |
| Frontend (app-store) | 10 (setActiveProject, addMessage, localStorage persistence, updateMessageId, userRating, rawResult) | — |
| Frontend (task-store) | 13 (processEvent lifecycle, pipeline filtering, step updates with/without pipeline field, completed/failed, auto-dismiss timers, seedFromApi merge, manual dismiss, untracked pipeline_end ignored) | — |
| Frontend (ProjectSelector) | 8 (render, new button, list items, click selects project, edit form, delete button, create form, empty state) | — |
| Frontend (ConnectionSelector) | 10 (render, create button, list items, DB type badge, test button, index button, sync button, delete button, form fields, DB type switch) | — |
| Frontend (ChatPanel) | 9 (render, empty state, user/assistant messages, loading indicator, error display, scroll-to-bottom, input area, thinking log bouncing dots) | — |
| Frontend (ChatMessage) | 10 (user/assistant content, feedback buttons, no feedback for user, SQL query block, visualization, error+retry, markdown, mobile viz collapse, mobile width) | — |
| Note Service | 10 (create, get, list_by_project, update, delete, update_result, filtering, ordering) | — |
| Notes API | — | 12 (create, list, get, update, delete, execute, connection validation, membership checks, audit logging, auth) |
| SQLAgent | 20 (name, no config raises, text response, execute_query success/failure, get_schema_info overview/detail, custom rules, db_index, sync_context, query_context, learnings get/record, unknown tool, exception, max iterations, token usage, tool_call_log, learning extraction) | — |
| DataSanityChecker | 9 (all null, all zero, future dates, percentage sums, benchmark deviations, format warnings, negative values, duplicate keys, single-row anomaly, date range mismatch) | — |
| InsightGenerator | 4 (trend detection, outlier detection, concentration detection, totals summary) | — |
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
| Frontend (ChatInput) | 7 (render, typing, submit, empty guard, disabled, placeholder, touch target) | — |
| Frontend (RulesManager) | 8 (new button, empty state, rule items, edit/delete buttons, create form, cancel edit) | — |
| Frontend (SshKeyManager) | 6 (add button, empty state, key items, delete button, create form, submit) | — |
| Frontend (ReadinessGate) | 8 (status dashboard, bypass button, callback, warning, auto-bypass when ready, green indicators, staleness warning, last indexed time) | — |
| Frontend (Sidebar) | 8 (render, nav sections, collapse, workspace sections, sign out, mobile drawer render, mobile drawer hidden, mobile close) | — |
| Frontend (InviteManager) | 6 (render, email+role inputs, invite button, members list, remove button except owner, pending invites) | — |
| Frontend (NotificationBell) | 5 (bell icon, badge when unread, no badge at zero, dropdown opens and lists, notification rows) | — |
| Frontend (DashboardList) | 4 (loading then list, empty state, dashboard titles, New Dashboard opens builder) | — |
| Frontend (AccountMenu) | 5 (gear button, menu open, Change Password for email vs Google-only, Sign Out calls logout) | — |
| Context Budget Manager | 23 (_estimate, BudgetAllocation, allocate, _truncate, budget limits, empty texts) | — |
| VectorStore | 21 (init client types, collection CRUD, add_documents, query, delete_by_source_path, delete_collection, embedding function) | — |
| GitTracker | 16 (ChangedFilesResult, get_head_sha, get_changed_files diff/full/fallback, get_last_indexed_sha, record_index, count_commits_ahead, cleanup_old_records) | — |
| BackupManager Extended | 21 (run_backup manifest/errors, _backup_database types, _backup_chroma skip/copy, _backup_rules, prune retention/failure, list_backups valid/corrupt/incomplete, pg_dump failure) | — |
| Connectors Extended | 49 (Postgres execute/params/disconnect/test, MySQL execute/params/test, MongoDB find/count/aggregate/invalid/test, ClickHouse execute/params/test, _dict_to_positional) | — |
| InvestigationAgent | 39 (run loop, tool dispatch, record finding, diagnostic query, compare results, column formats, learnings, error handling) | — |
| Batch Service | 12 (create, get, list, delete, note_ids loading, queries_json, note_ids_json) | — |
| Checkpoint Service | 33 (get_active, create, complete_step, mark_doc_processed, mark_docs_batch_processed, mark_failed, delete, cleanup_stale, static methods) | — |
| Usage Service | 13 (record_usage, get_period_comparison, aggregate_period, daily_breakdown, change_percent) | — |
| Auth Extended Routes | — | 18 (change-password, refresh, me, complete-onboarding, delete-account, registration validation) |
| Schedule & Notes Routes | — | 22 (schedules CRUD, invalid cron, run-now, history, notes CRUD, execute, auth guards) |
| Frontend (toast-store) | 12 (addToast, removeToast, auto-remove by type, unique ids, helper function) | — |
| Frontend (ConfirmModal) | 17 (store show/close, options, previous dialog resolution, component rendering, Cancel/Confirm, severity icons, confirmText typing, destructive styling) | — |
| Frontend (DataTable) | 9 (column headers, row data, row count, execution time, NULL display, export buttons, empty/missing data) | — |
| Frontend (OnboardingWizard) | 10 (step rendering, DB types, form inputs, SSH tunnel, skip/demo buttons, step indicators) | — |
| Frontend (BatchRunner) | 11 (header, title input, connection selector, add query, run all count, close, pre-select connection) | — |
| Frontend (ScheduleManager) | 8 (schedule list, cron labels, form, cancel, create disabled, preset/custom, alert conditions, status dots) | — |

---

## Mobile-Responsive Layout and PWA Support

The frontend is fully responsive and supports installation as a Progressive Web App (PWA).

### Responsive Layout

- **Desktop (>= 768px):** Sidebar + main content side-by-side, notes panel on the right
- **Mobile (< 768px):** Full-width content with a hamburger-triggered slide-over drawer for the sidebar
- The `useMobileLayout()` hook (in `frontend/src/hooks/useMobileLayout.ts`) uses `matchMedia` to detect viewport width
- Mobile header bar with hamburger menu, app title, and notification bell is visible only on small screens

### Mobile Sidebar Drawer

- On mobile, `Sidebar` accepts `isMobile`, `isOpen`, and `onClose` props
- Renders as a fixed overlay with a semi-transparent backdrop and slide-in animation from the left (`translate-x` transition)
- Close button (X) in the drawer header; tap backdrop to dismiss
- Focus is trapped inside the drawer when open for accessibility; Escape key closes it

### Touch Optimizations

- All interactive elements meet the 44px minimum touch target on touch devices (`@media (pointer: coarse)`)
- Chat input uses `text-base` (16px) on mobile to prevent iOS auto-zoom
- Send button has 44x44px minimum size on mobile
- Chat messages use wider max-width (95%) on mobile for better readability
- Metadata badges with lower priority (viz type, token counts, cost) are hidden on mobile to reduce density
- Visualizations collapse by default on mobile with a "Tap to view chart" button
- Tables inside chat messages have horizontal scroll on mobile (`overflow-x-auto`)

### PWA Configuration

The app includes a Web App Manifest at `frontend/public/manifest.json`:
- **Name:** CheckMyData.ai
- **Display:** standalone (no browser chrome)
- **Theme color:** #3b82f6 (blue accent)
- **Background:** #09090b (matches surface-0)

The root layout (`layout.tsx`) includes the manifest link, theme-color meta, and apple-mobile-web-app-capable meta tags.

**Note:** PWA icons (`/icon-192.png` and `/icon-512.png`) are referenced but not yet included. Replace with actual icons before production deployment.

### Key Files

| File | Purpose |
|---|---|
| `frontend/src/hooks/useMobileLayout.ts` | Viewport-width detection hook |
| `frontend/src/app/page.tsx` | Responsive layout with mobile header and sidebar state |
| `frontend/src/components/Sidebar.tsx` | Accepts `isMobile`/`isOpen`/`onClose` for drawer mode |
| `frontend/src/components/chat/ChatInput.tsx` | Touch-optimized input with sticky positioning |
| `frontend/src/components/chat/ChatMessage.tsx` | Mobile-responsive messages with collapsible viz |
| `frontend/public/manifest.json` | PWA manifest |
| `frontend/src/app/layout.tsx` | Manifest link + PWA meta tags |
| `frontend/src/app/globals.css` | Touch target rules + mobile scroll fixes |

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

**Manual deploy script:**

When CI/CD is unavailable (e.g. GitHub Actions billing limits), use the deploy script:

```bash
# Deploy both backend and frontend
./scripts/deploy-heroku.sh

# Deploy only backend
./scripts/deploy-heroku.sh --backend-only

# Deploy only frontend
./scripts/deploy-heroku.sh --frontend-only
```

The script builds Docker images for `linux/amd64`, pushes to Heroku Container Registry, releases both apps, and runs health checks. Requires `heroku login` or `HEROKU_API_KEY` env var.

<details>
<summary>Manual Docker commands (without the script)</summary>

```bash
heroku container:login
docker build --platform linux/amd64 -t registry.heroku.com/checkmydata-api/web -f Dockerfile.backend .
docker build --platform linux/amd64 -t registry.heroku.com/checkmydata-web/web \
  --build-arg NEXT_PUBLIC_API_URL=https://api.checkmydata.ai/api \
  --build-arg NEXT_PUBLIC_WS_URL=wss://api.checkmydata.ai/api/chat/ws \
  -f Dockerfile.frontend .
docker push registry.heroku.com/checkmydata-api/web
docker push registry.heroku.com/checkmydata-web/web
heroku container:release web --app checkmydata-api
heroku container:release web --app checkmydata-web
```

</details>

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
  RESEND_API_KEY=re_... \
  APP_URL=https://checkmydata.ai \
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

See [CHANGELOG.md](CHANGELOG.md) for full release history.

---

## Contributing

We welcome contributions! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for
guidelines on:

- Setting up the development environment
- Branch naming and commit conventions
- Pull request process
- Testing expectations

## License

This project is licensed under the [MIT License](LICENSE).
