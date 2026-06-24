# QA Fix Loop — Tracker

> **What this is.** The autonomous remediation loop that consumes the per-module audit
> reports in [`reports/`](reports/) and fixes the findings. The audit agent keeps writing
> and extending the reports; this loop takes them one module at a time and drives each to
> production: **decompose → spec + plan → implement (logs + tests, TDD) → lint → deploy →
> verify no regressions → next module.**
>
> Source of truth for loop state. Each `/loop` wake-up reads this file to know which module
> and which phase it is on, then advances.

## Per-module cycle (phases)

| Phase | What happens | Gate to advance |
|-------|--------------|-----------------|
| **P0 Spec** | Read `reports/NN-*.md`, read the touched source, decompose every finding, write spec (`docs/superpowers/specs/2026-06-24-qa-fix-NN-*-design.md`) + plan (`docs/superpowers/plans/2026-06-24-qa-fix-NN-*.md`). Commit docs. | Spec + plan committed |
| **P1 Implement** | TDD per finding (failing test → fix → green). Add structured logs + audit entries. Frequent conventional commits. | All planned findings done, local tests green |
| **P2 Verify** | `make check` (ruff format check, ruff, mypy, full backend tests, coverage ≥ 72%); frontend `tsc + eslint + vitest` when frontend touched. | Full local CI parity green |
| **P3 Deploy** | Merge module branch → `main`, push (triggers Heroku auto-deploy). | Push succeeds, CI green |
| **P4 Post-deploy** | Verify prod health (`/api/health`), scan Heroku logs for new errors/regressions ("нет паков"). Mark module done; advance pointer. | Prod healthy, no new errors |

**Deploy safety:** deploy only at module boundaries, only after P2 is fully green locally.
Work happens on `fix/security-audit-2026-06-24`; P3 merges to `main`.

> **⚠ Deploy is gated (2026-06-24).** Direct `git push origin …:main` is blocked by the
> harness safety classifier (pushing to the default branch triggers a prod deploy). The loop
> therefore does **deploy-prep**: it pushes the branch and opens/updates a PR, but the actual
> prod merge is a **human step** (the user merges the PR, or adds a Bash permission rule to allow
> the loop to push to `main`). P4 (prod health verify) runs only after the merge. The loop keeps
> making progress on later modules meanwhile — their commits accumulate on the branch / PR.

## Module order & status

Order = audit fix-first priority, then ascending module number. `▶` = current pointer.

| Order | Module | Report | Findings | Status | Phase |
|------:|--------|--------|---------:|--------|-------|
| 1 | 01 Auth & Session | [01](reports/01-auth-session.md) | 12 (2 High, 4 Med, 6 Low) | **done (PR #172, merge gated)** | P2✅ → P3 PR open |
| 2 | 07 Knowledge & Indexing | [07](reports/07-knowledge-indexing.md) | 8 (🔴 F-KNOW-01 RCE) | **partial** (01/02/03/05 fixed; 04/06/07/08 open) | P1 |
| 3 | 11 Rules engine | [11](reports/11-rules-engine.md) | 4 (🟠 F-RULE-01 cross-tenant) | pending | — |
| 4 | 15 MCP Server | [15](reports/15-mcp-server.md) | 4 (🟠 F-MCP-01 budget bypass) | pending | — |
| 5 | 03 Connections & Connectors | [03](reports/03-connections-connectors.md) | 7 (read-only invariant) | pending | — |
| 6 | 04 SSH Tunnel & Keys | [04](reports/04-ssh-tunnel-keys.md) | 7 | pending | — |
| 7 | 05 Chat & Orchestration | [05](reports/05-chat-orchestration.md) | 6 | pending | — |
| 8 | 06 SQL Agent & Query Exec | [06](reports/06-sql-agent-query-exec.md) | 5 | pending | — |
| 9 | 08 GitAgent | [08](reports/08-git-agent.md) | 3 | pending | — |
| 10 | 09 Data Validation / DataGate | [09](reports/09-data-validation-investigations-datagate.md) | 6 | pending | — |
| 11 | 10 Insights & Learning memory | [10](reports/10-insights-learning-memory.md) | 5 | pending | — |
| 12 | 12 Visualizations & Dashboards | [12](reports/12-visualizations-dashboards.md) | 3 | pending | — |
| 13 | 13 Schedules, Batch & Worker | [13](reports/13-schedules-batch-worker.md) | 6 | pending | — |
| 14 | 14 Billing & Entitlements | [14](reports/14-billing-entitlements.md) | 4 | pending | — |
| 15 | 16 Notifications, Notes & Feed | [16](reports/16-notifications-notes-feed.md) | 3 | pending | — |
| 16 | 17 LLM routing & Observability | [17](reports/17-llm-routing-observability.md) | 4 | pending | — |
| 17 | 18 Semantic/Graph/Temporal/Exploration | [18](reports/18-semantic-graph-temporal-exploration.md) | 4 | pending | — |
| 18 | 02 Projects, RBAC & Invites | [02](reports/02-projects-rbac-invites.md) | 9 | pending | — |
| 19 | 19 Frontend SPA | [19](reports/19-frontend-spa.md) | 3 | pending | — |

Legend: pending · in progress · done

## Pre-existing uncommitted WIP (do not clobber)

A prior session began module-07 fixes; these live uncommitted in the working tree on this
branch and must be **completed/committed when the loop reaches module 07**, not duplicated:
- `backend/app/knowledge/repo_url.py` (+ `test_repo_url.py`) — F-KNOW-01 repo_url transport allowlist
- `backend/app/core/safety.py` (modified) (+ `test_safety_hardening.py`)
- `backend/app/knowledge/repo_analyzer.py`, `backend/app/api/routes/repos.py` (modified)
- `backend/app/core/background.py` (+ `test_background.py`) — fire-and-forget task GC fix
All loop commits stage files explicitly to avoid sweeping this WIP into unrelated commits.

## Change log (loop)

- **2026-06-24** — Loop initialized. Module 01 P0 done: tracker + spec + plan committed (`8d721b8`).
- **2026-06-24** — Module 01 P1 **Task-group A** done (`a8d3b2a`): F-AUTH-01 SQLite FK
  enforcement (`enable_sqlite_fk`) + new cascade test; fixed 17 orphan-insert tests surfaced by
  enforcement via new conftest seeding helpers. Full integration suite green (491 passed).
- **2026-06-24** — Module 01 P1 **Task-group B** done (`f35ac10`): F-AUTH-02/03 JWT
  `token_version` revocation (`User.token_version` + migration **`f4a5b6c7d8e9`** — spec C2's
  `b2c3d4e5f6a7` collided with an existing revision, so a unique id was used) + `ver` claim
  enforced in `get_current_user` (defaults 0 → no forced logout) + async bcrypt + cookie
  re-issue + audit log in `change_password`. 93 auth tests green; mypy/ruff clean.

  **⚠ Next-iteration risk (group C / C6, F-AUTH-04):** omitting the JWT from the response body
  when `auth_cookie_enabled` will break the test harness (`register_user`/`auth_client` read
  `resp.json()["token"]` for Bearer auth, default `auth_cookie_enabled=True`). Resolve by
  running the suite in Bearer mode (set `AUTH_COOKIE_ENABLED=false` in `tests/conftest.py`) while
  the dedicated cookie tests set it True themselves — verify `test_auth_cookies.py` /
  `test_ws_auth.py` / `test_mcp_asgi_auth.py` configure cookie mode explicitly before flipping.
  Next: group C (C4 timing-equalise, C6 body-token omission, C8 Google CSRF, C11 /refresh limit).
- **2026-06-24** — Module 01 P1 **Task-group C** done (`03dad44`): F-AUTH-04/05/06/09.
  `_auth_response` omits the body JWT under cookie auth; suite runs Bearer-mode by default
  (`AUTH_COOKIE_ENABLED=false` in `tests/conftest.py`), `TestCookieSession` opts into cookie
  auth. Login timing equalised (dummy bcrypt); Google CSRF enforced on cookie presence; `/refresh`
  rate-limited. Fixed 4 `test_deps.py` regressions from the C5 version check (added `token_version`
  to `_fake_user` + a mismatch→401 test). Full suite was 4320 passed/4 failed → now fixed.
  Next: group D (C9 Google-link avatar/provider guard, C10 delete_account hardening:
  on-disk artifact cleanup + explicit MCP-key delete + audit_log).
- **2026-06-24** — Module 01 P1 **Task-group D** done (`ed54b48`): F-AUTH-07 (Google link no
  longer wipes avatar / misreports provider) + F-AUTH-10 (`delete_account` cleans on-disk
  ChromaDB/BM25 artifacts, explicitly revokes MCP keys, writes `auth.delete_account` audit).
- **2026-06-24** — Module 01 P1 **Task-group E** done (`2475114`): F-AUTH-08 (SameSite=none
  requires Secure), F-AUTH-11 (fail-closed prod detection via `_SAFE_ENVIRONMENTS` allow-list),
  F-AUTH-12 (`mcp_token_default_expiry_days=90`, wired into `mcp_key_service.issue`). `.env.example`
  updated. **All 12 findings (F-AUTH-01..12) implemented.** Per-area suites green; ruff/mypy clean.

  **Next iteration = P2/P3/P4:** run full `make check` (ruff format+check, mypy, full unit+integration,
  coverage ≥72%) from repo root; annotate each finding in `reports/01-auth-session.md` as fixed;
  then P3 deploy (merge `fix/security-audit-2026-06-24` → `main`, push) + P4 verify prod health.
  ⚠ Deploy gate: P3 only after P2 fully green. (Module-07 WIP is now committed as `e642c67` and
  already on `origin/main`, so no uncommitted-WIP risk remains.)
- **2026-06-24** — Module 01 **P2 ✅ + P3 PR**. Full `make check` green: ruff format (648) + check,
  mypy (328 files), **4334 backend tests, coverage 74.41%**; frontend **472 tests**, eslint, tsc.
  Discovered + fixed an F-AUTH-04 frontend regression (empty body token broke proactive refresh →
  added `expires_in`; `1343fc3`). Branch pushed; **PR [#172](https://github.com/CheckMyData-AI/checkmydata-ai/pull/172) opened**.
  Direct push to `main` **denied by safety classifier** → prod merge is now a human step (see deploy-gate
  note above). `origin/main` already carries `e642c67` + `8d721b8`.
  Next: module 07 — first confirm what `e642c67` already fixed (repo_url transport allowlist for
  F-KNOW-01) to avoid duplication, then address the remaining module-07 findings.
- **2026-06-24** — Module 07 **partial** (`81e3d75`): confirmed `e642c67` already fixed F-KNOW-01
  (repo_url allowlist) + F-KNOW-02 (host-key TOFU). Added F-KNOW-05 (`validate_git_ref` at API
  boundaries + RepoAnalyzer) and F-KNOW-03 (re-point clone on `repo_url` change). F-KNOW-04/06/07/08
  deferred (rationale in spec + `reports/testing_result.md` §7). Scoped tests + ruff/mypy green.
- **2026-06-24 — LOOP STOPPED (user request).** Finished the in-flight Module-07 fix and wrote the
  consolidated `reports/testing_result.md` (§7 remediation log: 16 findings resolved, all others
  open). No further wakeups scheduled. To resume: re-run `/loop` — next pointer is Module 07
  remainder (F-KNOW-04/06/07/08) then the §5 fix order (DB-session read-only is highest leverage).
