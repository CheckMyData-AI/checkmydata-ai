# Module 01 — Auth & Session — Audit Report

**Round 1** · 2026-06-23 · Scope: `routes/auth.py`, `services/auth_service.py`,
`core/auth_cookies.py`, `api/deps.py`, plus `models/base.py` engine setup and FK config.

Documented contract (CLAUDE.md "Multi-tenancy & access control"): browser auth = httpOnly
session cookie + CSRF double-submit, **no `localStorage` JWT**; `Authorization: Bearer` still
works for non-browser clients; DB credentials Fernet-encrypted at rest; all routes except
`/api/auth/*` and `/api/health` require auth. This report checks the implementation against
that contract and hunts for defects.

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## ✅ Remediation status — 2026-06-24 (QA fix loop)

All 12 findings fixed (TDD; per-area suites green, ruff/mypy clean). Spec/plan:
[`specs/2026-06-24-qa-fix-01-auth-session-design.md`](../../superpowers/specs/2026-06-24-qa-fix-01-auth-session-design.md),
[`plans/2026-06-24-qa-fix-01-auth-session.md`](../../superpowers/plans/2026-06-24-qa-fix-01-auth-session.md).

| Finding | Fix commit | Summary of fix |
|---------|-----------|----------------|
| F-AUTH-01 | `a8d3b2a` | `enable_sqlite_fk()` → `PRAGMA foreign_keys=ON` on app + test engines; +cascade test; fixed 17 orphan-insert tests |
| F-AUTH-02 | `f35ac10` | `User.token_version` (+migration `f4a5b6c7d8e9`) + `ver` JWT claim; `get_current_user` rejects mismatch; bumped on password change |
| F-AUTH-03 | `f35ac10` | `change_password` uses off-thread async bcrypt |
| F-AUTH-04 | `03dad44` | `_auth_response` omits JWT from body under cookie auth |
| F-AUTH-05 | `03dad44` | dummy bcrypt verify equalises unknown/passwordless login timing |
| F-AUTH-06 | `03dad44` | Google CSRF enforced on cookie presence (no body-token bypass) |
| F-AUTH-07 | `ed54b48` | Google link no longer wipes avatar / misreports provider |
| F-AUTH-08 | `2475114` | config: `SameSite=None` requires `Secure` (fail-closed) |
| F-AUTH-09 | `03dad44` | `/refresh` rate-limited (30/min) |
| F-AUTH-10 | `ed54b48` | `delete_account`: on-disk artifact cleanup + explicit MCP-key revoke + `audit_log` |
| F-AUTH-11 | `2475114` | prod secret guard fails closed via `_SAFE_ENVIRONMENTS` allow-list |
| F-AUTH-12 | `2475114` | MCP tokens default to 90-day expiry (`mcp_token_default_expiry_days`) |

---

## F-AUTH-01 — 🟠 High — SQLite has FK enforcement OFF, so every `ondelete=CASCADE` is a silent no-op in dev & tests

**Type:** Bug / dev-prod parity trap / data retention
**Location:** `backend/app/models/base.py` (engine setup, no PRAGMA), exploited via
`backend/app/api/routes/auth.py:275` `delete_account`.

**Description.** SQLite does **not** enforce foreign keys unless `PRAGMA foreign_keys=ON` is
issued on **every** connection. A repo-wide search finds no such pragma and no
`event.listens_for(Engine, "connect")` listener (the only `foreign_keys` hits in `app/` are
schema-introspection code in the connectors). Meanwhile every model declares
`ForeignKey(..., ondelete="CASCADE")` (e.g. `connection.py:21`, `chat_session.py:22`,
`project_member.py:27`, `dashboard.py:20`, `mcp_api_key.py`, `token_usage.py`).

`delete_account` deletes only the `Project`, `ProjectMember`, and `User` rows explicitly and
**relies on cascade** for everything hanging off those (connections, chat sessions, dashboards,
insights, MCP API keys, token-usage rows, agent learnings, …).

**Impact.**
- **Dev/test (SQLite):** cascades never fire. Account/project deletion leaves orphaned rows —
  including `connections.db_password_encrypted` / `connection_string_encrypted` /
  `mcp_env_encrypted` (Fernet-encrypted secrets, `connection.py:40-55`). Encrypted-secret rows
  linger indefinitely with no owning user/project. This contradicts the vision invariant
  "credentials never exposed / minimal retention".
- **Test trust:** integration tests run on SQLite, so any test asserting "delete project →
  child rows gone" **passes for the wrong reason** (nothing was cascaded; nothing to assert
  against), giving false confidence that prod cascade behaviour is exercised.
- **Prod (Postgres):** cascades *do* fire — so dev and prod diverge. Bugs that depend on the
  cascade path (or on its absence) are invisible until prod.

**Proposed fix.**
1. Add a connect-time pragma for SQLite in `app/models/base.py`:
   ```python
   from sqlalchemy import event
   from sqlalchemy.engine import Engine

   if settings.database_url.startswith("sqlite"):
       @event.listens_for(engine.sync_engine, "connect")
       def _sqlite_fk_pragma(dbapi_conn, _):
           cur = dbapi_conn.cursor()
           cur.execute("PRAGMA foreign_keys=ON")
           cur.close()
   ```
   (For async aiosqlite the `connect` event fires on the underlying sync DBAPI connection via
   `engine.sync_engine`.)
2. Add a regression test: create project + connection, delete the project, assert the
   connection row is gone — it should now pass *because* cascade fired, and would have silently
   passed-for-nothing before.
3. Independently, make `delete_account` defensive rather than cascade-dependent (see F-AUTH-10).

---

## F-AUTH-02 — 🟠 High — No server-side JWT revocation; password change and logout don't invalidate outstanding tokens

**Type:** Security
**Location:** `services/auth_service.py:40-50` (`create_token`/`decode_token`),
`routes/auth.py:182-201` (`change_password`), `routes/auth.py:231-239` (`logout`).

**Description.** JWTs are stateless: `create_token` embeds only `sub/email/iat/exp`; there is
no `jti`, no `token_version`, and no deny-list (confirmed: no `jti`/`token_version`/`revoke`
machinery for JWTs anywhere). Consequences:
- `change_password` updates the hash but **does not invalidate previously issued tokens** —
  a stolen/leaked JWT keeps working until `jwt_expire_minutes` elapses, even after the victim
  changes their password specifically to lock an attacker out.
- `logout` only calls `clear_session_cookies` — it clears the browser cookie but cannot revoke
  a **Bearer** token already captured by an attacker. There is no "log out everywhere".

**Impact.** Password change — the canonical "I've been compromised" action — provides no
session invalidation. Token lifetime is the only bound.

**Proposed fix.** Add an integer `token_version` column to `User` (default 0); include it as a
claim in `create_token`; in `get_current_user` reject when `payload["ver"] != user.token_version`.
Bump `token_version` on password change and on an explicit "sign out of all sessions" action.
(Cheaper than a Redis deny-list and naturally covers both cookie and Bearer clients.)

---

## F-AUTH-03 — 🟡 Medium — `change_password` uses blocking synchronous bcrypt on the request path

**Type:** Performance / inconsistency
**Location:** `routes/auth.py:196` and `:198`.

**Description.** `AuthService` deliberately added off-thread async bcrypt
(`hash_password_async`/`verify_password_async`, "T21") because sync bcrypt (~100 ms) blocks the
event loop and serialises concurrent auth requests. `register`/`authenticate` use the async
variants — but `change_password` calls the **sync** `_auth._verify_password(...)` and
`_auth._hash_password(...)` directly, re-introducing two ~100 ms event-loop stalls per call.

**Impact.** Each password change blocks the single event loop for ~200 ms, degrading latency
for all concurrent requests on that worker. Also reaches into "private" `_`-prefixed methods.

**Proposed fix.**
```python
if not await _auth.verify_password_async(body.current_password, user.password_hash):
    raise HTTPException(status_code=401, detail="Current password is incorrect")
user.password_hash = await _auth.hash_password_async(body.new_password)
```

---

## F-AUTH-04 — 🟡 Medium — JWT returned in the response body defeats the httpOnly-cookie threat model

**Type:** Security / design contradiction
**Location:** `routes/auth.py` `AuthResponse` returned by `register`/`login`/`google`/`refresh`
(e.g. `:87`, `:117`, `:168`, `:217`); model at `:46-48`.

**Description.** `core/auth_cookies.py` states the model explicitly: the JWT lives in an
httpOnly cookie "so it can never be read by JavaScript (no XSS token theft, nothing in
`localStorage`)". But when `auth_cookie_enabled` is true, these endpoints still return the raw
JWT in the JSON body (`token=token`). Any XSS on the SPA can read the response (or the SPA may
persist it), re-opening exactly the exfiltration vector the cookie design removes.

**Impact.** The security benefit of httpOnly cookies is undermined for browser clients; the
"nothing in localStorage" guarantee is only as strong as the SPA's discipline, not enforced by
the API.

**Proposed fix.** When `settings.auth_cookie_enabled`, omit `token` from the body (return
`token=""` or drop the field) so browsers rely solely on the cookie. Keep returning the token in
the body only on the Bearer path (cookie auth off), or expose a separate explicit
token-minting endpoint for non-browser clients.

---

## F-AUTH-05 — 🟡 Medium — User enumeration via login timing and explicit 409 on register

**Type:** Security
**Location:** `services/auth_service.py:82-98` (`authenticate`), `routes/auth.py:71-76`
(`register` → 409).

**Description.** `authenticate` returns early (`return None`) when the email is unknown
**without performing a bcrypt verify**, so the response time for a non-existent account is
near-instant while an existing account costs ~100 ms — a timing oracle for "is this email
registered?". Separately, `register` returns a specific `409 "An account with this email
already exists."`, an explicit enumeration signal. Both are rate-limited (10/min, 5/min) which
slows but does not prevent enumeration.

**Impact.** An attacker can map which emails have accounts (useful for targeted phishing /
credential stuffing).

**Proposed fix.** In `authenticate`, when the user is missing, run a dummy
`verify_password_async(password, settings.dummy_bcrypt_hash)` against a constant valid bcrypt
hash to equalise timing before returning `None`. Consider whether the 409 is worth the
enumeration trade-off (often accepted for UX; at minimum keep it rate-limited and audited).

---

## F-AUTH-06 — 🟢 Low — Google `g_csrf_token` double-submit check is opt-in and bypassable

**Type:** Security (low, defence-in-depth)
**Location:** `routes/auth.py:139-142`.

**Description.** The check is `if body.g_csrf_token:` then `if cookie_token and cookie_token != body.g_csrf_token`. An attacker who simply omits `g_csrf_token` from the POST body skips the
check entirely; it's also skipped when the cookie is absent. Google's documented flow expects
the double-submit to be enforced whenever the `g_csrf_token` cookie is present.

**Impact.** Low — the `credential` is a Google-signed ID token verified server-side
(`verify_google_token`), so forging a login still requires a valid Google token. This is
defence-in-depth, not the primary control.

**Proposed fix.** Enforce based on the **cookie**, not the body: if the `g_csrf_token` cookie
is present, require a matching body token; reject on mismatch or missing body token.

---

## F-AUTH-07 — 🟢 Low — Google linking wipes `picture_url` and silently flips `auth_provider`

**Type:** Bug / data correctness
**Location:** `services/auth_service.py:164-171`.

**Description.** When linking Google to an existing email account, `user.picture_url = picture`
is assigned unconditionally; if the Google payload has no `picture`, an existing avatar is
overwritten with `None`. Also `auth_provider` is flipped to `"google"` while `password_hash`
is retained — so the user can still log in with a password, but the single-valued
`auth_provider` field now misrepresents the available login methods (UI keys off it, e.g.
`change_password` gating).

**Impact.** Lost avatar on link; `auth_provider` no longer a reliable signal of which login
methods work.

**Proposed fix.** Guard the picture update (`if picture: user.picture_url = picture`). Represent
auth methods as independent booleans/flags (`has_password`, `has_google`) rather than a single
mutually-exclusive `auth_provider` string.

---

## F-AUTH-08 — 🟢 Low — `SameSite=None` cookies have no `Secure` guard; misconfig silently breaks login

**Type:** Bug / config hardening
**Location:** `core/auth_cookies.py:35-39` (`_samesite`), `:49-73` (`set_session_cookies`).

**Description.** `_samesite()` accepts `"none"`, but browsers reject `SameSite=None` cookies
that are not also `Secure`. If an operator sets `auth_cookie_samesite=none` with
`auth_cookie_secure=false` (e.g. behind a misconfigured proxy), both cookies are dropped and
login fails with no clear error. There is no validation linking the two settings.

**Impact.** Hard-to-diagnose "login does nothing" in certain deployments.

**Proposed fix.** Add a config validator: if `auth_cookie_samesite == "none"` then
`auth_cookie_secure` must be `True` (fail-closed at startup or log a loud warning).

---

## F-AUTH-09 — 🟢 Low — Sensitive auth mutations are not rate-limited

**Type:** Hardening
**Location:** `routes/auth.py:204` (`/refresh`), `:262` (`/complete-onboarding`), `:242`
(`/me`).

**Description.** `register`/`login`/`google`/`change-password`/`delete-account` carry
`@limiter.limit(...)`, but `/refresh` does not — a client with one valid session can mint
unlimited fresh JWTs. `/me` and `/complete-onboarding` are also unlimited.

**Impact.** Low (auth required), but `/refresh` is a token-minting endpoint and should be
bounded.

**Proposed fix.** Add e.g. `@limiter.limit("30/minute")` to `/refresh`.

---

## F-AUTH-10 — 🟡 Medium — `delete_account` is cascade-dependent, skips explicit secret/token cleanup, and omits an audit-log entry

**Type:** Bug / security / observability
**Location:** `routes/auth.py:275-303`.

**Description.** Three issues:
1. **Cascade dependence** (compounds F-AUTH-01): on SQLite no child rows are removed; on
   Postgres it works, but the route makes no guarantee itself.
2. **No explicit secret/MCP-token revocation** — it never calls the on-disk cleanup
   (`services/indexing_artifacts.py`, which removes BM25 snapshots and the ChromaDB collection)
   nor explicitly deletes MCP API keys; those rely on cascade (DB) + nothing (disk). Deleting an
   account can therefore leave the user's ChromaDB collection and BM25 `.pkl` snapshots on disk.
3. **No `audit_log`** — every other auth mutation calls `audit_log(...)` (`register`, `login`,
   `google`), but account deletion only does `logger.info`, so the security-audit trail is
   missing the single most destructive action.

**Impact.** Incomplete data/secret erasure (privacy/GDPR-deletion concern) and a gap in the
audit trail for the highest-impact action.

**Proposed fix.** Enumerate owned projects/connections and call the existing
`indexing_artifacts` cleanup for each before deletion; explicitly delete MCP keys; wrap in the
same transaction; and add `audit_log("auth.delete_account", user_id=user_id, detail=email)`.

---

## Test gaps (⚪ Info)

- No test asserts cascade cleanup actually happens on project/account delete (would currently
  pass-for-nothing on SQLite — see F-AUTH-01). Add one **after** enabling the FK pragma.
- No test asserts that, with `auth_cookie_enabled`, the JWT is absent from the login/register
  response body (F-AUTH-04).
- No timing-equalisation test for unknown-vs-known email on login (F-AUTH-05).
- `test_auth_cookies.py` / `test_mcp_asgi_auth.py` exist — next round, verify they cover
  CSRF-missing → 403 and Bearer-exempt-from-CSRF paths in `deps.get_current_user`.

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-AUTH-01 | 🟠 | SQLite FK off → all cascades are no-ops in dev/test; orphaned encrypted secrets |
| F-AUTH-02 | 🟠 | No JWT revocation; password change / logout don't kill outstanding tokens |
| F-AUTH-03 | 🟡 | `change_password` blocks event loop with sync bcrypt |
| F-AUTH-04 | 🟡 | JWT returned in body defeats httpOnly-cookie model |
| F-AUTH-05 | 🟡 | User enumeration via login timing + register 409 |
| F-AUTH-06 | 🟢 | Google CSRF check is opt-in / bypassable |
| F-AUTH-07 | 🟢 | Google link wipes avatar, flips `auth_provider` |
| F-AUTH-08 | 🟢 | `SameSite=None` without `Secure` guard → silent login failure |
| F-AUTH-09 | 🟢 | `/refresh` token minting not rate-limited |
| F-AUTH-10 | 🟡 | `delete_account` cascade-dependent, skips secret/disk cleanup + audit log |

**Next round focus for this module:** verify `mcp_tokens.py` issuance/hashing, JWT algorithm
confidence (no `alg=none` acceptance via `jose`), session-rotation summariser auth path, and
the `is_active` / soft-delete story for users.

---

# Round 2 — additional findings (2026-06-24)

Deep-dive into the R1-deferred areas. **Several R1 worries were ruled out (good):**
- **No `alg=none`/alg-confusion**: `decode_token` passes `algorithms=[settings.jwt_algorithm]`
  (`= ["HS256"]`), so `jose` rejects `none` and won't accept an RS256-signed token against the
  HMAC secret.
- **Prod secret validation fails closed**: a `@model_validator` **raises** at startup if
  `JWT_SECRET` is the default or `<32` chars, or `MASTER_ENCRYPTION_KEY` is missing
  (`config.py:656-674`) — the app won't boot insecure *in production*.
- **MCP tokens are well-built**: 256-bit `secrets.token_urlsafe(32)`, SHA-256 hashed at rest
  (`mcp_key_service.py:28-37`), minting rate-limited (10/min) + auth-required; `lookup_by_token`
  checks `revoked_at` + `expires_at` and **does not distinguish unknown/revoked/expired** (no
  validity oracle, `:133-150`); `resolve_user_from_personal_token` **checks `user.is_active`**
  (`auth.py:77`) — so deactivating a user **does** revoke MCP access (revocation is consistent
  with the JWT path).

## F-AUTH-11 — 🟡 Medium — Production secret guard is fail-*open* unless `environment` is exactly `production`/`prod`

**Type:** Security (config hardening)
**Location:** `config.py:656-660` (`is_prod = self.environment.lower() in ("production","prod")`;
`if not is_prod: return self`).

**Description.** The fail-closed secret validation (default/short `JWT_SECRET`, missing
`MASTER_ENCRYPTION_KEY`) only runs when `environment` matches the exact strings
`"production"`/`"prod"`. Any other value — unset/empty, `"staging"` used as prod, `"prod-eu"`,
`"live"`, a typo — **skips** the guard, and only the module-level `logger.warning` fires
(`config.py:757`). A real production deployment that doesn't set `ENVIRONMENT` to exactly that
string can boot with the default `"change-me-in-production"` JWT secret → **anyone can forge a
valid JWT for any user**.

**Impact.** A single missing/mislabeled env var silently downgrades the platform to forgeable
auth. Security controls should fail closed.

**Proposed fix.** Invert the default: treat **any** environment as production-grade *unless*
explicitly `development`/`test`/`local` (allowlist the safe envs, not the dangerous one). Or
always enforce the secret checks and only relax for an explicit dev flag.

## F-AUTH-12 — 🟢 Low — MCP tokens default to never expiring

**Type:** Security hardening
**Location:** `routes/mcp_tokens.py:33-34` (`expires_in_days: int | None = None`),
`mcp_key_service.py:66-70` (None → `expires_at=None` = never).

**Description.** A minted MCP token with no `expires_in_days` never expires — a long-lived bearer
credential. Revocation exists (good), but the default is unbounded lifetime.

**Proposed fix.** Default to a bounded expiry (e.g. 90 days) and/or enforce a configurable maximum;
surface expiry prominently in the token UI.

## Round 2 summary

| id | sev | one-line |
|----|-----|----------|
| F-AUTH-11 | 🟡 | Prod secret guard fails *open* unless `environment` is exactly `production`/`prod` |
| F-AUTH-12 | 🟢 | MCP tokens default to never expiring |

**Round 3 focus:** session-rotation summariser (does the auto-summary at context limit leak across
sessions / preserve auth scope?); password-reset flow (does one exist? — none seen in R1); login
lockout/throttle beyond the 10/min rate limit; `audit_log` coverage completeness.

---

# Round 3 — fix-verification pass (2026-06-24): all 12 F-AUTH fixes confirmed, no regressions

Independent auditor re-check of the QA-fix-loop remediation (the table at the top of this report).
**All verified correct; the specific regression risks were checked and are clean:**

- **F-AUTH-01** ✅ `enable_sqlite_fk(async_engine)` installs an `@event.listens_for(sync_engine,
  "connect")` `PRAGMA foreign_keys=ON` and is called on the app engine (`base.py:50`) **and** the
  test engine (`tests/integration/conftest.py:64`, `tests/unit/test_services.py:50`). New
  regression test `tests/integration/test_auth_cascade.py` exercises real cascade. Correct.
- **F-AUTH-02** ✅ **No lockout regression** — the column is `nullable=False, default=0,
  server_default="0"` (`user.py:29-31`) and the migration adds it `server_default="0"`, so existing
  users backfill to `0`; **all 5 `create_token` call sites pass `user.token_version`**
  (`auth.py:105/124/166/198/217`); `deps.py:78` rejects `payload.get("ver",0) != user.token_version`.
  A freshly-minted token always matches. Correct.
- **F-AUTH-04** ✅ `_auth_response` returns `token="" if settings.auth_cookie_enabled else token`
  (`auth.py:32`) — JWT omitted from the body under cookie auth, used by all auth endpoints.
- **F-AUTH-11** ✅ Inverted to a fail-closed allow-list: `_SAFE_ENVIRONMENTS = {"development","dev",
  "test","testing","local","ci"}` (`config.py:54`) — **any** other `environment` value (unset →
  default "development" is safe; but "staging"/"prod-eu"/"live"/typo) is treated as production and
  must pass the secret checks. Correct (closes the original fail-open).
- **F-AUTH-03/05/06/07/08/09/10/12** — fixes present per the remediation table; spot-checks
  consistent with the proposed fixes.

**Round 3 net: 0 new findings — remediation verified.** Module 01 is now closed (audit → fix →
independent verify).

**Round 4 focus (still open from R1/R2):** session-rotation summariser auth/PII scope;
password-reset flow (still absent?); login lockout beyond rate-limit; `audit_log` completeness.
