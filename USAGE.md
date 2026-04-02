# Usage Guide

> Comprehensive step-by-step guide to all CheckMyData.ai features.
> For installation and setup, see [INSTALLATION.md](INSTALLATION.md).

---

## Getting Started

After [installing](INSTALLATION.md) and starting the app:

- **Backend API** runs at `http://localhost:8000`
- **Frontend** runs at `http://localhost:3100`

Open the frontend URL in your browser to see the landing page. Click **Get Started** to register.

---

## 1. Register / Login

When you first open the app, you see the **AuthGate** — a login/registration form.

- Enter email + password + display name to **create an account**
- Or click **"Sign in with Google"** to authenticate via your Google account (no password needed)
- Emails are normalized (lowercased, trimmed) on registration and login for case-insensitive matching

### Guided Onboarding Wizard

First-time users see a 5-step onboarding wizard:

1. **Connect your database** — select db type, enter host/port/credentials, optionally configure SSH tunnel
2. **Test connection** — auto-runs on mount, shows animated status, auto-advances on success
3. **Index your database** — kicks off schema analysis so the AI understands your tables; can be skipped
4. **Connect your code (Optional)** — link a Git repo for deeper codebase understanding
5. **Ask your first question** — pre-populated example question to try the chat immediately

Additional options:
- **"Try demo instead"** button on step 1 calls `POST /api/demo/setup` to create a sample project
- **"Skip setup entirely"** link marks onboarding complete without any setup
- JWT token is stored in `localStorage` and automatically refreshed before expiry

**Google OAuth Setup** (required for "Sign in with Google"):

1. Go to [Google Cloud Console → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) and configure app name, scopes (`openid`, `email`, `profile`), and publishing status
2. Go to [Credentials](https://console.cloud.google.com/apis/credentials) → Create OAuth 2.0 Client ID (Web application type)
3. Under **Authorized JavaScript origins**, add `http://localhost:3100` (dev) and your production domain
4. Copy the **Client ID** and set it in `backend/.env` → `GOOGLE_CLIENT_ID` and `frontend/.env.local` → `NEXT_PUBLIC_GOOGLE_CLIENT_ID`
5. No `GOOGLE_CLIENT_SECRET` is needed — the app uses Google Identity Services (GIS) with ID-token verification

---

## 2. Add SSH Keys

Before connecting to servers behind SSH:

1. In the sidebar, find the **SSH Keys** section and click **+ Add**
2. Paste your **private key** (PEM format, contents of `~/.ssh/id_ed25519` or similar)
3. Give it a **name** (e.g. "production-server")
4. Optionally enter a **passphrase** if the key is encrypted
5. Click **Save** — the system validates the key, shows its type and fingerprint

The key is encrypted at rest with AES (Fernet). The API never returns the raw private key.

---

## 3. Create a Project

A **Project** groups together a Git repository, LLM configuration, and database connections.

1. In the sidebar **Projects** section, click **+ New**
2. Enter a **name** and optionally set a **Git repo URL** — the system auto-verifies access and populates branches
3. Optionally configure **per-purpose LLM models** (Indexing, Agent, SQL) under the collapsible "LLM Models" section
4. Click **Create**

---

## 4. Create a Database Connection

Each project can have multiple database connections:

| Database | Default Port | Connector |
|----------|-------------|-----------|
| PostgreSQL | 5432 | `asyncpg` |
| MySQL | 3306 | `aiomysql` |
| MongoDB | 27017 | `motor` |
| ClickHouse | 9000 | `clickhouse-connect` |

To add a connection:

1. Select a project, find **Connections**, click **+ New**
2. Enter connection name and select **db type**
3. Fill in host, port, database name, username, password — or toggle "Use connection string" for a full URI
4. **SSH Tunnel** (optional): Enter SSH host, port, user, select an SSH key. The system creates the tunnel automatically.
5. **SSH Exec Mode** (alternative): For servers where port forwarding is blocked. Uses CLI commands over SSH.
6. **Read-only mode** (default on): blocks DML/DDL queries
7. Click **Create Connection**, then **↻** to test the full chain

---

## 5. Index the Database (DB Index)

After testing a connection:

1. Click the **IDX** button next to the connection
2. The backend runs a 6-step pipeline: introspect schema, fetch samples, load project knowledge, LLM validation, store results, generate summary
3. The IDX button shows status (gray = not indexed, amber = in progress, green = indexed)
4. Once indexed, the query agent gains enriched schema context, table descriptions, and query hints

**Configuration:** `DB_INDEX_TTL_HOURS` (staleness, default 24h), `DB_INDEX_BATCH_SIZE` (tables per LLM call, default 5), `AUTO_INDEX_DB_ON_TEST` (auto-index on successful test, default false)

---

## 6. Code-DB Sync

After both repository and database are indexed:

1. Click the **SYNC** button next to IDX
2. The system cross-references your codebase with the database, discovering data formats, conversion rules, enum values, and business logic
3. The query agent gains proactive warnings about money/currency formats, date formats, soft-delete patterns, and more

---

## 7. Agent Learning Memory (ALM)

The agent automatically learns from query outcomes and accumulates per-connection knowledge:

- After each query retry, the system analyzes what went wrong and extracts lessons
- Lessons include: table preferences, column usage, data formats, query patterns, schema gotchas, performance hints
- Confidence scores grow with confirmations and decay over time
- A blue **LEARN** badge appears on connections with accumulated learnings — click to view, edit, or manage

---

## 8. Index the Repository (Knowledge Base)

If your project has a Git repo URL:

1. Click **Index Repository** in the sidebar
2. The backend runs a multi-pass pipeline: clone/pull, detect changes, analyze files (11 ORMs supported), profile project, cross-file analysis, generate docs, store vectors
3. After indexing, the Knowledge Docs section shows all indexed documents

**Incremental indexing**: Only files changed since the last commit are processed. **Resumable**: If interrupted, the next run resumes from the last completed step.

---

## 9. Chat — Ask Questions

With a project selected (and optionally a connection):

1. Open or create a chat session
2. Type your question in natural language:
   - **Data questions**: _"How many active plans were created last month?"_
   - **Knowledge questions**: _"How does the authentication flow work?"_
   - **Conversational**: _"Can you explain that result?"_
3. Each response shows: answer (Markdown), SQL query, metadata badges, thumbs up/down, visualizations with export options
4. **Session titles** are auto-generated by the LLM
5. **Viz Type Toolbar**: Switch between Table, Bar, Line, Pie, Scatter views without re-querying
6. **Export**: Download results as CSV, JSON, or XLSX
7. **Chat-based rule creation**: Ask the agent to remember conventions directly from chat
8. **Chat History Search**: Press **Cmd+K** (Mac) or **Ctrl+K** to search across all messages

---

## 10. Custom Rules

Rules inject additional context into the LLM prompt:

- **File-based**: Place `.md` or `.yaml` files in `./rules/`
- **DB-based**: Create via the **Rules** section in the sidebar; click any rule to open it in a centered popup for editing (viewers see a read-only view)
- **Default rule**: Every new project gets a comprehensive "Business Metrics & Guidelines" rule (fully editable)
- **Dirty-state Save**: The Save button is only enabled when you've actually changed something

---

## 11. Sharing a Project (Email Invites)

Project owners can invite collaborators:

1. Hover over a project, click the team icon, enter email and select a role (**Editor** or **Viewer**)
2. **Roles**: Owner (full CRUD), Editor (chat + sessions), Viewer (read-only chat)
3. Invitees receive email notifications (via Resend when configured)
4. Each user gets isolated chat sessions while sharing project data

---

## 12. Saved Queries (Notes Panel)

Save SQL queries from agent responses for quick reference:

1. Click the **bookmark icon** on any SQL result to save the query, data, answer, and visualization
2. Click the **bookmark button** in the header to open the Notes panel
3. Each note can be **refreshed** (re-runs the SQL), **edited**, **shared with team**, or **deleted**

---

## 13. Team Dashboards

Compose saved queries into grid-based dashboards:

1. In Sidebar → Dashboards, click "New Dashboard"
2. Add cards by selecting from saved queries
3. Dashboards support 2/3-column layouts, auto-refresh, and team sharing

---

## 14. Scheduled Queries and Data Alerts

Set up recurring SQL queries with alert conditions:

1. Click "New Schedule" in the Schedules section
2. Enter title, SQL, and cron expression (presets available)
3. Add alert conditions (column comparisons, percentage change)
4. The system runs queries automatically and sends in-app notifications when thresholds are met

---

## 15. Batch Query Execution

Run multiple queries at once:

1. Click the **layers icon** in the chat header
2. Add queries manually or from saved notes
3. Click "Run All" — results appear in a tabbed view
4. **Export All as XLSX** creates a multi-sheet Excel file

---

## 16. Connection Health Monitoring

The system continuously monitors database connections:

- Background health checks every 5 minutes
- Status indicators: green (healthy), amber (degraded), red (down)
- SSH tunnel auto-reconnect with exponential backoff
- Manual reconnect button when connections go down

---

## 17. Data Validation & Self-Improvement

The agent has a proactive data accuracy verification system:

- **Data Sanity Checker**: Automatic checks on every query result (null columns, future dates, benchmark comparison)
- **Validation Feedback**: Confirm, reject, or mark as approximate — builds benchmarks and learnings
- **"Wrong Data" Investigation**: Click the warning icon on any result to launch an automated investigation with root cause analysis and corrected SQL
- **Data Quality Dashboard**: See confidence scores, accuracy rates, and error patterns in the Analytics section

---

## 18. Data Enrichment Pipeline

The orchestrator can enrich query results between steps:

- **ip_to_country**: Offline GeoIP lookup with two-tier cache
- **phone_to_country**: Offline E.164 dialing code mapping
- **aggregate_data**: Group by columns with multiple aggregation functions
- **filter_data**: Filter enriched results by column values

---

## 19. Query Cost & Session Management

- **Cost Estimator**: Shows estimated token count and cost before sending a query
- **Context Budget Indicator**: Visual bar showing schema, rules, learnings, and history allocation
- **Auto-Session Rotation**: When approaching context limits, the system automatically summarizes and continues in a new session

---

## Makefile Commands

| Command | Description |
|---------|-------------|
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
| `make docker-up` | Build images, start containers |
| `make docker-down` | Stop and remove containers |
| `make docker-clean` | Stop containers and remove volumes |
| `make docker-logs` | Tail container logs |
