# eSIM Database Agent

AI-powered database query agent that analyzes Git repositories, understands database schemas, and lets you query databases through natural language chat with rich data visualization.

---

## How It Works — The Big Picture

```
┌───────────────────────────────────────────────────────────────────────┐
│                        User  (Browser)                               │
│  ┌─────────┐  ┌──────────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  Auth    │  │  Sidebar     │  │  Chat    │  │  Visualization   │  │
│  │  Gate    │  │  (Projects,  │  │  Panel   │  │  (Table/Chart/   │  │
│  │         │  │  Connections, │  │          │  │   Export)        │  │
│  │         │  │  SSH Keys,   │  │          │  │                  │  │
│  │         │  │  Rules, Docs)│  │          │  │                  │  │
│  └────┬────┘  └──────┬───────┘  └────┬─────┘  └────────┬─────────┘  │
│       │              │               │                  │            │
└───────┼──────────────┼───────────────┼──────────────────┼────────────┘
        │              │               │                  │
        ▼              ▼               ▼                  ▼
┌───────────────────────────────────────────────────────────────────────┐
│                    FastAPI  Backend  (Python)                         │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  API Layer  (/api/...)                                        │   │
│  │  auth · projects · connections · ssh-keys · chat              │   │
│  │  repos · rules · visualizations · workflows · health          │   │
│  └──────────────────────────┬─────────────────────────────────────┘   │
│                             │                                         │
│  ┌──────────────────────────▼─────────────────────────────────────┐   │
│  │  Core Orchestrator                                             │   │
│  │  1. Introspect schema (cached 5min)                           │   │
│  │  2. Load rules (file + DB)                                    │   │
│  │  3. RAG: vector search for relevant code docs                 │   │
│  │  4. Build SQL/query via LLM (dialect-aware prompts)           │   │
│  │  5. Safety guard (block DML in read-only mode)                │   │
│  │  6. Execute query on target database                          │   │
│  │  7. Interpret results via LLM                                 │   │
│  │  8. Recommend visualization format                            │   │
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
2. **Chat flow**: Ask a question in natural language -> the **ConversationalAgent** decides whether to chat, search knowledge, or query the database -> results returned with visualization. Uses SSE streaming for real-time progress updates. Chat history is token-budget-managed and older messages are summarized to stay within limits.
3. **Knowledge flow**: Git repo is analyzed via a multi-pass pipeline (project profiling -> entity extraction -> cross-file analysis -> enriched LLM doc generation) -> chunks stored in ChromaDB for RAG retrieval
4. **Sharing flow**: Project owner invites collaborators by email -> invited users register and are auto-accepted -> each user gets isolated chat sessions while sharing the same project data and connections

---

## User Guide — Step by Step

### 1. Installation & First Launch

```bash
# Clone and setup everything in one command
make setup       # creates venv, installs Python & Node deps, generates .env & encryption key, runs DB migrations

# Start both backend and frontend
make dev         # backend on :8000, frontend on :3000
```

Open `http://localhost:3000` in your browser.

### 2. Register / Login

When you first open the app, you see the **AuthGate** — a login/registration form.

- Enter email + password + display name to **create an account**
- Or click **"Sign in with Google"** to authenticate via your Google account (no password needed)
- JWT token is stored in `localStorage`, so you stay logged in across page refreshes
- Your email appears in the top-right header; click **Sign Out** to log out

**Google OAuth**: If you register with email/password first and later sign in with Google using the same email, your accounts are automatically linked.

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
2. Enter a **name** (e.g. "eSIM Analytics")
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
SSH Host: 64.188.10.62      SSH User: deploy       SSH Key: "prod-key"
DB Host: 127.0.0.1          DB Port: 3306          DB Name: analytics
DB User: readonly_agent     DB Password: ****
```
The agent will SSH into `64.188.10.62`, then connect to MySQL at `127.0.0.1:3306` through the tunnel.

**Example — MySQL via SSH exec mode (CLI on server):**
```
SSH Host: 64.188.10.62      SSH User: ssheleg-ai-agent    SSH Key: "server-key"
DB Host: 127.0.0.1          DB Port: 3306                 DB Name: esim_analytics
DB User: ssheleg_ai_agent_read    DB Password: ****
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
   - **LLM Validation** — an LLM analyzes each table: determines if it's active, rates relevance (1-5), writes a business description, identifies data patterns, and checks alignment with code
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

7. **Chat Readiness Gate**: When you open the chat for the first time, a readiness checklist shows which setup steps are complete and which are missing. If sync is not done, you can still chat (with reduced accuracy) or run sync inline from the checklist.

**What the sync discovers (examples):**
- `orders.amount` — "Stored in cents (integer). Divide by 100 for dollar values."
- `users.created_at` — "UTC timestamp, ISO 8601 format."
- `subscriptions.status` — "Enum: active | paused | cancelled | expired."
- `payments.deleted_at` — "Soft-delete pattern. Filter `WHERE deleted_at IS NULL` for active records."

### 8. Agent Learning Memory (ALM)

The agent automatically **learns from query outcomes** and accumulates per-connection knowledge that improves future queries. No manual setup required — learning happens transparently.

**How it works:**
- After every query that requires a retry (validation loop fires), the system analyzes what went wrong and what fixed it
- Lessons are extracted using zero-cost heuristic extractors (no LLM calls)
- Each lesson is stored per-connection with a confidence score that grows with confirmations
- On the next query, accumulated learnings are injected into the system prompt and query context

**What it learns automatically:**
| Category | Example | Trigger |
|---|---|---|
| Table Preference | "Use `orders_v2` not `orders_legacy` for revenue" | Agent tries table A (fails), succeeds with table B |
| Column Usage | "`amount_total` doesn't exist; use `total_amount`" | `column_not_found` error repaired |
| Data Format | "`amount` stored in cents, divide by 100" | Repair added `/ 100` division |
| Query Pattern | "Always JOIN `currencies` when querying revenue" | Repeated repair pattern |
| Schema Gotcha | "`deleted_at IS NULL` required for active records" | Soft-delete filter added in repair |
| Performance Hint | "`events` table: always filter by date range" | Timeout resolved by adding filter |

**Confidence system:**
- New heuristic lessons start at 60% confidence
- Agent-recorded lessons start at 80%
- Each confirmation adds +10% (capped at 100%)
- Contradictions reduce by −30%
- Only lessons with ≥50% confidence appear in the system prompt

**Managing learnings:**
- A blue **LEARN** badge with count appears on connections that have accumulated learnings
- Click the badge to open the **LearningsPanel** — view, edit, deactivate, or delete individual lessons
- Use **Clear all** to reset the learning memory for a connection
- The agent also has `get_agent_learnings` and `record_learning` tools — it can manually record discoveries during conversations

**User feedback integration:**
- When you give a **thumbs down** on an assistant message, the system triggers a learning analysis on the failed interaction

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

### 10. Activity Log (Bottom Panel)

A real-time **Activity Log** panel is available at the bottom of the screen:

1. Click the **"Activity Log"** button in the bottom-right corner to open it
2. The panel shows a live stream of ALL backend events across all pipelines:
   - **Indexing** (purple) — SSH key, git clone/pull, file analysis, doc generation, vector storage
   - **Query** (cyan) — schema introspection, SQL generation, execution, validation, repair
   - **Agent** (amber) — LLM calls, tool execution, knowledge search
3. Each log line shows: timestamp, pipeline, step name, status, detail, and elapsed time
4. The panel auto-scrolls to the latest entry. A badge shows unread count when closed.
5. Use **Clear** to reset the log, **Close** to hide the panel.

The log connects via SSE to `GET /api/workflows/events` (global mode, no workflow filter).

### 11. Chat — Ask Questions

With a project selected (and optionally a connection):

1. Open a chat session (or create one via the session list in the sidebar)
2. Type your question in natural language. The **ConversationalAgent** handles different types of interactions:

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

3. The agent decides which tools to call based on the question:

```
Your question
    ↓
[ConversationalAgent] — LLM with tools decides what to do
    ↓
├── Data question → calls get_db_index, get_schema_info, get_custom_rules, execute_query
│   ↓
│   [Validation Loop] — Pre-validate → Safety check → EXPLAIN → Execute
│   ↓  (if error: Classify → Enrich → Repair → retry, up to 3 attempts)
│   [Interpret results] → Table / Chart / Text + Export
│
├── Knowledge question → calls search_knowledge, get_entity_info
│   ↓
│   Returns answer with source citations
│
├── Rule management → calls manage_custom_rules
│   ↓
│   Creates/updates/deletes a project rule, sidebar refreshes
│
└── Conversation → responds directly (no tool calls)
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
   - A **table or chart** with the data, plus a **Visual / Text toggle** to switch between the rendered visualization and the plain-text answer
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

### 12. Custom Rules

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

### 13. Editing & Managing

- **Edit project**: Hover over a project and click the ✎ icon — change name, repo, LLM config
- **Edit connection**: Hover over a connection and click the ✎ icon — update host, credentials
- **Delete**: Click the × icon (projects, connections, SSH keys, rules, chat sessions)
- **SSH key protection**: Deleting a key that is used by a project or connection returns a 409 error

### 14. Sharing a Project (Email Invite System)

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

---

## Architecture Deep Dive

### Backend Layers

```
app/
├── api/routes/         ← HTTP endpoints (FastAPI routers)
├── core/               ← Business logic
│   ├── agent.py        ← ConversationalAgent: multi-tool loop (replaces rigid orchestrator for chat)
│   ├── tools.py        ← Tool definitions (execute_query, search_knowledge, get_schema_info, get_custom_rules, manage_custom_rules, get_db_index, get_entity_info, get_agent_learnings, record_learning)
│   ├── tool_executor.py← Executes tool calls, wraps ValidationLoop / VectorStore / SchemaIndexer / ProjectKnowledge
│   ├── prompt_builder.py← Dynamic system prompt builder (role-aware, capability-aware)
│   ├── orchestrator.py ← Original SQL pipeline (preserved, used by tool_executor)
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
│   ├── history_trimmer.py ← Token-budget-aware chat history summarization (handles tool messages)
│   ├── query_cache.py ← LRU result cache (connection_key + query_hash)
│   ├── retry.py        ← Async retry decorator with backoff
│   ├── rate_limit.py   ← slowapi rate limiting config
│   └── logging_config.py ← Structured logging setup
├── connectors/         ← Database adapters
│   ├── base.py         ← Abstract interface (ConnectionConfig, QueryResult, SchemaInfo)
│   ├── registry.py     ← Connector factory (routes to SSHExecConnector when exec_mode=True)
│   ├── postgres.py     ← asyncpg + SSH tunnel via asyncssh
│   ├── mysql.py        ← aiomysql + SSH tunnel
│   ├── mongodb.py      ← motor (async MongoDB driver)
│   ├── clickhouse.py   ← clickhouse-connect (sync, wrapped in asyncio.to_thread)
│   ├── ssh_exec.py     ← SSH exec mode: run queries via CLI on remote server
│   ├── ssh_tunnel.py   ← SSH tunnel (port forwarding) with keepalive + timeout
│   ├── cli_output_parser.py ← Parse MySQL/psql/ClickHouse CLI tabular output
│   └── exec_templates.py    ← Predefined CLI command templates per db_type
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
│   └── learning_analyzer.py  ← Heuristic lesson extractors (table switch, column fix, format, performance)
├── llm/                ← LLM provider abstraction
│   ├── base.py         ← Message, LLMResponse, ToolCall types
│   ├── router.py       ← Provider chain with fallback + retry
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   └── openrouter_provider.py
├── models/             ← SQLAlchemy models (internal DB)
│   ├── project.py, connection.py, ssh_key.py
│   ├── chat_session.py, chat_message.py
│   ├── custom_rule.py, user.py
│   ├── project_member.py ← Role-based project membership (owner/editor/viewer)
│   ├── project_invite.py ← Email-based project invitations
│   ├── knowledge_doc.py, commit_index.py (branch-aware)
│   ├── project_cache.py ← Cached ProjectKnowledge + ProjectProfile per project
│   ├── agent_learning.py ← AgentLearning + AgentLearningSummary: per-connection experience-based lessons
│   ├── db_index.py     ← DbIndex + DbIndexSummary: per-table LLM analysis results
│   └── rag_feedback.py ← RAG chunk quality tracking (version-scoped)
├── services/           ← Business logic layer
│   ├── project_service.py, connection_service.py
│   ├── ssh_key_service.py, chat_service.py
│   ├── rule_service.py, default_rule_template.py, auth_service.py
│   ├── membership_service.py ← Role checking, member CRUD, accessible projects
│   ├── invite_service.py ← Create/accept/revoke invites, auto-accept on registration
│   ├── rag_feedback_service.py ← Record & query RAG effectiveness (version-scoped)
│   ├── project_cache_service.py ← Persist/load ProjectKnowledge + ProjectProfile between runs
│   ├── checkpoint_service.py ← CRUD for indexing checkpoints (resumable pipeline state)
│   ├── agent_learning_service.py ← CRUD, dedup, confidence management, prompt compilation for learnings
│   ├── db_index_service.py  ← CRUD + formatting for database index entries
│   └── encryption.py   ← Fernet encrypt/decrypt
└── viz/                ← Visualization & export
    ├── renderer.py     ← Auto-detect viz type (table/chart/text)
    ├── chart.py        ← Chart.js config generation (bar/line/pie)
    ├── table.py        ← Tabular data formatting
    └── export.py       ← CSV, JSON, XLSX export
```

### How the Conversational Agent Works

The `ConversationalAgent` (`backend/app/core/agent.py`) is the brain of the system.  It replaced the rigid "always-generate-SQL" pipeline with a **multi-tool agent loop** where the LLM decides which tools (if any) to call.

```
User Message
    ↓
[ConversationalAgent.run()]
    ↓
Build system prompt (role-aware, capability-aware)
    ↓
┌──────────── Tool Loop (max 5 iterations) ────────────┐
│                                                        │
│  Send messages + available tools to LLM                │
│    ↓                                                   │
│  LLM responds with:                                    │
│    • Tool call → execute tool → feed result back       │
│    • Text → final answer → exit loop                   │
│                                                        │
│  Available tools (conditional):                        │
│    • execute_query  (if DB connected)                  │
│    • get_schema_info (if DB connected)                 │
│    • get_custom_rules (if DB connected)                │
│    • manage_custom_rules (if DB connected)             │
│    • record_learning (if DB connected)                 │
│    • get_agent_learnings (if DB connected + learnings) │
│    • get_db_index   (if DB connected + indexed)        │
│    • search_knowledge (if knowledge base indexed)      │
│    • get_entity_info (if knowledge base indexed)       │
│                                                        │
└────────────────────────────────────────────────────────┘
    ↓
[If SQL results: interpret + recommend visualization]
    ↓
Return AgentResponse (text | sql_result | knowledge | error)
```

**Key architectural decisions:**
- **Tools are lazy**: Schema, RAG, and rules are only fetched when the LLM explicitly requests them, not on every message.
- **Conversation is natural**: The LLM can respond without calling any tool for greetings, follow-ups, and discussions about previous results.
- **Knowledge-only mode**: Users can chat without a database connection — only `search_knowledge` is available.
- **Response types**: Each response is tagged as `text`, `sql_result`, `knowledge`, or `error` — the frontend renders each type differently.
- **Backward compatible**: The original `Orchestrator` is preserved and used internally by the `ToolExecutor` for SQL execution.

### Multi-Tool Agent Architecture

```
backend/app/core/
├── agent.py           ← ConversationalAgent: main loop, tool iteration, response building
├── tools.py           ← Tool definitions (execute_query, search_knowledge, get_schema_info, get_custom_rules, manage_custom_rules, get_entity_info, get_agent_learnings, record_learning)
├── tool_executor.py   ← Executes tool calls, wraps existing ValidationLoop / VectorStore / SchemaIndexer / ProjectKnowledge
├── prompt_builder.py  ← Dynamic system prompt (capability-aware, dialect-aware)
├── orchestrator.py    ← Original pipeline (preserved, used by tool_executor for SQL)
└── ...
```

### How the Original Orchestrator Works (used by ToolExecutor)

The `Orchestrator` handles SQL query execution. When the agent calls `execute_query`:

1. **Schema context** — Live DB introspection + RAG search in ChromaDB
2. **Rules context** — Merge file-based + DB-based custom rules
3. **Build query** — LLM generates SQL using tool calling (dialect-aware prompts)
4. **Validation loop** — The query goes through a self-healing cycle (see below)
5. **Interpret results** — LLM explains results and picks viz type
6. Return `OrchestratorResponse` with answer, query, results, visualization, and attempt history

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

SSH connections include a 30-second connect timeout and 15-second keepalive interval. The `is_alive()` check uses a unique stdout marker (`__SSH_TUNNEL_ALIVE__`) instead of relying on exit codes, making it robust against shell profile noise on the remote server. The SSH test endpoint (`POST /connections/{id}/test-ssh`) also uses a stdout marker (`__SSH_TEST_OK__`) and returns the actual stdout on failure for debugging. If an SSH tunnel is recreated (new port), the MySQL and PostgreSQL connectors automatically detect the broken connection during schema introspection and reconnect with a single retry. If an SSH connection drops mid-query, the exec connector automatically attempts one reconnection before failing.

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
│   ├── auth-store.ts      ← Zustand: user, token, login/register/logout
│   ├── log-store.ts       ← Zustand: activity log entries, panel state, SSE connection status
│   └── toast-store.ts     ← Zustand: toast notifications (success/error/info, 4s auto-dismiss)
├── hooks/
│   ├── useGlobalEvents.ts ← Global SSE subscription hook (all workflow events → log store)
│   └── useRestoreState.ts ← Restore active project/connection/session from localStorage on mount
├── lib/
│   ├── api.ts             ← REST client (fetch wrapper + auth headers + 422 error parsing)
│   ├── sse.ts             ← SSE helpers: fetch-based streaming with auth (per-workflow + global)
│   └── viz-utils.ts       ← Viz type definitions + rerenderViz() utility for client-side viz switching
└── components/
    ├── ui/
    │   ├── Icon.tsx           ← Centralized SVG icon system (~30 Lucide-style icons, no npm dep)
    │   ├── SidebarSection.tsx ← Reusable collapsible section with icon, title, count badge, action
    │   ├── StatusDot.tsx      ← Animated status indicator (success/warning/error/idle/loading, ARIA)
    │   ├── ActionButton.tsx   ← Consistent icon button (ghost/danger/accent, tooltip, focus ring, a11y)
    │   ├── Tooltip.tsx        ← Accessible tooltip (hover + focus, role=tooltip, aria-describedby)
    │   ├── ClientShell.tsx    ← Client wrapper: ErrorBoundary + ToastContainer + ConfirmModal
    │   ├── ErrorBoundary.tsx  ← Global React error boundary (prevents white-screen crashes)
    │   ├── ToastContainer.tsx ← Toast notification renderer (bottom-right corner)
    │   ├── ConfirmModal.tsx   ← Reusable confirmation modal (replaces native confirm())
    │   ├── LlmModelSelector.tsx ← Reusable LLM provider+model selector (stacked layout)
    │   └── Spinner.tsx        ← Reusable loading spinner
    ├── auth/AuthGate.tsx   ← Login/register with branded header, Google OAuth
    ├── Sidebar.tsx         ← Collapsible sidebar (w-64 ↔ w-16), grouped Setup/Workspace sections,
    │                          sticky header with logo, user avatar + sign-out, section toggles
    ├── chat/
    │   ├── ChatPanel.tsx   ← Message list + knowledge-only mode toggle + error retry
    │   ├── ChatMessage.tsx ← Individual message with response_type-aware rendering + retry button
    │   ├── ChatSessionList.tsx ← Session switcher with icons, loading states
    │   └── ToolCallIndicator.tsx ← Real-time tool call progress during streaming
    ├── projects/
    │   ├── ProjectSelector.tsx  ← CRUD + role badges + ActionButton icons + card-style items
    │   └── InviteManager.tsx    ← Invite users, manage members, error toasts
    ├── invites/PendingInvites.tsx ← Accept/decline incoming invites with error toasts
    ├── connections/ConnectionSelector.tsx ← CRUD + StatusDot + two-line items + IDX/SYNC badges
    ├── ssh/SshKeyManager.tsx ← Add/list/delete SSH keys with key icon cards
    ├── rules/RulesManager.tsx ← CRUD with icon buttons + default/global badges
    ├── knowledge/KnowledgeDocs.tsx ← Browse indexed docs with doc-type icons
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
| `POST` | `/api/auth/google` | Google OAuth login (sends GIS ID token) |
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
| `POST` | `/api/invites/{project_id}/invites` | Invite a user by email (owner only) |
| `GET` | `/api/invites/{project_id}/invites` | List invites (owner only) |
| `DELETE` | `/api/invites/{project_id}/invites/{id}` | Revoke a pending invite (owner only) |
| `POST` | `/api/invites/accept/{invite_id}` | Accept an invite |
| `GET` | `/api/invites/pending` | List pending invites for current user |
| `GET` | `/api/invites/{project_id}/members` | List project members |
| `DELETE` | `/api/invites/{project_id}/members/{user_id}` | Remove a member (owner only) |
| `POST` | `/api/visualizations/render` | Render visualization |
| `POST` | `/api/visualizations/export` | Export data (CSV/JSON/XLSX) |
| `GET` | `/api/workflows/events` | SSE workflow progress |
| `GET` | `/api/health` | Basic health check |
| `GET` | `/api/health/modules` | Per-module health status |

### Security Model

| Concern | Implementation |
|---|---|
| **Authentication** | JWT tokens (HS256), 24h expiry, bcrypt password hashing. Google OAuth via GIS ID token verification. All routes require auth (except `/auth/*` and `/health`). |
| **Authorization** | Role-based access control per project: owner, editor, viewer. Membership checked via `MembershipService.require_role()`. |
| **Project sharing** | Email-based invite system. Invites auto-accept on registration. Session isolation per user. |
| **Encryption at rest** | Fernet (AES-128-CBC + HMAC-SHA256) for SSH keys, passwords, connection strings |
| **Query safety** | SafetyGuard blocks DML/DDL in read-only mode, dialect-aware parsing |
| **Rate limiting** | slowapi: 5/min register, 10/min login, 20/min chat |
| **CORS** | Configurable origins via `CORS_ORIGINS` env var |
| **SSH key handling** | In-memory for DB tunnels, temp file (0600) for Git only, never returned via API. Keys are user-scoped (user_id FK). `get_decrypted()` enforces ownership when `user_id` is provided. |
| **Shell injection prevention** | SSH exec template variables (`db_name`, `db_user`, `db_host`, `db_password`) are shell-escaped via single-quoting before substitution. Queries are piped via stdin. |
| **Invite scoping** | `revoke_invite()` enforces `project_id` to prevent cross-project invite revocation by guessing IDs. |
| **WebSocket auth** | JWT token passed as query parameter, validated before connection acceptance |

### Database Schema (Internal)

The agent uses SQLite (default) or PostgreSQL (recommended for production) to store its own data:

```
users            — id, email, password_hash (nullable for Google users), display_name, is_active, auth_provider (email|google), google_id, created_at
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
project_cache    — id, project_id, knowledge_json, profile_json, created_at, updated_at
db_index         — id, connection_id (FK→connections CASCADE), table_name, table_schema, column_count, row_count, sample_data_json, ordering_column, latest_record_at, is_active, relevance_score, business_description, data_patterns, column_notes_json, query_hints, code_match_status, code_match_details, indexed_at  [UNIQUE(connection_id, table_name)]
db_index_summary — id, connection_id (FK→connections CASCADE, UNIQUE), total_tables, active_tables, empty_tables, orphan_tables, phantom_tables, summary_text, recommendations, indexed_at
agent_learnings  — id, connection_id (FK→connections CASCADE), category, subject, lesson, lesson_hash, confidence, source_query, source_error, times_confirmed, times_applied, is_active  [UNIQUE(connection_id, category, subject, lesson_hash)]
agent_learning_summaries — id, connection_id (FK→connections CASCADE, UNIQUE), total_lessons, lessons_by_category_json, compiled_prompt, last_compiled_at
```

Managed via **Alembic migrations** (20 revisions: initial → custom_rules → users → branch_and_rag_feedback → project_cache_and_rag_commit_sha → user_rating → project_members_invites_ownership → google_oauth_fields → tool_calls_json → ssh_exec_mode → indexing_checkpoint → cascade_delete_project_fks → add_user_id_to_ssh_keys → per_purpose_llm_models → add_connection_id_to_chat_sessions → add_default_rule_fields → add_db_index_tables → add_indexing_status_to_summary → add_code_db_sync_tables → add_column_distinct_values → add_agent_learning_tables).

All child tables referencing `projects.id` use `ON DELETE CASCADE` so deleting a project automatically removes all related rows (connections, chat sessions, knowledge docs, commit indices, project cache, RAG feedback, members, invites, indexing checkpoints).

---

## Configuration

Copy `backend/.env.example` to `backend/.env` and set:

| Variable | Required | Description |
|---|---|---|
| `MASTER_ENCRYPTION_KEY` | **Yes** | Fernet key for encrypting stored credentials. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `JWT_SECRET` | **Yes (prod)** | Secret for signing JWT tokens. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `GOOGLE_CLIENT_ID` | No | Google OAuth Client ID from [Google Cloud Console](https://console.cloud.google.com/apis/credentials). Enables "Sign in with Google" button. |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | No | Same value as above, set in `frontend/.env` for the GIS JavaScript SDK. |
| `OPENAI_API_KEY` | One of three | OpenAI API key (for GPT-4o, etc.) |
| `ANTHROPIC_API_KEY` | One of three | Anthropic API key (for Claude) |
| `OPENROUTER_API_KEY` | One of three | OpenRouter API key (multi-model proxy) |
| `DATABASE_URL` | No | Default: `sqlite+aiosqlite:///./data/agent.db`. For production: `postgresql+asyncpg://...` |
| `JWT_EXPIRE_MINUTES` | No | Token expiry (default: 1440 = 24h) |
| `CORS_ORIGINS` | No | JSON array of allowed origins (default: `["http://localhost:3000"]`) |
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
| `make dev` | Start backend (:8000) + frontend (:3000) |
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
- Backend unit tests: 740 across 31 test files
- Backend integration tests: 100 across 13 test files
- Frontend tests: 44 across 6 test files
- **Total: 884 tests**

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
| Workflow Tracker | 11 (events, subscribe, step, queue) | — |
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
| DB Index Validator | 21 (fallback analysis, build prompt, analyze table, batch analysis, generate summary) | — |
| DB Index Service | 16 (prompt context, table detail, response format, status check) | — |
| Learning Analyzer | 10 (table extraction, table preference, column correction, format discovery, schema gotcha, performance hint) | — |
| Agent Learning Service | 4 (compile prompt empty/with learnings, category labels, invalid category) | — |
| Custom Rules | 16 (file loading, YAML, context generation, default template, DB rule IDs in context) | 9 (CRUD, access control, default rule auto-creation) |
| Retry | 5 (success, retry, max attempts, callback) | — |
| ConversationalAgent | 12 (text reply, SQL tool call, knowledge search, multi-tool, no-connection, error handling, table_map, user_id passthrough, manage_rules tool call log) | 13 (full chat: text/SQL/knowledge flow, optional connection, stream events, rules_changed flag, user_id forwarding) |
| ToolExecutor | 52 (execute_query, search_knowledge, get_schema_info, get_custom_rules, get_entity_info, unknown tool, RAG threshold, get_db_index, get_sync_context, get_query_context, _format_table_context, auto_detect_tables, manage_custom_rules CRUD/validation/RBAC) | — |
| Prompt Builder | 13 (all combinations of connection/knowledge flags, re-visualization prompt, manage_rules capability/guideline) | — |
| Alembic | 2 (upgrade head, downgrade base) | — |
| API Routes | 19 (projects, connections, viz routes, stale index/sync status reset, pipeline failure propagation, startup stale reset) | — |
| Models Routes | 11 (sorting, cache, static providers, error fallback) | — |
| Membership Service | 12 (add, get_role, require_role, remove, list, accessible) | — |
| Invite Service | 11 (create, duplicate, reject, revoke, accept, pending, auto-accept) | — |
| Auth | — | 11 (register, login, duplicate, wrong password, Google login, account linking, token validation) |
| Projects | — | 9 (CRUD lifecycle + RBAC: owner/viewer/non-member, member-scoped list) |
| Invites (routes) | — | 9 (create, list, revoke, accept, pending, members, remove, non-owner restrictions) |
| Connections | — | 5 (CRUD lifecycle + viewer access control) |
| Rules | — | 5 (CRUD + viewer access control) |
| Chat Sessions | — | 8 (create, delete, not found, session isolation, cross-user protection, connection_id, tool_calls_json in messages) |
| WebSocket Auth | — | 4 (valid/invalid/empty/tampered token) |
| Health | — | 2 (basic, modules) |
| Frontend (api) | 4 (fetch mock, auth headers) | — |
| Frontend (auth-store) | 4 (login, error, logout, restore) | — |
| Frontend (app-store) | 10 (setActiveProject, addMessage, localStorage persistence, updateMessageId, userRating, rawResult) | — |

---

## Deployment

### Production — Heroku (primary)

The production environment runs on **Heroku** as two Docker container apps with Heroku Postgres.

**Live URLs:**

| Service | URL |
|---|---|
| Backend API | https://esim-db-agent-api-d1031c6e1d47.herokuapp.com/api |
| Frontend | https://esim-db-agent-web-e3dda1811661.herokuapp.com |
| Health check | https://esim-db-agent-api-d1031c6e1d47.herokuapp.com/api/health |

**Architecture on Heroku:**
- `esim-db-agent-api` — container stack, `Dockerfile.backend`, Heroku Postgres (Essential-0)
- `esim-db-agent-web` — container stack, `Dockerfile.frontend`, connects to the API app

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
docker build --platform linux/amd64 -t registry.heroku.com/esim-db-agent-api/web -f Dockerfile.backend .
docker build --platform linux/amd64 -t registry.heroku.com/esim-db-agent-web/web \
  --build-arg NEXT_PUBLIC_API_URL=https://esim-db-agent-api-d1031c6e1d47.herokuapp.com/api \
  --build-arg NEXT_PUBLIC_WS_URL=wss://esim-db-agent-api-d1031c6e1d47.herokuapp.com/api/chat/ws \
  -f Dockerfile.frontend .

# Push and release
docker push registry.heroku.com/esim-db-agent-api/web
docker push registry.heroku.com/esim-db-agent-web/web
heroku container:release web --app esim-db-agent-api
heroku container:release web --app esim-db-agent-web
```

**Setting up a new Heroku deployment from scratch:**

```bash
# 1. Create apps with container stack
heroku create esim-db-agent-api --stack container
heroku create esim-db-agent-web --stack container

# 2. Add Postgres to backend (replaces SQLite)
heroku addons:create heroku-postgresql:essential-0 --app esim-db-agent-api

# 3. Set backend env vars
heroku config:set \
  MASTER_ENCRYPTION_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  DEFAULT_LLM_PROVIDER=openai \
  OPENAI_API_KEY=sk-... \
  CORS_ORIGINS='["https://your-frontend-app.herokuapp.com"]' \
  --app esim-db-agent-api

# 4. Set frontend env vars
heroku config:set \
  NEXT_PUBLIC_API_URL=https://your-backend-app.herokuapp.com/api \
  NEXT_PUBLIC_WS_URL=wss://your-backend-app.herokuapp.com/api/chat/ws \
  --app esim-db-agent-web

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
