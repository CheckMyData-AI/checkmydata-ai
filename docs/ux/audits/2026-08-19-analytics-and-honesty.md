# UX Audit — 2026-08-19 — SCN-113…121

Scope: the nine scenarios that shipped in `[1.16.0]` and were never audited. Each
carried `Status: draft` and `Last audit: —` for a month while its code was in
production — the drift the scenario-first rule exists to prevent, since the base
is the source of truth only while it is kept current. Finding id in the full
audit: `AUD-0819-15` (`docs/audits/2026-08-19-full-stack-audit.md`).

**Totals: PASS 9 / PARTIAL 0 / FAIL 0.** Every claim below was checked against
code, not against the changelog.

## analytics-sources

### SCN-113 — Add a Google Analytics 4 connection — PASS
- The whole GA4 field set exists and is separate from the DB fields:
  `components/connections/ConnectionSelector.tsx:57-60` (`property_id`,
  `backfill_days`, `collection_hour`, `collection_enabled` defaults), `:68-71`
  (populated from `source_config` on edit), `:479-502` (submit builds
  `property_ids` + `backfill_days` and carries `collection_enabled`).
- `backfill_days` is clamped rather than trusted — `safeInt(…, 30, 1, 3650)` at
  `:500`, so a pasted `0` or `99999` cannot reach the collector, which validates
  the same bound at boot.

### SCN-114 — Add / delete a vendor credential — PASS
- Write-only secret, and the panel says so in the interface, not only in a
  comment: `components/settings/VendorCredentialsPanel.tsx:142-146` (textarea with
  `aria-label` from `vendorProviderSecretLabel`), `:155` — "Stored encrypted and
  never shown again — only its fingerprint and the …".
- Labels on every input (`:116`, `:131`), provider badge at `:322-324`, and the
  destructive path goes through the shared confirm (`:5` imports `confirmAction`),
  so it matches the SSH-keys idiom the scenario says it mirrors.

### SCN-115 — Analytics collection status — PASS
- The four states are distinct in copy as well as colour:
  `components/connections/ConnectionHealth.tsx:188-204`. `never_collected` reads
  "not collected" with its own muted tint, and `partial` says "Some periods
  landed, some are still owed — they are listed below."
- The scenario's sharpest requirement — that a zero-row period must not read as a
  pending one — is carried by a distinct `never_collected` state rather than by an
  empty pending list, and `:240` records the rule that `last_error` renders as an
  error "and never the other way round".
- A failed background refresh does not blank a row the reader is looking at
  (`:298`).

### SCN-116 — Vendor credential delete blocked while in use — PASS
- FK RESTRICT surfaces as 409 with an actionable sentence:
  `app/api/routes/vendor_credentials.py:114-116` — "Cannot delete: this credential
  is in use by a connection." The service raises a named error rather than letting
  the IntegrityError escape (`app/services/vendor_credential_service.py:49-53`)
  and logs the refusal (`:230`).

### SCN-117 — Grounded answer or honest refusal — PASS
- An answer with no tool call behind it is refused, not published:
  `app/agents/analytics_agent.py:661-665` logs "AnalyticsAgent refused an
  un-grounded answer" and returns `status="no_result"`; the module docstring
  states the contract at `:33` and `:40` (re-prompted once, then
  `UNGROUNDED_REFUSAL`).

### SCN-118 — Analytics answer renders a chart — PASS
- Analytics results become chart candidates like any other table:
  `app/agents/orchestrator.py:220-240` builds a `_ChartCandidate` with
  `is_sql=False` and carries `truncated` through, `:1999` merges them with the SQL
  candidates.
- The comment at `:2000-2002` is worth keeping: `determine_response_type` knows
  only SQL / knowledge / MCP, so an analytics-only answer is typed `"text"`
  however good its table is — gating viz on the response type alone is what used
  to drop these charts.

### SCN-119 — Unsupported analytics source refused at creation — PASS
- The family is declared once (`app/analytics/source_types.py:29-32`) with the
  reserved slots named in the comment, and creation refuses one that has no
  adapter (`app/services/connection_service.py:445`).

## chat

### SCN-120 — Database does not answer — honest stop — PASS
- Two independent bounds, both present: exactly one LLM repair per timeout
  (`app/core/validation_loop.py:46,439`) and a consecutive-timeout breaker that
  ends the loop with a named reason (`app/agents/sql_agent.py:289,415-422`,
  `stop_reason = "timeout_breaker"`, documented at `:112`).

## connections

### SCN-121 — Attaching an SSH key you do not own is refused — PASS
- Owner-strict lookups, and the reason is written down where someone might be
  tempted to relax it: `app/services/ssh_key_service.py:68-92` — the comment at
  `:72` explains why `SshKey.user_id.is_(None)` is deliberately NOT unioned in.

## What this audit did not check

- No browser replay. Every verdict above rests on code and tests, so a defect
  that only appears against a live GA4 property — a real 403 rendering as the
  scenario's "grant Viewer on this property" sentence, say — is **not** confirmed
  by this pass. SCN-113's error branch is the specific gap.
- No live collection run. `partial` and the pending-period list are verified as
  code paths and copy, not as something observed against a vendor.
