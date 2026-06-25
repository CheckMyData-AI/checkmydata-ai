# Code↔DB Sync Remediation — Design Spec (R5)

- **Date:** 2026-06-25
- **Author:** audit remediation (sergey@appvillis.com)
- **Branch:** `fix/sync-remediation-2026-06-25` (off current `fix/security-audit-2026-06-24`)
- **Source audit:** the 22 findings (9 High, 9 Medium, 4 Low) produced by the five-specialist sync audit on 2026-06-25 (backend, architecture, data/ML, security, QA).
- **Release framing:** **R5 — sync reliability & correctness**. Close each finding in `qa-audit/issues.md` and `[Unreleased]` in `CHANGELOG.md`.
- **Scope decision:** ALL 22 findings (user-approved). Approach **A** (surgical fixes + targeted structural changes where a finding demands it; no broad rewrite).

> **Status legend used below:** every contract here is *locked* — types, signatures, file layout, flag names/defaults, migration shapes. The implementation plan (`docs/superpowers/plans/2026-06-25-sync-remediation.md`) turns each into TDD tasks with exact code. A zero-context implementer must not invent names; use the ones fixed here.

> **⚠️ BINDING CORRECTIONS (post-validation, 2026-06-25):** an adversarial validation cycle confirmed all 22 findings' business logic is correct but produced corrections C1–C7 that **OVERRIDE the prose below where they conflict** — see the **Validation Log & Applied Corrections** section at the end of the plan. Most load-bearing: **C1** (owner-less project → budget *unenforced*, not blocked — §5.10 below is patched), **C2** (`omit_samples` is a threaded param, not an instance attr — §5.5d), **C4** (M3 emit needs the parent `workflow_id`; the `_hb` heartbeat must use a targeted UPDATE to avoid `version` lost-update — §5.7), **C5** (validate the ORM partial-index form before locking — §5.8), **C6** (index required-filters under the bare suffix too, for schema-qualified names — §5.9/SQL agent).

---

## 1. Goals & non-goals

### Goals
1. **Reliability:** a healthy daily sync is never mis-reaped; runs are tracked and observable; the single-active guard never 500s.
2. **Data correctness:** the per-table analysis the SQL agent consumes is attributed to the *right* table, is never silently replaced with garbage on LLM failure, never collapses cross-schema tables, and low-confidence/fallback rows never enforce hard SQL filters.
3. **Cost & privacy:** sync LLM calls are metered + budget-gated like chat; raw tenant data is scrubbed/denylisted (with an opt-in flag) before egress to the LLM provider.
4. **Loop-closure & schedule honesty:** freshness signals are consistent; per-project schedule hour is honored or not advertised; the stale→resync loop covers all connections.

### Non-goals (explicitly out of scope)
- No rewrite of the three execution paths (in-process / ARQ / daily) into one. We fix their *behavioral divergence* point-by-point (M3, M5).
- No change to the chat/orchestrator budget mechanism itself — we *reuse* `UsageService.check_token_budget` / `DbUsageSink` / `LLMRouter(usage_sink=…)`.
- No new UI work beyond what the freshness `to_dict` already feeds (the Knowledge Health panel keeps working; the schedule UI keeps reading `/sync-schedule`).
- No change to db-index *sampling* logic except adding the scrub seam shared by sync (H6).

---

## 2. Locked decisions (from brainstorming)

| Decision | Locked choice |
|---|---|
| **Scope** | All 22 findings, phased into 5 waves in one plan. |
| **H6 PII** | Layered: (1) column-name **denylist** (never send verbatim), (2) regex **redaction** of values (email/phone/card/JWT/SSN), (3) opt-in flag `connection.send_sample_data_to_llm` (default **True**) + global `sync_pii_scrubbing_enabled` (default **True**). |
| **H5 budget** | Attribute to **project owner**; meter via `DbUsageSink`; **pre-flight gate**: manual routes → HTTP **429** (matches chat's existing `check_token_budget` gate, grounded in `chat.py:197-200`), cron/auto → **graceful SKIP** (log + step status `skipped`, no crash); plus a cheap mid-run check that skips the *summary* LLM call when budget is exceeded. |
| **Approach** | A — surgical + targeted structural (H1 parent heartbeat, H9 adopt-not-run). |

> **Note on HTTP code:** the audit text said "402"; the *actual* in-repo token-budget gate (`chat.py`) returns **429**. We match the existing pattern (429) for token-budget exhaustion. EntitlementService quota→402 is a separate, pre-existing gate and is **not** added to the sync path in R5.

---

## 3. Library contract verification (Context7)

- **SQLAlchemy 2.0** (`/websites/sqlalchemy_en_20`): confirmed — after an `IntegrityError` raised from `await session.commit()`, the session is in a failed state and **must** be recovered with `await session.rollback()` before any further use; ignoring it yields the "transaction has been rolled back" error. `IntegrityError` is imported from `sqlalchemy.exc`. This grounds the **H8** contract.
- No other external-library contract changes: ARQ cron mechanics, Pydantic settings, and Alembic op API are used exactly as they already are in the repo.

---

## 4. File layout (new + touched) and ownership map

### New files
| File | Purpose |
|---|---|
| `backend/app/knowledge/pii_scrubber.py` | Pure functions: column-denylist + value-redaction for LLM egress (H6). |
| `backend/app/services/sync_budget.py` | Owner resolution + `DbUsageSink` builder + pre-flight budget verdict for sync (H5). |
| `backend/alembic/versions/<rev1>_sync_remediation_connection_flag.py` | `connections.send_sample_data_to_llm` column (H6). |
| `backend/alembic/versions/<rev2>_sync_remediation_indexing_run_active_index.py` | Add the partial-unique active index to the model/metadata parity (H8) — see §5.8. |
| `backend/alembic/versions/<rev3>_sync_remediation_schema_qualified_uniqueness.py` | `db_index` & `code_db_sync` schema-qualified uniqueness (M2). |
| `backend/tests/unit/knowledge/test_pii_scrubber.py` | Unit tests for the scrubber. |
| `backend/tests/unit/services/test_sync_budget.py` | Unit tests for the budget helper. |
| `backend/tests/unit/knowledge/test_code_db_sync_pipeline_run.py` | First real `run()`-level orchestration tests (Steps 1-6, aborts, all-fallback guard). |

### Touched files → owning task (no two parallel tasks write the same file)
| File | Owning task | Findings |
|---|---|---|
| `backend/app/config.py` + `backend/.env.example` | **W1-config** | all new flags |
| `backend/app/knowledge/pii_scrubber.py` (new) | **W1-pii** | H6 |
| `backend/app/services/sync_budget.py` (new) | **W1-budget** | H5 |
| `backend/app/knowledge/code_db_sync_analyzer.py` | **W2-analyzer** | H2 (tool `table_name` def + batch reconcile), H3, H4(marker) |
| `backend/app/knowledge/code_db_sync_pipeline.py` | **W2-pipeline** | H2(store), M2(match), H4(guard), H6(scrub call), H5(wire), L4(truncation markers) |
| `backend/app/knowledge/graph_db_bridge.py` | **W2-pipeline** | M7 (op_kind heuristics) |
| `backend/app/api/routes/data_investigations.py` | **W2-investigations** | M6 (producer reroute) |
| `backend/app/services/code_db_sync_service.py` | **W2-service** | M6, table-identity helper, mark_stale, L2 |
| `backend/app/agents/sql_agent.py` | **W2-sqlagent** | H4(confidence gate), M6(consumer guard) |
| `backend/app/services/db_index_service.py` + `backend/app/models/db_index.py` | **W2-dbindex** | H7, M2(constraint) |
| `backend/app/services/run_coordinator.py` + `backend/app/models/indexing_run.py` | **W3-coordinator** | H8 |
| `backend/app/services/daily_knowledge_sync_service.py` | **W3-daily** | H1, H9, M3, M4(consume), H5(skip), M5(overview) |
| `backend/app/services/stale_run_reaper.py` | **W3-reaper** | L1, H1(grace) |
| `backend/app/worker.py` | **W3-worker** | H5(sink), M3(synced_tables typo) |
| `backend/app/api/routes/connections.py` + `backend/app/models/connection.py` | **W4-connections** | H6(opt-in field+routes), H5(429 in trigger_sync) |
| `backend/app/services/knowledge_freshness_service.py` | **W4-freshness** | M8 |
| `backend/app/main.py` | **W5-main** | M4(wave honors hour), M1(reconciler all connections) |
| `backend/app/api/routes/projects.py` | **W5-projects** | M4(schedule consistency), M9(get_index_age guard surfaced) |

Migrations are authored by their owning task; Alembic revision linearity is resolved at integration (W5).

---

## 5. Locked contracts

### 5.1 New config flags (`backend/app/config.py`, Pydantic `Settings`)
Add to the existing settings class (same style: typed field + comment). `.env.example` gets matching commented entries.

```python
# --- R5 sync remediation -------------------------------------------------
# H6: scrub PII / secrets from DB samples + distinct values before they are
# sent to an LLM provider. Layered with the per-connection opt-in below.
sync_pii_scrubbing_enabled: bool = True
# H4: per-table analyses below this confidence are NEVER used to enforce hard
# SQL required-filters (they may still inform soft hints). 1..5; default 2
# means "fallback rows (confidence=1) never enforce filters".
sync_min_confidence_to_enforce_filters: int = 2
# H4: if the fraction of NON-fallback table analyses in a sync run is below
# this, the run does NOT overwrite the previously-stored good rows; it marks
# the summary failed and keeps prior data. 0.0 disables the guard.
sync_min_success_ratio_to_persist: float = 0.5
# H5: gate sync LLM spend on the project owner's token budget (meter + block).
sync_budget_enforcement_enabled: bool = True
```

`connection.send_sample_data_to_llm` is a **model column** (not a global flag) — see §5.9.

### 5.2 `pii_scrubber.py` (new module — pure, no I/O)

```python
"""Redact PII / secrets from DB-derived context before it reaches an LLM."""
from __future__ import annotations

# Column whose NAME (case-insensitive substring) implies sensitive content.
# Values for these columns are never sent verbatim — replaced with "[redacted:<col>]".
SENSITIVE_COLUMN_TOKENS: tuple[str, ...] = (
    "password", "passwd", "secret", "token", "api_key", "apikey", "private_key",
    "access_key", "credential", "ssn", "social_security", "card_number", "card_no",
    "cardno", "pan", "cvv", "cvc", "iban", "swift", "auth", "session", "cookie",
    "salt", "hash",  # note: matched as substrings; documented in tests
)

def is_sensitive_column(column_name: str) -> bool:
    """True if the column name implies sensitive content (case-insensitive substring)."""

def redact_value(value: str) -> str:
    """Mask PII patterns inside a free string: emails, phone numbers, credit-card-like
    digit runs, JWTs (eyJ...), and long hex/base64 secrets. Returns the masked string.
    Non-PII text is returned unchanged. Idempotent."""

def scrub_distinct_values(
    column_name: str, values: list, *, enabled: bool = True
) -> list:
    """Return distinct values safe for an LLM prompt.
    - enabled=False → return values unchanged (caller chose raw).
    - sensitive column → return ["[redacted:<n> values]"] (cardinality only, no values).
    - else → [redact_value(str(v)) for v in values]."""

def scrub_sample_json(sample_json: str, *, enabled: bool = True) -> str:
    """Parse a JSON array of row dicts; for each dict, redact sensitive columns by name
    and redact_value() every remaining string field. Re-serialise. On parse failure,
    return redact_value(sample_json) so a non-JSON blob is still masked. enabled=False →
    return input unchanged."""
```

Behavioral contract: scrubbing is **on** when `settings.sync_pii_scrubbing_enabled and connection.send_sample_data_to_llm` evaluates such that — see the truth table in §5.5 (`_build_db_context`).

### 5.3 LLM tool contract (`backend/app/llm/base.py` — unchanged shape, used as-is)
`ToolParameter` already supports `required: bool = True` and `enum`. **No change to base.py is required** beyond confirming the field exists (it does). Therefore **W1-tool is folded into W2-analyzer** (the only edit is in the tool *definition*, not the base types). The ownership map's `llm/base.py` row is dropped; analyzer owns the tool definition.

### 5.4 Analyzer contract (`code_db_sync_analyzer.py`)

**(a) `TableSyncAnalysis` gains a fallback marker (H4):**
```python
@dataclass
class TableSyncAnalysis:
    table_name: str
    ...
    confidence_score: int = 3
    is_fallback: bool = False   # NEW — True iff produced by _fallback_analysis
```
`_fallback_analysis` sets `is_fallback=True`.

**(b) `SYNC_ANALYSIS_TOOL` gains a required `table_name` parameter (H2/H3):**
```python
ToolParameter(
    name="table_name",
    type="string",
    description=(
        "The EXACT table name being analyzed, copied verbatim from the "
        "'## Table: <name>' header. Required so results can be matched back "
        "to the correct table."
    ),
),
```
Inserted as the **first** parameter.

**(c) `analyze_table_batch` reconciles by name, not position (H2/H3):**
- Build `by_name = {t[0].lower(): (t[0], idx) for idx, t in enumerate(tables)}` (input name → canonical input name).
- For each `tc` with `tc.name == "table_sync_analysis"`: read `args.get("table_name")`; look up case-insensitively in `by_name`.
  - **Hit:** build the `TableSyncAnalysis` with `table_name = <canonical input name>` (NOT the LLM string, NOT positional). Mark that input index as covered. Guard against duplicate coverage (if the LLM returns the same table twice, keep the first, log a warning).
  - **Miss / missing `table_name`:** discard the tool call, log a warning (`"batch sync: tool call for unknown table %r — dropped"`).
- After the loop, any input table **not covered** → append `_fallback_analysis(name)` (per-table fallback, preserving order is not required since each row is self-identified by `table_name`).
- Return list length still equals `len(tables)` (every input table appears exactly once).

**(d) Robust scalar coercion (H3 / QA-C2):** the `int(args.get("confidence_score", 3))` call is wrapped per-tool-call:
```python
def _coerce_confidence(raw) -> int:
    try:
        return max(1, min(5, int(float(raw))))
    except (TypeError, ValueError):
        return 3
```
Used in both `analyze_table` and `analyze_table_batch`. A single bad scalar degrades **only that table** to confidence 3 (not fallback), never aborts the batch.

**(e) `analyze_table` (single):** also reads `args.get("table_name")` but ALWAYS stores the input `table_name` (single-call path is already safe; the field is just for parity/telemetry).

### 5.5 Pipeline contract (`code_db_sync_pipeline.py`)

**(a) Schema-qualified table identity in `_match_tables` (M2):**
- Build the DB lookup keyed by `(schema_lower, name_lower)`:
  ```python
  db_by_key = {}                      # (schema_lower, name_lower) -> DbIndex
  bare_name_counts = Counter()        # name_lower -> count across schemas
  for e in db_entries:
      sch = (getattr(e, "table_schema", None) or "public").lower()
      nm = e.table_name.lower()
      db_by_key[(sch, nm)] = e
      bare_name_counts[nm] += 1
  ```
- A bare name is **ambiguous** iff `bare_name_counts[name_lower] > 1`.
- The stored/displayed `table_name` for a DB entry is:
  - bare `e.table_name` when **not** ambiguous (back-compat — no prompt churn for single-schema installs),
  - `f"{e.table_schema}.{e.table_name}"` when **ambiguous**.
- Code entities/usages match against the bare lowercased name as today, but when that bare name is ambiguous the match is recorded against **each** schema-qualified DB entry, and `confidence`/notes carry a "matched by bare name across N schemas — verify schema" caveat in `code_context`.
- `all_tables` iteration uses the qualified display name as the `_MatchedTable.table_name` so Step 5 stores distinct rows per schema.

**(b) Step 5 store keyed by self-identified analysis name (H2):** `mt_lookup` lookup uses `analysis.table_name` which now always equals a matched display name (guaranteed by 5.4c). Add an assertion-style guard: if `analysis.table_name not in mt_lookup`, skip the row and log (defensive; should never happen).

**(c) All-fallback / low-success guard (H4):** after Step 4 produces `analyses`, before Step 5 delete+upsert:
```python
total = len(analyses)
non_fallback = sum(1 for a in analyses if not a.is_fallback)
ratio = (non_fallback / total) if total else 0.0
if total and ratio < settings.sync_min_success_ratio_to_persist:
    # Do NOT delete_stale_tables or upsert — keep prior good rows intact.
    await self._sync_svc.set_sync_status(session, connection_id, "failed")
    self._tracker.end(wf_id, "code_db_sync", "failed",
                      f"LLM degraded: only {non_fallback}/{total} tables analyzed; "
                      f"kept previous sync")
    return {"status": "failed", "error": "llm_degraded_kept_previous", ...}
```
(Guard skipped when `sync_min_success_ratio_to_persist == 0.0`.)

**(d) PII scrub in `_build_db_context` (H6):** the method gains a `scrub: bool` parameter (threaded from `run()` which knows the connection's `send_sample_data_to_llm` AND the global flag):
```python
scrub = settings.sync_pii_scrubbing_enabled and connection_send_sample_data_to_llm
# distinct values:
vals_str = " | ".join(pii_scrubber.scrub_distinct_values(col, vals[:15], enabled=...)...)
# sample data:
sample = pii_scrubber.scrub_sample_json(entry.sample_data_json, enabled=...)[:800]
```
Truth table for what reaches the LLM:
| `sync_pii_scrubbing_enabled` | `connection.send_sample_data_to_llm` | Distinct values | Sample data |
|---|---|---|---|
| True | True | redacted (denylist+regex) | redacted |
| True | False | omitted entirely | omitted entirely |
| False | True | raw | raw |
| False | False | omitted entirely | omitted entirely |
(`send_sample_data_to_llm=False` always omits sample+distinct; the global flag only toggles redaction-vs-raw when sending is allowed.)

**(e) L4 truncation markers:** when `len(vals) > 15`, append `f" (+{len(vals)-15} more)"`; when `sample_data_json` is truncated at 800 chars, append `"…[truncated]"`. (Display-only; no behavior change.)

**(f) H5 budget wiring in `run()`:** at the top of `run()` (after `wf_id` is set, before Step 1):
```python
from app.services.sync_budget import build_sink, preflight_owner_budget
if settings.sync_budget_enforcement_enabled:
    async with async_session_factory() as s:
        ok, reason, owner_id = await preflight_owner_budget(s, project_id)
    if not ok:
        await self._sync_svc.set_sync_status(...“failed”/“skipped”...)
        await self._tracker.end(wf_id, "code_db_sync", "failed", reason)
        return {"status": "failed", "error": reason, "budget_blocked": True, ...}
    self._llm = LLMRouter(usage_sink=build_sink(owner_id, project_id))
    self._analyzer = CodeDbSyncAnalyzer(self._llm)
```
Mid-run: before the Step-6 summary LLM call, `if self._llm._sink.budget_exceeded(): skip summary, use SyncSummaryResult() default`. (Analyses already computed are persisted by Step 5; summary is additive and safely skippable.)

> The route-level pre-flight (429 / graceful-skip) is the *primary* gate (§5.10/§5.7); this in-pipeline gate is the backstop for the cron/auto path which does not pass through a route.

### 5.6 `code_db_sync_service.py`

**(a) `add_runtime_enrichment` (M6):**
- For `required_filters_json`: **validate shape** before merge — the payload must be a flat `{column: condition}` dict; reject/skip keys whose value is not a string OR whose key is a known metadata token (`"source"`, `"filter"`, `"_meta"`). Only `{column: condition_string}` pairs are merged. The investigation producer (§5.6c) is changed to emit the correct shape, but the service stays defensive.
- For `column_value_mappings_json`: **deep-merge per column** — `existing[col]` and `new[col]` are both dicts → `existing[col].update(new[col])` (preserves prior value meanings); only replace wholesale when one side is non-dict.
- For appendable text fields (`query_recommendations`, `conversion_warnings`): dedupe by **normalized-line equality** (split existing into lines, compare stripped); cap total length at `8000` chars (truncate oldest, keep newest), so the column cannot grow unbounded (M6.3 / L-text).

**(b) Confidence-aware prompt context (H4):** `sync_to_prompt_context` and the SQL-agent loaders gate on confidence — see §5.6/§5.8 wiring; the service exposes the raw `confidence_score` (already on the row), the *gating* lives in the SQL-agent consumer (§5.8) and is config-driven.

**(c) Producer fix in `data_investigations.py::_enrich_sync_from_investigation` (M6):** change the `missing_filter` branch payload from `{"source": "investigation", "filter": inv.root_cause}` to a real filter shape, OR route it to a non-enforced field. **Locked choice:** route investigation-derived hints to `query_recommendations` (a soft, non-enforced field) instead of `required_filters_json`, since an investigation root-cause string is prose, not a `{column: condition}` map:
```python
await sync_svc.add_runtime_enrichment(
    db, connection_id=inv.connection_id, table_name=table,
    field="query_recommendations",
    value=f"[from investigation] {inv.root_cause}",
)
```
This removes the contract violation at the source; the service-level validation (5.6a) is the safety net.

**(d) L2 — `touch_heartbeat` no longer fabricates a "synced_at":** when `touch_heartbeat` creates a summary row, it sets `synced_at=None` is not possible (`server_default`), so instead the fix lives in presentation: `sync_to_prompt_context` only prints the "analyzed <date>" header when `summary.sync_status == "completed"` (or `"stale"`). For `running`/`failed`/`idle` it prints a neutral header without a fabricated date. (Owned by W2-service.)

### 5.7 `daily_knowledge_sync_service.py`

**(a) H1 — continuous parent heartbeat (primary fix):** `run_for_project` wraps `_orchestrate` in a heartbeat that refreshes the **parent** `daily_sync` run's `heartbeat_at` every `settings.heartbeat_interval_seconds`:
```python
from app.core.heartbeat import heartbeat
async def _hb() -> None:
    async with async_session_factory() as s:
        run = await s.get(IndexingRun, run_id)
        if run and run.status == "running":
            run.heartbeat_at = datetime.now(UTC)
            await s.commit()
async with heartbeat(_hb, interval_seconds=settings.heartbeat_interval_seconds):
    result = await self._orchestrate(project_id, run_id=run_id)
```
This guarantees the reaper (300s) never kills a working multi-minute daily sync.

**(b) M3 — progress + manifest alignment:** `_orchestrate(project_id, *, run_id)` emits coordinator step transitions for the real phases so the parent run advances past 0%. The `daily_sync` manifest in `run_manifests.py` is aligned to the phases `_orchestrate` actually runs (`plan_targets` → `repo_index` → `db_index` → `code_db_sync` → `summarize`); the dead `freshness_reconcile` step is removed from the daily manifest (the standalone reconciler loop owns reconciliation). Exact step keys are read from `run_manifests.py` by the implementing task and the manifest edited to match. Progress is emitted via lightweight `tracker.emit(run.workflow_id, step, "started"/"completed", …)` so the existing `_on_event`→`_apply_event` projection advances `progress_pct`.

**(c) H9 — adopt-not-run on conflict:** `_start_child_wf` returns a `(wf_id | None, already_active: bool)` tuple. When `already_active` is True (the child kind+connection already has an active run, i.e. a manual/auto run is in flight), the daily sub-step **SKIPS** running its own pipeline (returns `_STEP_SKIPPED, "already running (adopted)"`) instead of launching an untracked concurrent pipeline. The soft `get_sync_status=="running"` check stays as a second line.

**(d) M4 — honor per-project hour (consume side):** daily sync remains correct because the wave now passes only projects whose effective hour matches the current dispatch hour (the *decision* is in `main.py`, §5.11). `list_eligible_projects` additionally returns the effective hour so the wave can filter (see §5.11).

**(e) H5 — graceful budget skip:** `_run_code_db_sync` (and `_run_db_index` for symmetry) calls `preflight_owner_budget`; if exceeded → return `_STEP_SKIPPED, "owner token budget exceeded"` (no crash, recorded in steps_json). The pipeline's own backstop (§5.5f) covers direct callers.

**(f) M5 — regenerate overview after daily sync:** after a successful `_run_code_db_sync`, call `_regenerate_overview(project_id, connection_id)` (matching the in-process/ARQ paths) inside the `final_status == _STEP_COMPLETED` branch.

### 5.8 `run_coordinator.py` + `indexing_run.py` (H8)

**(a) `start()` catches the partial-unique race:**
```python
from sqlalchemy.exc import IntegrityError
...
db.add(run)
try:
    await db.commit()
except IntegrityError as exc:
    await db.rollback()                      # Context7-confirmed: required
    existing = await self._find_active(db, project_id, kind, connection_id)
    raise RunAlreadyActiveError(existing.id if existing else "unknown") from exc
await db.refresh(run)
```
This converts the DB-level race into the same `RunAlreadyActiveError` callers already handle (clean 409 / adopt), and recovers the session so request handlers don't fail downstream.

**(b) Model/metadata parity:** add the partial-unique index to `IndexingRun.__table_args__` so `Base.metadata.create_all` (unit tests / SQLite) enforces single-active too:
```python
Index(
    "uq_indexing_runs_active_one",
    "project_id", "kind", text("coalesce(connection_id, '')"),
    unique=True,
    sqlite_where=text("status IN ('queued','running','cancelling')"),
    postgresql_where=text("status IN ('queued','running','cancelling')"),
),
```
A no-op Alembic migration (`<rev2>`) documents the parity (the index already exists in prod via `a1f2b3c4d5e6`; the migration guards `op.create_index(..., if_not_exists=True)` for envs created before model parity). Tests that build schemas via `create_all` now exercise the guard.

### 5.9 `db_index_service.py` + `db_index.py` (H7, M2)

**(a) H7 — `is_indexed` distinguishes failed-only:**
```python
async def is_indexed(self, session, connection_id) -> bool:
    summary = await self.get_summary(session, connection_id)
    if not summary:
        return False
    status = (getattr(summary, "indexing_status", "idle") or "idle")
    if status in ("running", "failed", "idle"):
        return False
    if status not in ("completed", "completed_partial"):
        return False
    return summary.indexed_at is not None
```
i.e. only `completed`/`completed_partial` count as indexed. (`completed_partial` stays indexed per the existing R2-4 contract.) `get_index_age` (M9) gains the `None` guard:
```python
indexed_at = summary.indexed_at
if indexed_at is None:
    return None
if indexed_at.tzinfo is None:
    indexed_at = indexed_at.replace(tzinfo=UTC)
```

**(b) M2 — schema-qualified uniqueness:** `DbIndex.__table_args__` unique constraint becomes `(connection_id, table_schema, table_name)` (name `uq_db_index_conn_schema_table`); migration `<rev3>` drops `uq_db_index_conn_table` and creates the new one. The db_index *upsert* path (in `db_index_service`/`db_index_pipeline`) keys on `(connection_id, table_schema, table_name)`. The same schema-aware uniqueness is applied to `code_db_sync` only if needed — since `_match_tables` now stores schema-qualified names on collision (§5.5a), the existing `(connection_id, table_name)` constraint on `CodeDbSync` already keeps qualified names distinct; **no CodeDbSync constraint change** is required (locked: leave it).

> The db_index upsert anchor is read by the implementing task; the contract (key tuple `(connection_id, table_schema, table_name)`) is fixed here.

### 5.10 `sync_budget.py` (new — H5)

```python
"""Owner-attributed budget gate + usage sink for the code↔DB sync pipeline."""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession

async def resolve_owner_user_id(session: AsyncSession, project_id: str) -> str | None:
    """Return Project.owner_id for the project, or None if the project is gone."""

def build_sink(owner_user_id: str, project_id: str):
    """Return a DbUsageSink(user_id=owner_user_id, project_id=project_id)."""

async def preflight_owner_budget(
    session: AsyncSession, project_id: str
) -> tuple[bool, str | None, str | None]:
    """(_enabled-aware) Return (ok, reason, owner_user_id).
    - owner missing (Project.owner_id NULL — legacy/owner-deleted) → (True, None, None)  # C1:
      budget UNENFORCED (log WARNING; caller uses default LLMRouter/NullUsageSink).
      Blocking here would freeze every sync for owner-less projects (graceful-degradation
      violation), so we degrade, never block.
    - check_token_budget(owner) returns a message → (False, message, owner_id)
    - else → (True, None, owner_id)
    When settings.sync_budget_enforcement_enabled is False → always (True, None, owner_id)."""
```
Uses `UsageService.check_token_budget(session, owner_id)` (grounded signature) and `DbUsageSink(user_id=…, project_id=…)`.

### 5.11 `main.py` (M4, M1)

**(a) M4 — wave honors per-project hour:** `_dispatch_daily_knowledge_sync_wave` computes the current hour in `daily_knowledge_sync_timezone` and dispatches a project only when its **effective** schedule hour equals the current hour. The cron loop wakes hourly (or computes the next per-project boundary). **Locked simplest correct design:** the loop wakes at the top of every hour; the wave filters `eligible` to projects whose `SyncScheduleService.effective(...)["hour"] == current_local_hour`. `list_eligible_projects` already filters on `enabled`; the hour filter is added in the wave. The Redis day-lock becomes an **hour-lock** `cron:daily_sync:{run_date}:{hour}` so each hour's wave is single-flight.

**(b) M1 — reconciler covers all connections:** `_freshness_reconcile` iterates **all** connections of each project (not just `connections[0]`) and calls `maybe_autostart_db_index` / `maybe_autostart_sync` per connection. `KnowledgeFreshnessService.evaluate` is called per connection. (Still gated by `freshness_reconciler_enabled`, default off — behavior unchanged when disabled; the fix is correctness when enabled.)

### 5.12 `knowledge_freshness_service.py` (M8)

- `warnings: list[str] = field(default_factory=list)` (no more `None` default); drop the `# type: ignore`.
- `to_summary`/`overall_stale` keep working on the list.
- Keep `warnings` and `details` appended in lockstep inside `_warn` (already the case); add a class-level docstring noting `to_dict` serialises `details` and `to_summary` serialises `warnings` and both are filled by `_warn` only.
- `stale` vs `failed` distinction for triggering: `sync_stale` stays True for both, but add `sync_failed: bool` field set only when `sync_status == "failed"`. The reconciler (M1) uses `sync_stale` to resync but applies a **failed-backoff**: when `sync_failed`, only resync if the last failed run is older than `settings.heartbeat_interval_seconds * N` (locked: skip auto-resync of a `failed` sync more than once per reconcile cycle — i.e. the reconciler resyncs `stale` immediately but a `failed` sync at most once per `freshness_reconciler` interval, preventing the retry-storm). Minimal lock: add `sync_failed` and have the reconciler treat `failed` with a one-shot guard keyed in-memory per connection per cycle.

### 5.13 `connections.py` + `connection.py` (H6 opt-in, H5 429)

- `Connection` model gains `send_sample_data_to_llm: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")`. Migration `<rev1>`. Surfaced in `ConnectionCreate` (default True) and `ConnectionResponse`.
- `trigger_sync` route: before dispatch, `ok, reason, _ = await preflight_owner_budget(db, conn.project_id)`; if not ok → `raise HTTPException(status_code=429, detail=reason)`. (Mirrors chat.)
- `sync_now` route (in `projects.py`, W5): same 429 pre-flight.

### 5.14 `worker.py` (H5 sink, M3 typo)

- `run_code_db_sync` builds the budget sink the same way (or relies on the pipeline's internal §5.5f wiring — **locked: rely on pipeline-internal wiring**, so the worker just calls the pipeline; no duplicate sink construction). The worker's pre-flight is the pipeline's backstop.
- Fix the log key: `result.get("synced")` (was `synced_tables`) so `matched=` logs correctly.

### 5.15 `stale_run_reaper.py` (L1, H1-grace)

- L1: when any driver returns `-1` rowcount, still log at INFO that a sweep ran and that the exact count is unknown (`"reaper swept (rowcount unknown on this driver)"`), so a real reap is never invisible. Keep `max(0, …)` for the numeric sum.
- H1 secondary grace: `_stale_run` additionally protects a run whose `heartbeat_at` is non-null but younger than cutoff (already correct) — no change needed once §5.7a heartbeats the parent. (No reaper change strictly required for H1; the heartbeat is the fix. L1 is the only reaper edit.)

---

## 6. Per-finding → fix traceability (all 22)

| ID | Sev | Root cause (verified) | Fix (contract §) | Owning task |
|---|---|---|---|---|
| H1 | High | Parent `daily_sync` heartbeat frozen → reaped at 5 min; result discarded | Continuous parent heartbeat §5.7a (+ progress §5.7b) | W3-daily, W3-reaper(L1) |
| H2 | High | Batch analysis attributed by tool-call position | Required `table_name` + name reconciliation §5.4b/c, store §5.5b | W2-analyzer, W2-pipeline |
| H3 | High | One bad `confidence_score` aborts whole batch | Per-call `_coerce_confidence` §5.4d | W2-analyzer |
| H4 | High | All-fallback run overwrites good rows; conf decorative | `is_fallback` marker §5.4a, success-ratio guard §5.5c, confidence gate §5.6b/§5.8(sqlagent) | W2-analyzer/pipeline/sqlagent |
| H5 | High | Sync LLM bypasses budget/usage gate | `sync_budget` §5.10, pipeline wire §5.5f, route 429 §5.13/§5.7e, meter via DbUsageSink | W1-budget, W2-pipeline, W3-daily, W4/W5 routes |
| H6 | High | Raw samples/distinct → LLM, no scrub | `pii_scrubber` §5.2, scrub in `_build_db_context` §5.5d, opt-in column §5.13 | W1-pii, W2-pipeline, W4-connections |
| H7 | High | `is_indexed` True for failed-only index | status whitelist §5.9a | W2-dbindex |
| H8 | High | `start()` race → 500 not 409; index missing from model | catch `IntegrityError`+rollback §5.8a, model parity §5.8b | W3-coordinator |
| H9 | High | Daily runs untracked concurrent pipeline on conflict | adopt-not-run §5.7c | W3-daily |
| M1 | Med | Stale→resync loop only covers connection[0]; off by default | reconciler all-connections §5.11b | W5-main |
| M2 | Med | Same-name cross-schema tables collapse | schema-qualified identity §5.5a + uniqueness §5.9b | W2-pipeline, W2-dbindex |
| M3 | Med | Parent run 0%→100%; freshness_reconcile dead | progress steps + manifest align §5.7b | W3-daily |
| M4 | Med | Per-project hour advertised, ignored by cron | wave honors hour §5.11a | W5-main |
| M5 | Med | daily sync skips `_regenerate_overview`; `synced_tables` typo | overview §5.7f, log key §5.14 | W3-daily, W3-worker |
| M6 | Med | Enrichment writes `{source,filter}` into required_filters; shallow merge | validate+deep-merge §5.6a, producer reroute §5.6c | W2-service, (W2-investigations) |
| M7 | Med | graph op_kind heuristics presented as authoritative | label op_kind "(heuristic)", trim over-broad write verbs, drop fabricated `depth` from prompt §6note | W2-pipeline (graph_db_bridge) |
| M8 | Med | freshness `warnings=None`, source split, stale==failed | dataclass §5.12 | W4-freshness |
| M9 | Med | `get_index_age` AttributeError on NULL indexed_at | None guard §5.9a | W2-dbindex |
| L1 | Low | reaper `-1` rowcount → "0 reaped" log hides work | INFO-log unknown-count §5.15 | W3-reaper |
| L2 | Low | `touch_heartbeat` fabricates synced_at header | header gating §5.6d | W2-service |
| L3 | Low | daily child orphaned to reaper; two terminal writers | covered by H9 (adopt) + H1 heartbeat; document divergence note | W3-daily/coordinator |
| L4 | Low | distinct[:15]/sample[:800] truncation unmarked; substring relevance | truncation markers §5.5e; word-boundary relevance match (graph/enum) | W2-pipeline |

**M7 detail (locked):** in `graph_db_bridge.py`, (1) move `process_`, `handle_`, `sync_`, `set_`, `add_`, `register_` out of `_WRITE_VERBS` into a new `_AMBIGUOUS_VERBS` → `op_kind="unknown"`; (2) the pipeline prompt line drops the fabricated `depth=` and labels op as `op={op_kind} (heuristic)`; (3) `_estimate_depth` is kept only for ranking, not printed. **L4 relevance detail (locked):** the substring `in` checks for enums/services/scopes/constants in `_build_code_context` switch to word-boundary/exact-token match (`table_lower == x or table_lower in tokenize(x)`).

---

## 7. Sync request lifecycle (after R5)

```
trigger_sync / sync_now (route)
  → require_role(editor) → preflight_owner_budget → 429 if exceeded
  → RunCoordinator.start(code_db_sync|daily_sync)   # IntegrityError→RunAlreadyActiveError→409
  → dispatch (ARQ | in-proc | daily)

daily _orchestrate(run_id)  [wrapped in parent heartbeat 30s]
  → coord.step plan_targets → repo_index → (per conn) db_index → code_db_sync → summarize
  → each sub-step: adopt-not-run if a manual run is active; budget-skip if owner over budget

CodeDbSyncPipeline.run
  → preflight_owner_budget (backstop) → build LLMRouter(usage_sink=owner sink)
  → load code knowledge / db index
  → _match_tables (schema-qualified identity)
  → analyze (per-call confidence coercion; batch reconciled by table_name)
  → all-fallback guard: if success-ratio < threshold → keep prior rows, mark failed, stop
  → store (delete_stale + upsert by self-identified name)
  → summary (skipped if budget exceeded mid-run)
  → _regenerate_overview

DB egress to LLM: _build_db_context → pii_scrubber (denylist+redact | omit | raw) per truth table
SQL agent consumption: required_filters enforced only when confidence ≥ threshold
```

---

## 8. Error handling & graceful degradation
- Budget exceeded: manual → 429 (actionable message); cron/auto → step `skipped` + logged, never crashes the wave; pipeline backstop → run `failed` with `budget_blocked`.
- LLM degraded (all/most fallback): prior good sync is **preserved**; run marked `failed`; freshness surfaces it; no garbage overwrites filters.
- `IntegrityError` race: recovered via rollback → clean `RunAlreadyActiveError` → 409/adopt.
- PII scrub parse failure: falls back to whole-string redaction (never raw).
- Reaper: continuous parent heartbeat prevents false-positive reaps; reaper still recovers genuinely dead runs.

## 9. Testing strategy (TDD — every task: failing → impl → green)
- **pii_scrubber:** email/phone/card/JWT masking; denylist columns → cardinality only; opt-out → omit; non-JSON sample → masked; idempotency.
- **analyzer:** batch reorder / skip / extra-call / unknown-name → correct attribution + per-table fallback; non-numeric/`"4.5"`/`"high"` confidence → that table conf=3, others intact; `table_name` echoed.
- **pipeline run():** first real orchestration tests — empty knowledge / empty db abort; all-fallback guard keeps prior rows; schema-qualified identity for colliding names; scrub applied; budget pre-flight blocks.
- **sync_budget:** owner missing; enforcement off → always ok; over-budget → reason.
- **is_indexed:** failed-only → False; completed_partial → True; get_index_age None-guard.
- **run_coordinator:** simulated `IntegrityError` on commit → `RunAlreadyActiveError` + session usable (rollback); `create_all` enforces single-active.
- **daily:** parent heartbeat refreshes during a long orchestrate (reaper does not reap); adopt-not-run skips when manual active; budget skip; overview regen called.
- **reaper:** `-1` rowcount logs sweep; healthy heartbeated parent survives.
- **freshness:** default warnings list; stale vs failed; all-connections reconcile.
- **main wave:** only projects whose effective hour == current hour are dispatched; hour-lock single-flight.
- CI gates unchanged: ruff format+check, mypy, 72% combined coverage (each task adds tests to hold/raise coverage), retrieval eval untouched.

## 10. Rollout / back-compat / flags
- All new behavior is either a bugfix (no flag) or gated by a flag defaulting to the safe value (`sync_pii_scrubbing_enabled=True`, `sync_budget_enforcement_enabled=True`, `send_sample_data_to_llm=True`).
- Migrations are additive/locked: new column (default True), index parity (if-not-exists), schema-qualified unique constraint (drop+create within one migration, guarded for SQLite).
- No data backfill required; existing CodeDbSync rows remain valid (bare names stay bare unless a future re-sync detects a collision).
- Disabling `sync_budget_enforcement_enabled` restores pre-R5 metering-off behavior; disabling `sync_pii_scrubbing_enabled` restores raw egress (for trusted single-tenant self-host).

## 11. Open risks / watch-items
- **M2 schema qualification** changes stored `table_name` for *colliding* tables only — verify the SQL agent prompt + required-filter guard accept `schema.table` strings (they already inject `WHERE` clauses table-by-table; qualified names are inert text). Covered by a sql_agent test.
- **M3 manifest edit** must keep other consumers of the `daily_sync` manifest (UI step rendering) working — the implementing task verifies `run_manifests.py` consumers.
- **db_index upsert key change (M2)** must be applied atomically with the constraint migration to avoid an upsert hitting the old constraint mid-deploy — sequenced in W2-dbindex.
- **Heartbeat overhead:** one extra UPDATE per parent run every 30s — negligible.

## 12. Wave plan (dependency graph for the implementation plan)
- **Wave 1 (sequential foundation):** W1-config (flags) → then parallel: W1-pii, W1-budget. Contracts/types only; no consumers yet.
- **Wave 2 (parallel; correctness):** W2-analyzer → W2-pipeline (depends analyzer+pii+budget); parallel W2-service, W2-sqlagent, W2-dbindex, W2-investigations(producer). File ownership disjoint.
- **Wave 3 (parallel; reliability):** W3-coordinator, W3-daily (depends budget+coordinator), W3-reaper, W3-worker.
- **Wave 4 (parallel; egress/freshness):** W4-connections (model+migration+routes; depends budget+pii), W4-freshness.
- **Wave 5 (sequential glue):** W5-main (wave/reconciler), W5-projects (schedule/route), migration linearization, CHANGELOG + qa-audit/issues.md closure, full `make check` + frontend tsc/lint, final validation cycle (§ plan).

Each task: exact `file:line` anchors, complete code, failing-test-first, conventional commit, explicit DoD. Parallel-group tasks share no files (table in §4).
