# Module 19 — Frontend SPA — Audit Report

**Round 1** · 2026-06-24 · Scope: XSS surface (`dangerouslySetInnerHTML`, markdown render),
auth/token storage, CSRF client, link safety. (Per-component a11y/design-token + state-management
deep review deferred to R2.)

**The frontend security posture is strong** — this pass focused on the highest-risk web vectors and
found them well-handled.

**Positive notes (verified):**
- **Chat/agent output is XSS-safe**: rendered with `react-markdown` v9 + `remark-gfm` and **no
  `rehype-raw`** (`ChatMessage.tsx:5-8,407`) — embedded HTML/`<script>` in agent or DB-derived
  content is escaped, not executed. **This mitigates the F-VIZ-02 stored-XSS concern** for the
  markdown path.
- **Markdown links are allowlisted**: the custom `a` component only permits `http(s)://`
  (`safeHref = /^https?:\/\//i.test(href) ? href : undefined`) and sets
  `rel="noopener noreferrer"` (`ChatMessage.tsx:42-45`) — blocks `javascript:`/`data:` URLs.
- **No JWT in `localStorage`/`sessionStorage`**: auth rides exclusively on the httpOnly session
  cookie (`_client.ts:87`) — consistent with the cookie-auth model (the backend still returns the
  token in the body — F-AUTH-04 — but the SPA doesn't persist it).
- **CSRF double-submit is correct**: `_client.ts` reads the non-httpOnly `cmd_csrf` cookie and
  echoes `X-CSRF-Token` on state-changing requests, with `credentials: "include"` (`:20-39,82-87`).
- All six `dangerouslySetInnerHTML` uses are **static** JSON-LD (schema.org) or the theme-init
  script — no user/DB data flows into them.

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-FE-01 — 🟡 Medium — Failing frontend tests (lost regression signal)

**Type:** Test health / CI
**Location:** frontend Vitest suite (per observation 21130: "3 tests failing, 468/471" during the
dashboard-rebuild merges; obs 21109: "HomeAsk test file failed to load").

**Description.** During the recent dashboard/activation-funnel work, the frontend test suite had
failing/non-loading tests. The project requires green CI, and failing tests mean regressions in the
affected components (chat send flow, HomeAsk pending-question wiring) aren't being caught.

**Impact.** Reduced regression protection on actively-changing chat/onboarding components.

**Proposed fix.** Run `make test-frontend` (`cd frontend && npx vitest run`) to get the current
status and fix the failures (or remove/repair the non-loading test file). Verify the count is back
to all-green; gate it in CI. *(Flagged for verification — the observation may be partially resolved
since.)*

---

## F-FE-02 — 🟢 Low — Verify dashboard card text is rendered as React children (not innerHTML)

**Type:** Security (defense-in-depth, cross-ref F-VIZ-02)
**Location:** dashboard viewer components (`/dashboard/[id]`), `cards_json` render path.

**Description.** The chat markdown path is confirmed safe. The dashboard card renderer should be
confirmed to render card titles/labels as React children (escaped) and chart data via chart.js
(canvas, not DOM), with **no** `dangerouslySetInnerHTML` for any `cards_json`-derived field. The
grep found no `dangerouslySetInnerHTML` in chat/dashboard components (good), but the specific
card-title/description render wasn't read line-by-line this pass.

**Proposed fix.** Confirm in R2; if any card field is ever rendered as HTML, sanitize it. The
durable fix is backend `cards_json` schema validation (F-VIZ-03).

---

## F-FE-03 — 🟢 Low — Accessibility / design-token conformance not audited this pass

**Type:** Quality (conventions)
**Location:** component tree broadly.

**Description.** CLAUDE.md mandates semantic design tokens (no raw Tailwind palette), `aria-label` +
`<Tooltip>` on icon buttons, modal focus traps + Escape-to-close, and ≥44px touch targets. These
weren't audited per-component in this security-focused pass.

**Proposed fix.** Dedicated a11y + design-token lint sweep in R2 (e.g. eslint-plugin-jsx-a11y +
a grep for raw palette classes).

---

## Test gaps (⚪ Info)

- Fix the failing/non-loading frontend tests (F-FE-01) before adding new ones.
- Add a test asserting agent markdown containing `<script>` / `[x](javascript:...)` renders inert
  (locks in the current safe behaviour).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-FE-01 | 🟡 | Failing frontend Vitest tests (per obs 21130) — lost regression signal |
| F-FE-02 | 🟢 | Confirm dashboard card text renders as escaped React children (cross-ref F-VIZ-02) |
| F-FE-03 | 🟢 | a11y / design-token conformance not audited this pass |

**Cross-ref:** F-VIZ-02 (stored XSS via `cards_json`) is **downgraded** — the frontend render is
XSS-safe (react-markdown no-raw-html, http(s)-only links, no innerHTML for dynamic content). The
residual is backend-side `cards_json` validation (F-VIZ-03).

**Next-round focus:** Zustand store correctness (stale-closure guards in `app-store`/ChatPanel —
some fixed per obs 20933; audit the rest); SSE/WS reconnect + in-flight stream abort on session
switch; `reasoning-store` trace handling; PWA/offline behaviour; `prefers-reduced-motion`
`MotionConfig` coverage; error-boundary coverage on the gated SPA.
