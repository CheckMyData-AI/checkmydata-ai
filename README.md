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
4. Optionally set:
   - **LLM provider** (`openai`, `anthropic`, or `openrouter`)
   - **LLM model** (e.g. `gpt-4o`, `claude-sonnet-4-20250514`)
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
9. Click **Test SSH** to verify SSH connectivity independently, then **Test DB** to verify the full chain

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

### 6. Index the Repository (Knowledge Base)

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

### Activity Log (Bottom Panel)

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

### 7. Chat — Ask Questions

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
├── Data question → calls get_schema_info, get_custom_rules, execute_query
│   ↓
│   [Validation Loop] — Pre-validate → Safety check → EXPLAIN → Execute
│   ↓  (if error: Classify → Enrich → Repair → retry, up to 3 attempts)
│   [Interpret results] → Table / Chart / Text + Export
│
├── Knowledge question → calls search_knowledge
│   ↓
│   Returns answer with source citations
│
└── Conversation → responds directly (no tool calls)
```

4. Each assistant message shows:
   - The **answer** in natural language
   - The **SQL query** that was executed
   - **Metadata badges**: execution time, row count, visualization type, token usage
   - **Thumbs up/down feedback** buttons to rate answer quality
   - A **"show details"** expander with:
     - **Code Context** — which RAG documents were used (with similarity scores)
     - **Attempt History** — full retry details if validation loop triggered
     - **Token Usage** — prompt, completion, and total tokens consumed
   - A **table or chart** with the data
   - **Export buttons** to download as CSV, JSON, or XLSX
5. **Session titles** are auto-generated by the LLM after the first response
6. **Identical queries** are served from a short-lived cache (2-minute TTL) to avoid re-executing the same SQL

### 8. Custom Rules

Rules inject additional context into the LLM prompt, guiding how queries are built:

- **File-based rules**: Place `.md` or `.yaml` files in `./rules/` directory
- **DB-based rules**: Create via the **Rules** section in the sidebar

Example rules:
- _"The `created_at` field uses UTC timestamps. Always convert to user timezone."_
- _"Revenue = price × quantity − discount. Always use this formula."_
- _"Table `legacy_users` is deprecated. Use `users_v2` instead."_

Rules can be **global** or **project-scoped**.

### 9. Editing & Managing

- **Edit project**: Hover over a project and click the ✎ icon — change name, repo, LLM config
- **Edit connection**: Hover over a connection and click the ✎ icon — update host, credentials
- **Delete**: Click the × icon (projects, connections, SSH keys, rules, chat sessions)
- **SSH key protection**: Deleting a key that is used by a project or connection returns a 409 error

### 10. Sharing a Project (Email Invite System)

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
│   ├── tools.py        ← Tool definitions (execute_query, search_knowledge, get_schema_info, get_custom_rules)
│   ├── tool_executor.py← Executes tool calls, wraps ValidationLoop / VectorStore / SchemaIndexer
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
│   └── doc_store.py    ← Doc storage keyed by (project_id, source_path)
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
│   └── rag_feedback.py ← RAG chunk quality tracking (version-scoped)
├── services/           ← Business logic layer
│   ├── project_service.py, connection_service.py
│   ├── ssh_key_service.py, chat_service.py
│   ├── rule_service.py, auth_service.py
│   ├── membership_service.py ← Role checking, member CRUD, accessible projects
│   ├── invite_service.py ← Create/accept/revoke invites, auto-accept on registration
│   ├── rag_feedback_service.py ← Record & query RAG effectiveness (version-scoped)
│   ├── project_cache_service.py ← Persist/load ProjectKnowledge + ProjectProfile between runs
│   ├── checkpoint_service.py ← CRUD for indexing checkpoints (resumable pipeline state)
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
│    • search_knowledge (if knowledge base indexed)      │
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
├── tools.py           ← Tool definitions (execute_query, search_knowledge, get_schema_info, get_custom_rules)
├── tool_executor.py   ← Executes tool calls, wraps existing ValidationLoop / VectorStore / SchemaIndexer
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

SSH connections include a 30-second connect timeout and 15-second keepalive interval. The `is_alive()` check actively pings the server (not just socket inspection). If an SSH connection drops mid-query, the exec connector automatically attempts one reconnection before failing. The SSH test endpoint (`POST /connections/{id}/test-ssh`) allows testing SSH connectivity independently from the database.

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
  • Incremental mode: load cached ProjectKnowledge, re-scan only changed/deleted files
    ↓
Pass 4: DocGenerator — enriched LLM documentation
  • Each model sent to LLM WITH cross-file context (relationships, enum values, usage data)
  • Large files split by class/model boundary (no blind truncation)
  • Project-level summary document generated (entity map, dead tables, enums)
    ↓
Pass 5: Chunker + VectorStore
  • Stale chunks cleaned before upserting new ones
  • Entity-aware chunk boundaries
  • Chunks tagged with source_path, models, tables, commit_sha
    ↓
ChromaDB — RAG retrieval (supports embedded + remote server mode)
    ↓
DocStore — one row per (project_id, source_path), updated in-place
```

### Frontend Architecture

```
Next.js 15 / React 19 / TypeScript / Tailwind CSS

src/
├── app/
│   ├── page.tsx           ← Main page: AuthGate → Sidebar + ChatPanel + LogPanel
│   ├── layout.tsx         ← Root layout: wraps app in ClientShell (ErrorBoundary + Toast + ConfirmModal)
│   └── globals.css        ← Global styles + animation keyframes
├── stores/
│   ├── app-store.ts       ← Zustand: projects, connections, sessions, messages, chatMode
│   ├── auth-store.ts      ← Zustand: user, token, login/register/logout
│   ├── log-store.ts       ← Zustand: activity log entries, panel state, SSE connection status
│   └── toast-store.ts     ← Zustand: toast notifications (success/error/info, 4s auto-dismiss)
├── hooks/
│   └── useGlobalEvents.ts ← Global SSE subscription hook (all workflow events → log store)
├── lib/
│   ├── api.ts             ← REST client (fetch wrapper + auth headers + 422 error parsing)
│   └── sse.ts             ← SSE helpers: fetch-based streaming with auth (per-workflow + global)
└── components/
    ├── ui/
    │   ├── ClientShell.tsx    ← Client wrapper: ErrorBoundary + ToastContainer + ConfirmModal
    │   ├── ErrorBoundary.tsx  ← Global React error boundary (prevents white-screen crashes)
    │   ├── ToastContainer.tsx ← Toast notification renderer (bottom-right corner)
    │   ├── ConfirmModal.tsx   ← Reusable confirmation modal (replaces native confirm())
    │   └── Spinner.tsx        ← Reusable loading spinner
    ├── auth/AuthGate.tsx   ← Login/register form with password hint, Google loading state
    ├── Sidebar.tsx         ← Collapsible sections, onboarding guide, section toggles with localStorage persistence
    ├── chat/
    │   ├── ChatPanel.tsx   ← Message list + knowledge-only mode toggle + error retry
    │   ├── ChatMessage.tsx ← Individual message with response_type-aware rendering + retry button
    │   ├── ChatSessionList.tsx ← Session switcher with loading states
    │   └── ToolCallIndicator.tsx ← Real-time tool call progress during streaming
    ├── projects/
    │   ├── ProjectSelector.tsx  ← CRUD + inline name validation + error toasts
    │   └── InviteManager.tsx    ← Invite users, manage members, error toasts
    ├── invites/PendingInvites.tsx ← Accept/decline incoming invites with error toasts
    ├── connections/ConnectionSelector.tsx ← CRUD + test error details + SSH tunnel guidance
    ├── ssh/SshKeyManager.tsx ← Add/list/delete SSH keys with loading state
    ├── rules/RulesManager.tsx ← CRUD with try-catch + error toasts
    ├── knowledge/KnowledgeDocs.tsx ← Browse indexed docs + empty state message
    ├── workflow/WorkflowProgress.tsx ← Real-time step tracking (SSE-based)
    ├── workflow/StreamWorkflowProgress.tsx ← Inline progress from SSE stream events
    ├── log/LogPanel.tsx ← Bottom panel: real-time activity log with color-coded pipeline events
    └── viz/ ← DataTable, ChartRenderer, ExportButtons
```

**State management**: Zustand stores persist the active project, connection, chat session, and messages. Auth state is synced with `localStorage` for persistence across refreshes. Sidebar collapse state is persisted in `localStorage`.

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
| **SSH key handling** | In-memory for DB tunnels, temp file (0600) for Git only, never returned via API. Keys are user-scoped (user_id FK). |
| **WebSocket auth** | JWT token passed as query parameter, validated before connection acceptance |

### Database Schema (Internal)

The agent uses SQLite (default) or PostgreSQL (recommended for production) to store its own data:

```
users            — id, email, password_hash (nullable for Google users), display_name, is_active, auth_provider (email|google), google_id, created_at
projects         — id, name, description, repo_url, repo_branch, ssh_key_id, owner_id, llm_provider, llm_model
connections      — id, project_id, name, db_type, ssh_*, db_*, ssh_exec_mode, ssh_command_template, ssh_pre_commands, is_read_only, is_active
ssh_keys         — id, user_id (FK→users), name, private_key_encrypted, passphrase_encrypted, fingerprint, key_type
project_members  — id, project_id, user_id, role (owner|editor|viewer), created_at  [UNIQUE(project_id, user_id)]
project_invites  — id, project_id, email, invited_by, role, status (pending|accepted|revoked), created_at, accepted_at
chat_sessions    — id, project_id, user_id, title, created_at
chat_messages    — id, session_id, role, content, metadata_json, user_rating, created_at
custom_rules     — id, project_id, name, content, format, created_at, updated_at
knowledge_docs   — id, project_id, doc_type, source_path, content, commit_sha, updated_at
commit_index     — id, project_id, commit_sha, branch, commit_message, indexed_files, created_at
rag_feedback     — id, project_id, chunk_id, source_path, doc_type, distance, query_succeeded, commit_sha, created_at
project_cache    — id, project_id, knowledge_json, profile_json, created_at, updated_at
```

Managed via **Alembic migrations** (12 revisions: initial → custom_rules → users → branch_and_rag_feedback → project_cache_and_rag_commit_sha → user_rating → project_members_invites_ownership → google_oauth_fields → tool_calls_json → ssh_exec_mode → indexing_checkpoint → cascade_delete_project_fks).

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
| `MAX_HISTORY_TOKENS` | No | Token budget for chat history before summarization kicks in (default: 4000) |
| `INCLUDE_SAMPLE_DATA` | No | Include sample rows in LLM prompt (default: false) |
| `CUSTOM_RULES_DIR` | No | Directory for file-based rules (default: `./rules`) |
| `LOG_FORMAT` | No | `text` (default) or `json` (structured) |
| `LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

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
- Backend unit tests: 474 across 26 test files
- Backend integration tests: 79 across 13 test files
- Frontend tests: 27 across 5 test files
- **Total: 580 tests**

### Test Coverage by Module

| Module | Unit Tests | Integration Tests |
|---|---|---|
| Orchestrator | 7 (process_question, connector key, disconnect) | — |
| Query Builder | 6 (dialect-aware prompts) | — |
| Validation Loop | 8 (first-try, retry, max attempts, safety, schema) | 6 (E2E retry flows) |
| Error Classifier | 18 (PG, MySQL, CH, Mongo, fallback) | — |
| Pre-Validator | 8 (valid, wrong col/table, ambiguous, fuzzy, MongoDB) | — |
| Post-Validator | 5 (success, error, empty, slow) | — |
| EXPLAIN Validator | 6 (PG, MySQL, error, warning, MongoDB skip) | — |
| SQL Parser | 16 (tables, columns, subqueries, CTEs, aggregations) | — |
| Schema Hints | 11 (fuzzy col/table, related tables, detail) | — |
| Retry Strategy | 16 (should_retry × 8, repair_hints × 8) | — |
| Context Enricher | 5 (column/table error, RAG, history) | — |
| Query Repairer | 3 (success, no tool call, LLM exception) | — |
| Query Validation | 9 (data models, serialization) | — |
| Safety Guard | 17 (read-only, DML, DDL, MongoDB) | — |
| SSH Key Service | 10 (CRUD, validation, passphrase, in-use) | 3 |
| SSH Key Routes | 9 (list, create, delete, duplicate, in-use) | — |
| SSH Exec Connector | 15 (connect, execute, test, build_command, pre-commands, custom template) | — |
| CLI Output Parser | 17 (TSV, CSV, psql tuples, MySQL batch, generic, edge cases) | — |
| Exec Templates | 12 (structure, format, defaults, substitution, special chars) | — |
| SSH Exec Connections | — | 6 (CRUD with exec mode, test-ssh, ssh_user in response) |
| Viz/Export | 14 (table, chart, text, CSV, JSON) | — |
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
| Custom Rules | 6 (file loading, YAML, context generation) | 4 |
| Retry | 5 (success, retry, max attempts, callback) | — |
| ConversationalAgent | 10 (text reply, SQL tool call, knowledge search, multi-tool, no-connection, error handling) | 10 (full chat: text/SQL/knowledge flow, optional connection, stream events) |
| ToolExecutor | 8 (execute_query, search_knowledge, get_schema_info, get_custom_rules, unknown tool) | — |
| Prompt Builder | 6 (all combinations of connection/knowledge flags) | — |
| Alembic | 2 (upgrade head, downgrade base) | — |
| API Routes | 9 (projects, connections, viz routes) | — |
| Models Routes | 11 (sorting, cache, static providers, error fallback) | — |
| Membership Service | 12 (add, get_role, require_role, remove, list, accessible) | — |
| Invite Service | 11 (create, duplicate, reject, revoke, accept, pending, auto-accept) | — |
| Auth | — | 11 (register, login, duplicate, wrong password, Google login, account linking, token validation) |
| Projects | — | 9 (CRUD lifecycle + RBAC: owner/viewer/non-member, member-scoped list) |
| Invites (routes) | — | 9 (create, list, revoke, accept, pending, members, remove, non-owner restrictions) |
| Connections | — | 5 (CRUD lifecycle + viewer access control) |
| Rules | — | 5 (CRUD + viewer access control) |
| Chat Sessions | — | 5 (create, delete, not found, session isolation, cross-user protection) |
| WebSocket Auth | — | 4 (valid/invalid/empty/tampered token) |
| Health | — | 2 (basic, modules) |
| Frontend (api) | 4 (fetch mock, auth headers) | — |
| Frontend (auth-store) | 4 (login, error, logout, restore) | — |
| Frontend (app-store) | 3 (setActiveProject, addMessage) | — |

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
| Connection test fails | Verify SSH tunnel config: SSH host/user/key must reach the server, DB host should be `127.0.0.1` for tunneled connections |
| 429 Too Many Requests | Rate limiting active. Wait and retry. Limits: 20 chat/min, 5 register/min |
| Indexing returns 409 | Indexing is already running as a background task. Wait for it to finish (check `/status` endpoint or SSE events) |
| Indexing interrupted, want to restart fresh | Click "Index Repository" with `force_full=true` to discard the checkpoint and start from scratch |
| Stale checkpoint blocking indexing | Checkpoints older than 24h are auto-cleaned on startup. You can also use `force_full=true` to discard manually |
| `CharacterNotInRepertoireError` during indexing | Binary files (ELF, images) could leak null bytes into PostgreSQL. Multi-layer fix: (1) git-sourced `changed_files` now filtered by `DB_RELEVANT_EXTENSIONS` matching `_find_db_relevant_files()`, (2) `is_binary_file()` checks extension + null bytes, (3) post-read null-byte content guard in `analyze()`, (4) `doc_store.upsert()` strips `\x00` before INSERT, (5) `doc_generator` fallback detects binary content and returns placeholder, (6) `pipeline_runner` pre-filters binary files from `changed_files` before analysis and skips binary-looking enriched docs |
| `NotImplementedError: No support for ALTER of constraints in SQLite` | Migration `c7d2e8f31a45` now uses `op.batch_alter_table()` with `naming_convention` for SQLite compatibility. Pull latest and re-run `make migrate`. For Docker, run `docker compose down -v && docker compose up --build` to start fresh |
