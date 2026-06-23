# Plan — QA Fix Module 01: Auth & Session

Implements [`2026-06-24-qa-fix-01-auth-session-design.md`](../specs/2026-06-24-qa-fix-01-auth-session-design.md).
Contracts (C1–C14) are locked in the spec — this plan is the execution order. TDD throughout:
write the failing test, confirm it fails, implement the minimal fix, confirm green, commit.

Run tests from `backend/`: `.venv/bin/pytest <path> -v`. Conventional commits, one per task
group. Branch: `fix/security-audit-2026-06-24`.

## Task group A — SQLite FK enforcement (F-AUTH-01) · C13

1. **A1 (test, failing):** `tests/integration/test_auth_cascade.py` — register user (granted
   create), create a project + a connection under it, delete the project, assert the connection
   row is absent. Expect **fail** today (cascade no-op on SQLite).
2. **A2 (impl):** add `enable_sqlite_fk(async_engine)` to `app/models/base.py`; call it for the
   app `engine` when `database_url` is sqlite; call it in `tests/integration/conftest.py`
   `engine` fixture before `create_all`.
3. **A3:** confirm A1 passes. **DoD:** cascade test green; `ruff check app/ tests/` clean.
   Commit `fix(auth): enforce SQLite FK so ondelete=CASCADE works in dev/tests (F-AUTH-01)`.

## Task group B — JWT versioning / revocation (F-AUTH-02, F-AUTH-03) · C1,C2,C3,C5,C7

4. **B1 (impl, model+migration):** add `User.token_version` (C1); create migration
   `b2c3d4e5f6a7` (C2); run `PYTHONPATH=. .venv/bin/alembic upgrade head` against a scratch
   sqlite to confirm it applies.
5. **B2 (test, failing):** in `test_auth_extended.py`, change password then reuse the *old*
   Bearer token on `/api/auth/me` → expect 401. Also unit-assert `create_token` payload has
   `ver` (`test_auth_service.py`).
6. **B3 (impl):** `create_token` gains `token_version` + `ver` claim (C3); `get_current_user`
   rejects mismatched `ver` (C5); `change_password` → async bcrypt, bump `token_version`,
   re-issue cookie, audit log (C7). Update all `create_token` callers to pass
   `user.token_version`.
7. **B4:** confirm B2 green; confirm pre-existing auth tests still pass (no forced logout —
   `ver` defaults to 0). Commit `fix(auth): JWT token_version revocation + async bcrypt on change-password (F-AUTH-02/03)`.

## Task group C — Response/CSRF/login hardening (F-AUTH-04/05/06/09) · C4,C6,C8,C11

8. **C1t (test, failing):** with cookie auth on, `register`/`login` body `token == ""`
   (F-AUTH-04); `/refresh` 429 past limit (F-AUTH-09); unknown-email `authenticate` returns
   None but calls verify (F-AUTH-05, assert via spy/mock on `verify_password_async`).
9. **C2i (impl):** `_auth_response` helper + `token=""` under cookie auth (C6); `/refresh`
   `@limiter.limit("30/minute")` + `request` param (C11); dummy-hash timing equalisation (C4);
   Google cookie-based CSRF enforcement (C8).
10. **C3v:** confirm green. Commit `fix(auth): omit JWT from body under cookie auth, equalise login timing, rate-limit refresh, enforce Google CSRF (F-AUTH-04/05/06/09)`.

## Task group D — Account/profile correctness (F-AUTH-07, F-AUTH-10) · C9,C10

11. **D1 (test, failing):** unit — Google email-link with no `picture` keeps existing avatar
    and does not flip a password user's provider (C9). Integration — `delete_account` removes
    MCP keys and emits `auth.delete_account` audit (capture via `caplog` on the `audit` logger).
12. **D2 (impl):** C9 link guard; C10 delete_account (enumerate projects/connections →
    best-effort `indexing_artifacts` cleanup; explicit MCP-key delete; audit log). Read
    `app/services/indexing_artifacts.py` for the exact cleanup signatures first.
13. **D3v:** confirm green. Commit `fix(auth): defensive account deletion (secret/disk cleanup + audit) and non-destructive Google linking (F-AUTH-07/10)`.

## Task group E — Config fail-closed (F-AUTH-08, F-AUTH-11, F-AUTH-12) · C12,C14

14. **E1 (test, failing):** `test_config.py` — `Settings(auth_cookie_samesite="none", auth_cookie_secure=False)` raises (F-AUTH-08); `Settings(environment="staging", jwt_secret="change-me-in-production")` raises (F-AUTH-11 fail-closed); MCP create with `expires_in_days=None` sets `expires_at ≈ now + 90d` (F-AUTH-12).
15. **E2 (impl):** SameSite/secure validator; `_SAFE_ENVIRONMENTS` inversion; `mcp_token_default_expiry_days=90` + wire into `mcp_key_service` (C14).
16. **E3v:** confirm green; run full unit+config suites — ensure the env inversion didn't break
    any `Settings(...)` instantiation in tests. Commit `fix(config): fail-closed prod secret guard, SameSite=None requires Secure, bounded MCP token expiry (F-AUTH-08/11/12)`.

## Task group F — Verify (P2) + report annotation

17. **F1:** annotate each finding in `docs/qa-audit/reports/01-auth-session.md` with
    `**Status:** ✅ fixed (<commit>)`.
18. **F2:** `make check` from repo root (ruff format check, ruff, mypy, full backend tests,
    coverage ≥ 72%). Fix any fallout. Frontend untouched in this module → skip frontend gate.
19. **F3:** commit `docs(qa-audit): mark Module 01 findings fixed`. Update
    `FIX_LOOP_TRACKER.md` (module 01 → done, pointer → module 07).

## Then (loop): P3 deploy + P4 verify

- Merge `fix/security-audit-2026-06-24` → `main`, push (Heroku auto-deploy via CI).
- Verify `/api/health`, scan Heroku logs for new errors/regressions. Mark done; next module.

## Verification checklist (DoD for the module)

- [ ] All A–E tests green; failing-first confirmed for each.
- [ ] `make check` green, coverage ≥ 72%.
- [ ] No forced logout for existing sessions (ver-default backward-compat verified).
- [ ] Report findings annotated `fixed`; tracker advanced.
