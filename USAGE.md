# Usage Guide

## Getting Started

After [installation](INSTALLATION.md), open `http://localhost:3100` in your
browser.

## Core Flows

### 1. Registration and Login

- **Email/password**: Enter email, password (8+ chars), and display name
- **Google OAuth**: Click "Sign in with Google" (requires `GOOGLE_CLIENT_ID`)
- First-time users see an onboarding wizard

### 2. Onboarding Wizard

The 5-step wizard guides new users:

1. **Connect database** — Choose type (PostgreSQL, MySQL, ClickHouse, MongoDB),
   enter credentials, optionally configure SSH tunnel
2. **Test connection** — Auto-runs connectivity check
3. **Index schema** — Analyzes your database structure for AI understanding
4. **Connect code repo** (optional) — Link a Git repository for deeper context
5. **Ask first question** — Try a pre-populated example query

Alternatively, click **"Try demo instead"** for a sample project.

### 3. Chat — Querying Your Data

Type a natural language question in the chat input:

```
"How many orders were placed last month?"
"Show me the top 10 customers by revenue"
"What's the average order value by country?"
```

The AI agent will:
1. Analyze your database schema
2. Generate and validate an SQL query
3. Execute the query safely
4. Return results with automatic visualization (table, chart, or both)

**Keyboard shortcut**: Press `Cmd/Ctrl+K` to focus the chat input from anywhere.

### 4. Visualizations

Query results are automatically visualized. The VizAgent picks the best chart
type based on the data:
- Bar charts for comparisons
- Line charts for time series
- Pie charts for distributions
- Data tables for detailed rows

Export results as CSV or JSON using the export buttons.

### 5. Saved Notes

Bookmark useful queries by clicking the save icon on any result. Access saved
notes from the sidebar.

### 6. Batch Queries

Run multiple queries at once:
1. Open the batch runner from the sidebar
2. Add queries manually or select from saved notes
3. Execute all queries in sequence
4. Export results as a batch

### 7. Dashboards

Create persistent dashboards from saved queries:
1. Navigate to Dashboards in the sidebar
2. Create a new dashboard
3. Add saved notes as dashboard tiles
4. Dashboards auto-refresh their data

### 8. Data Validation

When the AI returns results, validate them:
- Click the checkmark to confirm accuracy
- Click the X to report incorrect results
- Provide expected values and rejection reasons
- The agent learns from your feedback

### 9. Custom Rules

Define validation rules for your data:
1. Go to Rules in the sidebar
2. Create rules in markdown, YAML, or text format
3. Rules are applied to future queries for context

### 10. Team Collaboration

- Invite team members by email from project settings
- Each user gets their own chat sessions
- All team members share the same database connections and project data
- Role-based access: owner, editor, viewer

## Makefile Commands

```bash
make setup          # Full setup (backend + frontend + env + migrations)
make dev            # Start both servers
make dev-backend    # Start backend only
make dev-frontend   # Start frontend only
make stop           # Stop all servers
make logs           # Tail server logs
make test           # Backend unit tests
make test-frontend  # Frontend tests
make test-all       # All tests
make lint           # Backend linting
make check          # Lint + all tests
make clean          # Remove build artifacts
```
