# Security gap sweep — 2026-09-11

The cross-cutting sweep the 2026-09-09 audit could not finish. Its hunter was killed by an
account spend limit, and the report recorded the ground as **not covered**, which is why
row **P0-7** exists at all: not a fix with a known defect behind it, but a question nobody
had answered.

**The answer is that the ground is covered.** Seven areas checked, no new hole. The two real
gaps in this territory were already on the board before this sweep ran and stay where they
are: `AUTH-05` and `API-05`, both P2.

A sweep that finds nothing is worth what not sweeping is worth unless it leaves something
behind, so five of the checks are now `backend/tests/unit/test_security_sweep_invariants.py`
and run on every commit. The rest are recorded here with what was read.

## What was checked, and what it showed

| Area | Result | Evidence |
|---|---|---|
| **Security headers** | sound | `main.py:428-446` — `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, HSTS emitted only over HTTPS with `max-age`, `includeSubDomains` and `preload` each behind their own setting |
| **CSP** | sound | `config.py:971-984` — `default-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`. `'unsafe-inline'` appears in **`style-src` only**, which is what a Tailwind build needs; `script-src` carries none. Report-only mode is a separate flag, so a tightening can be observed before it is enforced |
| **Cookie flags** | sound, and the trap is already closed | `auth_cookies.py:50-70` — session cookie `httpOnly`, the CSRF cookie deliberately readable for the double-submit, both `secure` by default. The failure mode worth hunting here is `SameSite=None` without `Secure`, which browsers drop **silently** — a login that fails with no error anywhere. `config.py:1351` already refuses that combination at boot |
| **CSRF** | sound | `deps.py:59-62` — enforced on every method outside `SAFE_METHODS` when the caller authenticated by cookie, and compared with `hmac.compare_digest`. A `==` there leaks the token one character at a time |
| **Secrets hygiene** | sound, measured | An AST scan of every `logger.*` call in `app/` for arguments whose names suggest a secret returned **11 candidates and 0 secrets**: token *counts*, token *ids*, a credential fingerprint, a credential name, `_redact_token(api_key)`, and a GA4 service-account address. The scan is now a test with each of the eleven quoted exactly, so a twelfth has to be looked at rather than absorbed |
| **Route authentication** | sound, measured | Every HTTP and WebSocket handler in `app/api/routes/` was checked for a session dependency. **11 have none**, and each is authenticated by something else or public by design: the six auth endpoints, `logout`, the public price list, the Stripe webhook (signature), the chat WebSocket (single-use ticket) and the repo webhook (shared secret). Now an allowlist in the test, each entry carrying **which credential stands in for the session** |
| **Webhook replay** | sound | Stripe's `construct_event` verifies the signature with its own timestamp tolerance, and `handle_event` claims the event id in a ledger row before doing anything. P0-6 extended that claim to the *money* — the refund, the invoice, the session — so a redelivery under a new event id cannot double-apply either |
| **WS ticket lifecycle** | sound | `core/ws_tickets.py` — single-use, TTL-bounded, bound to `(user, project, connection)`, Redis-backed when a shared client exists so a ticket minted on one dyno is spent on another |
| **Demo path** | sound | `routes/demo.py` — authenticated, rate-limited, and it **reuses** an existing demo project rather than creating another (F-EXP-03), so repetition costs nothing |
| **Key-rotation edges** | sound | `services/encryption.py:94-107` — `encrypt()` uses the primary key **only**; `decrypt()` falls back through retired keys in order. A retired key that could write would make the rotation unfinishable, so that asymmetry is now a test |

## What this sweep did not do

- **It did not re-audit tenancy.** Project scoping was the subject of its own pass
  (P1 1.10–1.12) and of P0-3 in this programme; repeating it here would have been a second
  reading of ground already measured rather than the uncovered ground this row names.
- **It did not test the deployed headers against the live site.** Every check above reads
  the code that emits them. A response-level check belongs with the deploy verification,
  not here, and is worth its own row if anybody wants the live surface asserted.
- **It found no reason to move `AUTH-05` or `API-05`.** Both are real; both were already
  ranked P2 by the audit that found them, and this sweep produced no new evidence that
  changes that ranking.
