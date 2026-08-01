# ADR-0001 — Cache external report APIs locally, with provenance and a TTL

- **Status:** Accepted, 2026-08-01
- **Deciders:** product owner
- **Supersedes / amends:** the `vision.md` §8 anti-vision bullet "A data warehouse or
  ETL pipeline"
- **Related:** `docs/superpowers/specs/2026-08-01-analytics-sources-brief.md` (decisions
  D1, D11), `docs/superpowers/specs/2026-08-01-m0-ga4-spine-design.md` §1.3, §1.4, §3.4

## Context

CheckMyData answers questions by querying the user's own systems live. `vision.md` §8
says the product is not "a data warehouse or ETL pipeline — the system reads from
existing databases; it does not store, transform, or move production data". For
PostgreSQL, MySQL, ClickHouse and MongoDB that rule works and costs nothing: the
database is always reachable, it speaks a query language, and there is no quota on
asking it a question. Reading live is strictly better than caching.

Analytics vendors are a different kind of source. The three we are integrating —
Google Analytics 4 (Data API v1beta), App Store Connect, and Google Play (Cloud Storage
reports + the Play Developer Reporting API) — share three properties that none of the
four databases have:

1. **They are quota-limited.** GA4 bills every request against per-property and
   per-project token buckets; App Store Connect and Play throttle report downloads.
   A chat session that asks five follow-up questions about the same week would spend
   five requests against the same numbers. Under load, an interactive product that
   proxies every question to the vendor will run out of quota mid-conversation, and
   the user sees a failure that has nothing to do with their question.
2. **They lag, and they settle.** GA4 data for "today" is always partial and keeps
   moving for roughly 48 hours; Play earnings arrive around the middle of the following
   month. There is no instant of time at which "read it live" and "read it correctly"
   are the same operation. Correctness requires knowing *when* a number was fetched and
   whether the period it covers has settled — which is provenance, i.e. state we have
   to keep.
3. **They have no query language.** Each vendor exposes a fixed set of canned reports
   with fixed dimension/metric combinations. "Sessions by country for the last 30 days,
   compared with the 30 before" is not one vendor call; it is several, plus a join.
   Aggregation, comparison and cross-source reasoning — the things the product exists to
   do — can only happen on our side of the wire.

So the literal reading of §8 forbids exactly the thing that makes these sources usable.
The rule was written to protect a real invariant (we are not a warehouse; we do not lift
the customer's production data into our storage). It was not written to rule out storing
a vendor's already-aggregated public-facing report. We need to decide which of the two
readings governs, and to record it so nobody re-litigates it per module.

## Decision

**We cache external report-API results locally, per connection, with provenance and a
TTL. The production-database rule is unchanged and absolute.**

Concretely:

1. **Scope of the carve-out.** It applies *only* to external report APIs reached with a
   vendor credential the user supplied for that purpose — currently GA4, App Store
   Connect and Google Play. It does not apply to any connection that points at a
   database the user operates. Data in a user's production database is still only ever
   read, in place, on demand; we do not copy it, transform it, or move it.

2. **Fact tables, not raw payloads.** Each vendor report is parsed into typed fact rows
   (for GA4: `ga4_overview_daily`, `ga4_geo_daily`, `ga4_platform_daily`,
   `ga4_trend_daily`, `ga4_event_daily`), keyed by a natural key of
   `(connection_id, property_id, date, …dimensions)` and written with an upsert, so a
   re-run of a period overwrites rather than duplicates. **Raw vendor response bodies
   are never persisted** — not to a blob column, not to disk. `fetch()` returns parsed
   rows and the response goes out of scope. (Heroku's ephemeral filesystem makes this
   the only honest option anyway.)

3. **Provenance is mandatory.** Every fact row carries `fetched_at`. Separately, an
   `analytics_imports` journal records one row per `(connection_id, report, period)`
   with `status` (`ok` | `empty` | `failed`), `rows_written`, `error` and `fetched_at`.
   That journal is what lets the agent distinguish **"this period was collected and the
   value is zero"** from **"this period was never collected"** — two sentences that must
   never be confused in an answer, and the reason the agent has a `coverage()` tool at
   all.

4. **TTL / refresh, not a permanent copy.** Because vendor numbers settle after the
   fact, the last `REFETCH_TAIL` periods (2 for GA4) are always re-fetched, and any
   period recorded `failed` stays pending and is refilled on the next run — a hole below
   the high-water mark is not skipped. The cache converges on the vendor; it does not
   fork from it.

5. **Retention is bounded and deletion cascades.**
   - **Fact tables: kept** for the life of the connection. They are the answerable
     surface; expiring them would silently turn answered history into "not collected".
   - **Raw payloads: never persisted**, so there is nothing to retain.
   - **Journal: pruned at 400 days** (`analytics_journal_retention_days`, run by the
     existing 24 h maintenance cron). 400 days keeps a full year plus a comparison
     margin, and bounds a table that would otherwise grow by
     `reports × periods` forever — a growth flaw the source blueprint recorded and never
     fixed.
   - **Delete cascades.** `analytics_imports` and all five `ga4_*` tables hold
     `ON DELETE CASCADE` foreign keys to `connections.id`, so deleting a connection
     removes every cached row for it, and deleting a project cascades through its
     connections. Conversely, `connections.vendor_credential_id` is `ON DELETE
     RESTRICT`: deleting a credential that a connection still uses fails loudly (HTTP
     409) rather than orphaning the connection.

6. **`vision.md` §8 is amended, not quietly reinterpreted.** The bullet now states the
   production-database prohibition and this carve-out explicitly, and points here.

## Consequences

### Good

- Analytics questions are answerable at all. Aggregation, period-over-period comparison
  and cross-source reasoning happen locally, where they are cheap and composable.
- Vendor quota is spent once per period, on a schedule, instead of once per user
  question. A conversation cannot exhaust it.
- Answers can be honest about freshness and completeness, because the journal is a
  first-class record of what was collected, when, and what failed. Partial runs report
  `partial`, not success.
- Latency is local-database latency, not vendor round-trip latency, for every follow-up
  question.
- Collection survives vendor outages: a failed period is recorded and refilled later
  rather than turning into a missing answer.
- The invariant users actually care about — "our production data does not leave our
  database" — is now stated more precisely than before, not weakened.

### Bad

- We now own storage, growth and a retention policy where previously we owned none.
  Bounded (journal pruned, cascade on delete) but non-zero, and it must be re-checked
  per vendor added.
- The cache can be stale or incomplete. This is mitigated but not eliminated: every
  answer must carry its freshness and any pending-period caveat, which is extra
  machinery on the answer path (`coverage()`, the partial caveat, DataGate) that live
  proxying would not need.
- A second definition of "correct" appears: correct-per-the-cache versus
  correct-per-the-vendor. Reconciliation (the refetch tail, hole refill) exists to close
  the gap, and is itself code that can be wrong.
- Vendor schema drift now breaks a *parser and a table*, not just one request. Divergence
  from published docs is an explicit stop-and-ask (brief A2/D12).
- Someone reading §8 in isolation may still think the product warehouses data. The
  amended bullet and this ADR are the mitigation; both must stay in sync.

## Alternatives considered

### 1. Live proxy only — call the vendor on every question, store nothing

**Rejected.**

- Fails on quota: an interactive chat multiplies requests by the number of follow-ups.
  Five questions about the same week cost five identical vendor calls. Under any real
  usage the property's daily token budget is spent on repetition, and the failure lands
  mid-conversation.
- Fails on correctness: with nothing stored, there is no `fetched_at` and no journal, so
  the system cannot distinguish "zero sessions" from "never fetched", and cannot state
  freshness. That directly violates vision invariant §7 #7 ("context is always fresh or
  explicitly marked as stale") — a stricter invariant than the §8 bullet this ADR
  amends.
- Fails on capability: the vendors have no query language. A period-over-period
  comparison or a cross-source join has to be assembled from several canned reports.
  Doing that per question, live, is slower, more fragile, and still requires holding the
  intermediate results — i.e. a cache with a lifetime of one request and none of its
  benefits.
- Fails on resilience: a vendor outage or a transient 500 becomes a user-visible "I
  cannot answer", with no way to serve the numbers we already successfully read
  yesterday.

The only thing it buys is literal compliance with the old §8 wording — a rule written
about production databases, applied to a case it was not written for.

### 2. MCP-only — expose the vendors as MCP servers and let the existing MCP path handle them

**Rejected.**

- It relocates the problem instead of solving it. An MCP tool call is still a live
  vendor call, so every quota, lag and provenance argument against alternative 1 applies
  unchanged.
- It would make the feature opt-in twice over: the MCP server is off by default
  (`MCP_ENABLED`), and users would have to run and configure an external process per
  vendor. The target user is a project owner who wants to paste a service-account JSON
  and get answers — not to operate three MCP servers.
- Credentials would move out of the product's Fernet-encrypted, owner-scoped
  `vendor_credentials` store into per-server configuration we neither control nor audit,
  weakening tenant isolation (R3) rather than reusing the proven `ssh_key_service`
  owner-strict shape.
- The MCP result path is deliberately validated *less* than the SQL path. Revenue and
  install numbers must not reach a user having passed weaker checks than a `SELECT`
  does; the honesty gates (DataGate, truncation/partial caveat, freshness,
  AnswerQualityGate) are wired explicitly for analytics because of exactly this (brief
  D2/D3).
- Scheduled collection, retry of failed periods, and the journal have no home in a
  stateless tool call, so "collects on schedule without human action" (a done-criterion)
  could not be met.

MCP remains the right answer for *arbitrary user-supplied* sources. It is the wrong
answer for three known vendors that are core product surface.
