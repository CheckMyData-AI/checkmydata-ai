# Code↔DB Sync Remediation — Implementation Plan (R5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all 22 findings of the 2026-06-25 code↔DB sync audit (reliability, data correctness, cost/privacy, schedule honesty) without rewriting the existing pipeline.

**Architecture:** Surgical fixes plus two targeted structural changes (continuous parent-run heartbeat for daily sync; adopt-not-run for the daily child sub-steps). Two new pure/helper modules (`pii_scrubber`, `sync_budget`). LLM batch results are reconciled by table name instead of position; sync LLM spend is metered + budget-gated like chat; DB samples are scrubbed before LLM egress.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async (`asyncpg`/`aiosqlite`), Alembic, ARQ, pytest (`asyncio_mode=auto`), ruff `0.15.15`, mypy.

**Companion spec:** `docs/superpowers/specs/2026-06-25-sync-remediation-design.md` (all contracts locked there; § references below point into it).

## Global Constraints

- **Branch:** `fix/sync-remediation-2026-06-25` (already created off `fix/security-audit-2026-06-24`).
- **Line length 100; ruff rules `E F I N W UP`; ruff + mypy pinned** — do not widen. Run `cd backend && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports` before each commit.
- **Async everywhere** — no sync I/O on the request path; SQLAlchemy 2.0 async sessions via `async_session_factory`.
- **TDD mandatory** — failing test → confirm fail → minimal impl → confirm pass → commit. `asyncio_mode="auto"` (no `@pytest.mark.asyncio`).
- **Coverage gate 72% combined** (`coverage report --fail-under=72`). Every task adds tests; never lower coverage.
- **Conventional commits**, prefix `fix(sync):` / `feat(sync):` / `security(sync):` / `test(sync):` / `docs(sync):`.
- **New env vars** → `backend/app/config.py` (docstring) **and** `backend/.env.example`.
- **Single-active guard:** SQLAlchemy `IntegrityError` is imported from `sqlalchemy.exc`; after it is raised by `await session.commit()` the session MUST be recovered with `await session.rollback()` before reuse (Context7-confirmed).
- **No two parallel tasks write the same file** — ownership table in spec §4 is authoritative.
- **Final task** closes each finding ID in `qa-audit/issues.md` and adds a CHANGELOG `[Unreleased]` entry.

---

## Dependency graph & parallel groups

```
Wave 1 (foundation):  T1 (config)  ──►  T2 (pii_scrubber) ‖ T3 (sync_budget)
Wave 2 (correctness):  T4 (analyzer) ──► T5 (pipeline)        [T5 depends T2,T3,T4]
                       T6 (service) ‖ T7 (sqlagent) ‖ T8 (dbindex subsystem) ‖ T9 (investigations producer)
Wave 3 (reliability):  T10 (coordinator) ──► T11 (daily)      [T11 depends T3,T10]
                       T12 (reaper) ‖ T13 (worker)
Wave 4 (egress/fresh): T14 (connections: flag+migration+routes) [depends T3] ‖ T15 (freshness)
Wave 5 (glue):         T16 (main) ‖ T17 (projects) ──► T18 (integration: migrations linearize, CHANGELOG, issues, make check, validation cycle)
```
Parallelizable within a wave = tasks on the same line separated by `‖`. `──►` = ordering dependency.

---

# WAVE 1 — Foundation (contracts only, no consumers)

## Task T1: Config flags + .env.example

**Files:**
- Modify: `backend/app/config.py` (the `Settings` class; add after the existing `db_index_batch_size` block near line 315)
- Modify: `backend/.env.example`
- Test: `backend/tests/unit/test_config.py` (add a test; create if absent)

**Interfaces — Produces:**
- `settings.sync_pii_scrubbing_enabled: bool = True`
- `settings.sync_min_confidence_to_enforce_filters: int = 2`
- `settings.sync_min_success_ratio_to_persist: float = 0.5`
- `settings.sync_budget_enforcement_enabled: bool = True`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_config.py  (append)
def test_r5_sync_remediation_defaults():
    from app.config import settings
    assert settings.sync_pii_scrubbing_enabled is True
    assert settings.sync_min_confidence_to_enforce_filters == 2
    assert settings.sync_min_success_ratio_to_persist == 0.5
    assert settings.sync_budget_enforcement_enabled is True
```

- [ ] **Step 2: Run it — expect FAIL** (`AttributeError`)

`cd backend && .venv/bin/pytest tests/unit/test_config.py::test_r5_sync_remediation_defaults -v`
Expected: FAIL (`'Settings' object has no attribute 'sync_pii_scrubbing_enabled'`).

- [ ] **Step 3: Add the fields** (in `Settings`, after `db_index_batch_size: int = 5`)

```python
    # --- R5 sync remediation -------------------------------------------------
    # H6: scrub PII / secrets from DB samples + distinct values before LLM egress.
    sync_pii_scrubbing_enabled: bool = True
    # H4: per-table analyses below this confidence never enforce hard SQL filters.
    sync_min_confidence_to_enforce_filters: int = 2
    # H4: if the fraction of non-fallback analyses is below this, keep prior rows
    # instead of overwriting with a degraded run. 0.0 disables the guard.
    sync_min_success_ratio_to_persist: float = 0.5
    # H5: gate sync LLM spend on the project owner's token budget.
    sync_budget_enforcement_enabled: bool = True
```

- [ ] **Step 4: Mirror in `.env.example`**

```bash
# R5 sync remediation
SYNC_PII_SCRUBBING_ENABLED=true
SYNC_MIN_CONFIDENCE_TO_ENFORCE_FILTERS=2
SYNC_MIN_SUCCESS_RATIO_TO_PERSIST=0.5
SYNC_BUDGET_ENFORCEMENT_ENABLED=true
```

- [ ] **Step 5: Run test — expect PASS**, then ruff/mypy.

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/.env.example backend/tests/unit/test_config.py
git commit -m "feat(sync): R5 config flags (pii scrub, confidence gate, success-ratio guard, budget)"
```

---

## Task T2: `pii_scrubber.py` (H6)

**Files:**
- Create: `backend/app/knowledge/pii_scrubber.py`
- Test: `backend/tests/unit/knowledge/test_pii_scrubber.py`

**Interfaces — Produces** (spec §5.2):
- `is_sensitive_column(column_name: str) -> bool`
- `redact_value(value: str) -> str`
- `scrub_distinct_values(column_name: str, values: list, *, enabled: bool = True) -> list`
- `scrub_sample_json(sample_json: str, *, enabled: bool = True) -> str`
- `scrub_row_cells(columns: list[str], rows: list[list], *, enabled: bool = True) -> list[list]`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/knowledge/test_pii_scrubber.py
from app.knowledge import pii_scrubber as p


def test_sensitive_column_detection():
    assert p.is_sensitive_column("password_hash")
    assert p.is_sensitive_column("user_API_Key")
    assert not p.is_sensitive_column("created_at")


def test_redact_email_phone_card_jwt():
    assert "[redacted-email]" in p.redact_value("contact a@b.com please")
    assert "[redacted-card]" in p.redact_value("4111 1111 1111 1111")
    assert "[redacted-jwt]" in p.redact_value("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def")
    assert p.redact_value("just text") == "just text"


def test_scrub_distinct_sensitive_column_returns_cardinality_only():
    out = p.scrub_distinct_values("email", ["a@b.com", "c@d.com"])
    assert out == ["[redacted: 2 values]"]


def test_scrub_distinct_disabled_returns_raw():
    assert p.scrub_distinct_values("email", ["a@b.com"], enabled=False) == ["a@b.com"]


def test_scrub_sample_json_redacts_and_survives_bad_json():
    good = '[{"email": "a@b.com", "note": "call 415-555-1212"}]'
    out = p.scrub_sample_json(good)
    assert "a@b.com" not in out and "415-555-1212" not in out
    # non-JSON still masked, not raw
    assert "a@b.com" not in p.scrub_sample_json("raw blob a@b.com")
    assert p.scrub_sample_json("anything", enabled=False) == "anything"


def test_scrub_row_cells_redacts_sensitive_columns():
    cols = ["id", "password", "email"]
    rows = [[1, "hunter2", "a@b.com"]]
    out = p.scrub_row_cells(cols, rows)
    assert out[0][0] == 1
    assert "hunter2" not in str(out[0][1])
    assert "a@b.com" not in str(out[0][2])
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

`cd backend && .venv/bin/pytest tests/unit/knowledge/test_pii_scrubber.py -v`

- [ ] **Step 3: Implement `pii_scrubber.py`**

```python
"""Redact PII / secrets from DB-derived context before it reaches an LLM.

Pure functions, no I/O. Used by the DB-index validator and the code↔DB sync
analyzer (the two places raw tenant sample data would otherwise egress to an
LLM provider). See spec §5.2.
"""
from __future__ import annotations

import json
import re

SENSITIVE_COLUMN_TOKENS: tuple[str, ...] = (
    "password", "passwd", "secret", "token", "api_key", "apikey", "private_key",
    "access_key", "credential", "ssn", "social_security", "card_number", "card_no",
    "cardno", "pan", "cvv", "cvc", "iban", "swift", "auth", "session", "cookie",
    "salt", "hash",
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(r"\b\+?\d[\d\s().-]{7,}\d\b")
# long hex / base64-ish secrets (>= 24 chars, no spaces)
_SECRETISH = re.compile(r"\b[A-Za-z0-9+/=_-]{24,}\b")


def is_sensitive_column(column_name: str) -> bool:
    name = (column_name or "").lower()
    return any(tok in name for tok in SENSITIVE_COLUMN_TOKENS)


def redact_value(value: str) -> str:
    if not value:
        return value
    s = str(value)
    s = _JWT.sub("[redacted-jwt]", s)
    s = _EMAIL.sub("[redacted-email]", s)
    s = _CARD.sub("[redacted-card]", s)
    s = _PHONE.sub("[redacted-phone]", s)
    s = _SECRETISH.sub("[redacted-secret]", s)
    return s


def scrub_distinct_values(column_name: str, values: list, *, enabled: bool = True) -> list:
    if not enabled:
        return values
    if is_sensitive_column(column_name):
        return [f"[redacted: {len(values)} values]"]
    return [redact_value(str(v)) for v in values]


def scrub_sample_json(sample_json: str, *, enabled: bool = True) -> str:
    if not enabled or not sample_json:
        return sample_json
    try:
        rows = json.loads(sample_json)
    except (json.JSONDecodeError, TypeError):
        return redact_value(sample_json)
    if not isinstance(rows, list):
        return redact_value(sample_json)
    cleaned = []
    for row in rows:
        if isinstance(row, dict):
            cleaned.append(
                {
                    k: ("[redacted]" if is_sensitive_column(str(k))
                        else (redact_value(v) if isinstance(v, str) else v))
                    for k, v in row.items()
                }
            )
        else:
            cleaned.append(redact_value(row) if isinstance(row, str) else row)
    return json.dumps(cleaned, default=str)


def scrub_row_cells(columns: list[str], rows: list[list], *, enabled: bool = True) -> list[list]:
    if not enabled:
        return rows
    sensitive_idx = {i for i, c in enumerate(columns) if is_sensitive_column(str(c))}
    out: list[list] = []
    for row in rows:
        new_row = []
        for i, cell in enumerate(row):
            if i in sensitive_idx:
                new_row.append("[redacted]")
            elif isinstance(cell, str):
                new_row.append(redact_value(cell))
            else:
                new_row.append(cell)
        out.append(new_row)
    return out
```

- [ ] **Step 4: Run tests — expect PASS**, then ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge/pii_scrubber.py backend/tests/unit/knowledge/test_pii_scrubber.py
git commit -m "security(sync): add pii_scrubber (denylist + value redaction) for LLM egress (H6)"
```

---

## Task T3: `sync_budget.py` (H5)

**Files:**
- Create: `backend/app/services/sync_budget.py`
- Test: `backend/tests/unit/services/test_sync_budget.py`

**Interfaces — Consumes:** `UsageService.check_token_budget(db, user_id) -> str | None`; `DbUsageSink(user_id=…, project_id=…)`; `Project.owner_id`; `settings.sync_budget_enforcement_enabled`.
**Produces** (spec §5.10):
- `resolve_owner_user_id(session, project_id) -> str | None`
- `build_sink(owner_user_id, project_id) -> DbUsageSink`
- `preflight_owner_budget(session, project_id) -> tuple[bool, str | None, str | None]` → `(ok, reason, owner_user_id)`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/services/test_sync_budget.py
import pytest
from app.services import sync_budget


class _FakeProject:
    def __init__(self, owner_id):
        self.owner_id = owner_id


@pytest.fixture
def patch_owner(monkeypatch):
    def _set(owner):
        async def _resolve(session, project_id):
            return owner
        monkeypatch.setattr(sync_budget, "resolve_owner_user_id", _resolve)
    return _set


async def test_preflight_disabled_always_ok(monkeypatch, patch_owner):
    monkeypatch.setattr(sync_budget.settings, "sync_budget_enforcement_enabled", False)
    patch_owner("u1")
    ok, reason, owner = await sync_budget.preflight_owner_budget(None, "p1")
    assert ok is True and reason is None and owner == "u1"


async def test_preflight_blocks_when_budget_message(monkeypatch, patch_owner):
    monkeypatch.setattr(sync_budget.settings, "sync_budget_enforcement_enabled", True)
    patch_owner("u1")

    async def _budget(db, user_id):
        return "daily token budget exhausted"

    monkeypatch.setattr(sync_budget._usage_svc, "check_token_budget", _budget)
    ok, reason, owner = await sync_budget.preflight_owner_budget(None, "p1")
    assert ok is False and "budget" in reason and owner == "u1"


async def test_preflight_owner_missing(monkeypatch):
    monkeypatch.setattr(sync_budget.settings, "sync_budget_enforcement_enabled", True)

    async def _resolve(session, project_id):
        return None

    monkeypatch.setattr(sync_budget, "resolve_owner_user_id", _resolve)
    ok, reason, owner = await sync_budget.preflight_owner_budget(None, "p1")
    assert ok is False and owner is None
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

- [ ] **Step 3: Implement `sync_budget.py`**

```python
"""Owner-attributed budget gate + usage sink for the code↔DB sync pipeline (H5)."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.usage_sink import DbUsageSink
from app.models.project import Project
from app.services.usage_service import UsageService

logger = logging.getLogger(__name__)
_usage_svc = UsageService()


async def resolve_owner_user_id(session: AsyncSession, project_id: str) -> str | None:
    row = await session.execute(select(Project.owner_id).where(Project.id == project_id))
    return row.scalar_one_or_none()


def build_sink(owner_user_id: str, project_id: str) -> DbUsageSink:
    return DbUsageSink(user_id=owner_user_id, project_id=project_id)


async def preflight_owner_budget(
    session: AsyncSession, project_id: str
) -> tuple[bool, str | None, str | None]:
    owner_id = await resolve_owner_user_id(session, project_id)
    if not owner_id:
        return False, "project owner not found", None
    if not settings.sync_budget_enforcement_enabled:
        return True, None, owner_id
    msg = await _usage_svc.check_token_budget(session, owner_id)
    if msg:
        return False, msg, owner_id
    return True, None, owner_id
```

- [ ] **Step 4: Run tests — expect PASS**, ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/services/sync_budget.py backend/tests/unit/services/test_sync_budget.py
git commit -m "feat(sync): owner-attributed budget pre-flight + usage sink helper (H5)"
```

---

# WAVE 2 — Data correctness

## Task T4: Analyzer — `table_name` echo, name reconciliation, robust confidence, fallback marker (H2, H3, H4)

**Files:**
- Modify: `backend/app/knowledge/code_db_sync_analyzer.py`
- Test: `backend/tests/unit/knowledge/test_code_db_sync_analyzer.py` (add tests)

**Interfaces — Produces:** `TableSyncAnalysis.is_fallback: bool`; `SYNC_ANALYSIS_TOOL` with first param `table_name`; `analyze_table_batch` reconciling by `args["table_name"]`.
**Consumes:** nothing new.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/knowledge/test_code_db_sync_analyzer.py  (append)
import pytest
from app.knowledge.code_db_sync_analyzer import CodeDbSyncAnalyzer, TableSyncAnalysis
from app.llm.base import LLMResponse, ToolCall


class _Router:
    def __init__(self, calls):
        self._calls = calls

    async def complete(self, **kwargs):
        return LLMResponse(tool_calls=self._calls)


def _tc(table_name, conf=4, status="matched"):
    return ToolCall(id="x", name="table_sync_analysis", arguments={
        "table_name": table_name, "sync_status": status, "confidence_score": conf,
        "required_filters": "{}", "column_value_mappings": "{}",
    })


async def test_batch_reconciles_by_name_not_position():
    tables = [("orders", "", ""), ("payments", "", "")]
    # LLM returns them REVERSED
    analyzer = CodeDbSyncAnalyzer(_Router([_tc("payments"), _tc("orders")]))
    out = await analyzer.analyze_table_batch(tables)
    by_name = {a.table_name: a for a in out}
    assert by_name["orders"].sync_status == "matched"
    assert by_name["payments"].sync_status == "matched"
    assert not by_name["orders"].is_fallback


async def test_batch_unknown_name_dropped_and_missing_filled_with_fallback():
    tables = [("orders", "", ""), ("payments", "", "")]
    analyzer = CodeDbSyncAnalyzer(_Router([_tc("orders"), _tc("ghost_table")]))
    out = await analyzer.analyze_table_batch(tables)
    by_name = {a.table_name: a for a in out}
    assert len(out) == 2
    assert by_name["payments"].is_fallback is True   # never returned by LLM
    assert by_name["orders"].is_fallback is False


async def test_batch_bad_confidence_only_degrades_that_table():
    tables = [("orders", "", ""), ("payments", "", "")]
    bad = _tc("orders"); bad.arguments["confidence_score"] = "4.5"
    analyzer = CodeDbSyncAnalyzer(_Router([bad, _tc("payments", conf=5)]))
    out = await analyzer.analyze_table_batch(tables)
    by_name = {a.table_name: a for a in out}
    assert by_name["orders"].confidence_score == 3   # coerced, not fallback
    assert by_name["orders"].is_fallback is False
    assert by_name["payments"].confidence_score == 5


async def test_fallback_marked():
    a = CodeDbSyncAnalyzer._fallback_analysis("t")
    assert a.is_fallback is True and a.confidence_score == 1
```

- [ ] **Step 2: Run — expect FAIL.**

`cd backend && .venv/bin/pytest tests/unit/knowledge/test_code_db_sync_analyzer.py -k "reconcile or unknown_name or bad_confidence or fallback_marked" -v`

- [ ] **Step 3: Edit `TableSyncAnalysis`** — add field (after `confidence_score: int = 3`):

```python
    is_fallback: bool = False
```

- [ ] **Step 4: Add `table_name` as the FIRST `ToolParameter` in `SYNC_ANALYSIS_TOOL`** (before `data_format_notes`):

```python
        ToolParameter(
            name="table_name",
            type="string",
            description=(
                "The EXACT table name being analyzed, copied verbatim from the "
                "'## Table: <name>' header. Required so results map to the right table."
            ),
        ),
```

- [ ] **Step 5: Add a module-level coercion helper** (near `_clamp_sync_status`):

```python
def _coerce_confidence(raw) -> int:
    try:
        return max(1, min(5, int(float(raw))))
    except (TypeError, ValueError):
        return 3
```

- [ ] **Step 6: Update `_fallback_analysis`** to set the marker:

```python
    @staticmethod
    def _fallback_analysis(table_name: str) -> TableSyncAnalysis:
        return TableSyncAnalysis(
            table_name=table_name,
            sync_status="unknown",
            confidence_score=1,
            data_format_notes="LLM analysis unavailable — using fallback.",
            is_fallback=True,
        )
```

- [ ] **Step 7: Replace `analyze_table_batch` body** (lines ~266-315) with name-reconciled version:

```python
        results_by_name: dict[str, TableSyncAnalysis] = {}
        by_name = {t[0].lower(): t[0] for t in tables}
        try:
            resp = await self._llm.complete(
                messages=messages, tools=[SYNC_ANALYSIS_TOOL],
                preferred_provider=preferred_provider, model=model,
                temperature=0.0, max_tokens=4096,
            )
            for tc in resp.tool_calls:
                if tc.name != "table_sync_analysis":
                    continue
                args = tc.arguments
                raw_name = str(args.get("table_name", "")).lower()
                canonical = by_name.get(raw_name)
                if canonical is None:
                    logger.warning("batch sync: tool call for unknown table %r — dropped",
                                   args.get("table_name"))
                    continue
                if canonical in results_by_name:
                    logger.warning("batch sync: duplicate analysis for %s — keeping first",
                                   canonical)
                    continue
                col_notes = args.get("column_sync_notes", "{}")
                if isinstance(col_notes, dict):
                    col_notes = json.dumps(col_notes)
                results_by_name[canonical] = TableSyncAnalysis(
                    table_name=canonical,
                    data_format_notes=args.get("data_format_notes", ""),
                    column_sync_notes_json=col_notes,
                    business_logic_notes=args.get("business_logic_notes", ""),
                    conversion_warnings=args.get("conversion_warnings", ""),
                    query_recommendations=args.get("query_recommendations", ""),
                    required_filters_json=args.get("required_filters", "{}"),
                    column_value_mappings_json=args.get("column_value_mappings", "{}"),
                    sync_status=_clamp_sync_status(args.get("sync_status", "unknown")),
                    confidence_score=_coerce_confidence(args.get("confidence_score", 3)),
                )
        except Exception:
            logger.warning("Batch sync analysis failed", exc_info=True)

        out: list[TableSyncAnalysis] = []
        fallback_count = 0
        for name, _db, _code in tables:
            if name in results_by_name:
                out.append(results_by_name[name])
            else:
                out.append(self._fallback_analysis(name))
                fallback_count += 1
        if fallback_count:
            logger.info("LLM sync batch: %d/%d used fallback", fallback_count, len(tables))
        return out
```

- [ ] **Step 8: Update `analyze_table`** single-path to use `_coerce_confidence` (replace the `confidence_score=max(1, min(5, int(...)))` line):

```python
                    confidence_score=_coerce_confidence(args.get("confidence_score", 3)),
```

- [ ] **Step 9: Run tests — expect PASS.** Re-run the full analyzer test file to confirm no regression:

`cd backend && .venv/bin/pytest tests/unit/knowledge/test_code_db_sync_analyzer.py -v` → all PASS. ruff/mypy.

- [ ] **Step 10: Commit**

```bash
git add backend/app/knowledge/code_db_sync_analyzer.py backend/tests/unit/knowledge/test_code_db_sync_analyzer.py
git commit -m "fix(sync): reconcile batch analyses by table_name + robust confidence + fallback marker (H2,H3,H4)"
```

---

## Task T5: Pipeline — schema-qualified identity, all-fallback guard, scrub, budget wiring, store-by-name, truncation markers (H2-store, M2, H4, H6, H5, L4)

**Files:**
- Modify: `backend/app/knowledge/code_db_sync_pipeline.py`
- Modify: `backend/app/knowledge/graph_db_bridge.py` (M7)
- Test: `backend/tests/unit/knowledge/test_code_db_sync_pipeline_run.py` (create), `backend/tests/unit/knowledge/test_graph_db_bridge.py` (add M7 test)

**Interfaces — Consumes:** `pii_scrubber` (T2), `sync_budget` (T3), analyzer `is_fallback` (T4), `settings.*` (T1).
**Produces:** scrubbed `_build_db_context`; pipeline `run()` budget-gated; store keyed by self-identified name.

- [ ] **Step 1: Write failing tests** (focus on the all-fallback guard + schema-qualified match + scrub call — pure-ish units)

```python
# backend/tests/unit/knowledge/test_code_db_sync_pipeline_run.py
import json
import pytest
from app.knowledge.code_db_sync_pipeline import CodeDbSyncPipeline
from app.knowledge.code_db_sync_analyzer import TableSyncAnalysis


class _DbEntry:
    def __init__(self, name, schema="public"):
        self.table_name = name
        self.table_schema = schema
        self.business_description = ""
        self.row_count = None
        self.column_count = 0
        self.data_patterns = ""
        self.query_hints = ""
        self.column_notes_json = "{}"
        self.column_distinct_values_json = json.dumps({"email": ["a@b.com", "c@d.com"]})
        self.sample_data_json = json.dumps([{"email": "a@b.com"}])


def test_build_db_context_scrubs_when_enabled():
    ctx = CodeDbSyncPipeline._build_db_context(_DbEntry("users"), scrub=True)
    assert "a@b.com" not in ctx
    assert "[redacted: 2 values]" in ctx or "redacted" in ctx


def test_build_db_context_omits_when_send_disabled():
    # scrub=False path used by run() when connection opted out → caller omits;
    # here we assert raw passes through when scrubbing globally off:
    ctx = CodeDbSyncPipeline._build_db_context(_DbEntry("logs"), scrub=False)
    assert "a@b.com" in ctx  # raw allowed only when scrubbing disabled & sending allowed


def test_distinct_truncation_marker():
    e = _DbEntry("t")
    e.column_distinct_values_json = json.dumps({"k": [str(i) for i in range(20)]})
    ctx = CodeDbSyncPipeline._build_db_context(e, scrub=True)
    assert "+5 more" in ctx


def test_all_fallback_guard_helper():
    analyses = [TableSyncAnalysis(table_name="a", is_fallback=True),
                TableSyncAnalysis(table_name="b", is_fallback=True)]
    total = len(analyses)
    non_fb = sum(1 for a in analyses if not a.is_fallback)
    assert (non_fb / total) < 0.5  # guard would trip
```

- [ ] **Step 2: Run — expect FAIL** (`_build_db_context` has no `scrub` param yet).

- [ ] **Step 3: Edit `_build_db_context`** — add `scrub: bool` param and route through `pii_scrubber`, add truncation markers (L4):

```python
    @staticmethod
    def _build_db_context(entry: DbIndex, *, scrub: bool = True) -> str:
        from app.knowledge import pii_scrubber
        parts: list[str] = []
        if entry.business_description:
            parts.append(f"Description: {entry.business_description}")
        if entry.row_count is not None:
            parts.append(f"Rows: ~{entry.row_count:,}")
        if entry.column_count:
            parts.append(f"Column count: {entry.column_count}")
        if entry.data_patterns:
            parts.append(f"Data patterns: {entry.data_patterns}")
        if entry.query_hints:
            parts.append(f"Query hints: {entry.query_hints}")
        if entry.column_notes_json and entry.column_notes_json != "{}":
            try:
                notes = json.loads(entry.column_notes_json)
                if notes:
                    parts.append("Column notes:")
                    for col, note in notes.items():
                        parts.append(f"  {col}: {note}")
            except (json.JSONDecodeError, TypeError):
                pass
        dv_json = getattr(entry, "column_distinct_values_json", None) or "{}"
        if dv_json and dv_json != "{}":
            try:
                distinct = json.loads(dv_json)
                if distinct:
                    parts.append("Actual distinct values in DB:")
                    for col, vals in distinct.items():
                        shown = pii_scrubber.scrub_distinct_values(col, vals[:15], enabled=scrub)
                        vals_str = " | ".join(str(v) for v in shown)
                        more = f" (+{len(vals) - 15} more)" if len(vals) > 15 else ""
                        parts.append(f"  {col}: [{vals_str}]{more}")
            except (json.JSONDecodeError, TypeError):
                pass
        if entry.sample_data_json and entry.sample_data_json != "[]":
            sample = pii_scrubber.scrub_sample_json(entry.sample_data_json, enabled=scrub)
            suffix = "…[truncated]" if len(sample) > 800 else ""
            parts.append(f"Sample data: {sample[:800]}{suffix}")
        return "\n".join(parts)
```

> **Note:** `_build_db_context` is called inside `_match_tables`. Add a `scrub` field to `_MatchedTable`? No — `_build_db_context` is called directly in `_match_tables` (line ~430). Thread `scrub` into `_match_tables(..., scrub: bool)` and pass to `_build_db_context`. The `run()` method computes `scrub` (Step 6 below) and passes it to `_match_tables`.

- [ ] **Step 4: Thread `scrub` and schema-qualified identity into `_match_tables`** (M2). Replace the `db_table_names`/`entity_by_table` construction and the per-table loop key with schema-aware logic:

```python
    def _match_tables(
        self,
        knowledge: ProjectKnowledge,
        db_entries: list[DbIndex],
        rules_context: str = "",
        *,
        scrub: bool = True,
    ) -> list[_MatchedTable]:
        from collections import Counter
        results: list[_MatchedTable] = []
        db_by_key: dict[tuple[str, str], DbIndex] = {}
        bare_counts: Counter = Counter()
        for e in db_entries:
            sch = (getattr(e, "table_schema", None) or "public").lower()
            nm = e.table_name.lower()
            db_by_key[(sch, nm)] = e
            bare_counts[nm] += 1

        def _display_name(e: DbIndex) -> str:
            if bare_counts[e.table_name.lower()] > 1:
                return f"{getattr(e, 'table_schema', 'public') or 'public'}.{e.table_name}"
            return e.table_name

        entity_by_table: dict[str, EntityInfo] = {}
        code_table_names: set[str] = set()
        for _, entity in knowledge.entities.items():
            if entity.table_name:
                entity_by_table[entity.table_name.lower()] = entity
                code_table_names.add(entity.table_name.lower())
        for tbl_name in knowledge.table_usage:
            code_table_names.add(tbl_name.lower())

        # DB-side first (schema-qualified), then code-only tables with no DB row.
        seen_bare: set[str] = set()
        for (sch, nm), db_entry in sorted(db_by_key.items()):
            seen_bare.add(nm)
            entity = entity_by_table.get(nm)
            usage = knowledge.table_usage.get(nm) or knowledge.table_usage.get(
                next((k for k in knowledge.table_usage if k.lower() == nm), "")
            )
            ambiguous = bare_counts[nm] > 1
            display = _display_name(db_entry)
            code_context = self._build_code_context(entity, usage, knowledge, nm, rules_context)
            if ambiguous:
                code_context = (
                    f"(NOTE: table name '{nm}' exists in multiple schemas; matched code by "
                    f"bare name — verify schema '{sch}')\n" + code_context
                )
            results.append(self._make_matched(
                display, self._build_db_context(db_entry, scrub=scrub), code_context,
                entity, usage, knowledge,
            ))

        for nm in sorted(code_table_names - seen_bare):
            entity = entity_by_table.get(nm)
            usage = knowledge.table_usage.get(nm) or knowledge.table_usage.get(
                next((k for k in knowledge.table_usage if k.lower() == nm), "")
            )
            code_context = self._build_code_context(entity, usage, knowledge, nm, rules_context)
            results.append(self._make_matched(nm, "", code_context, entity, usage, knowledge))
        return results
```

- [ ] **Step 5: Extract the `_MatchedTable` builder** (`_make_matched`) so both branches share it (DRY) — add this method (moves the `mt = _MatchedTable(...)` + json blocks from the old loop):

```python
    @staticmethod
    def _make_matched(table_name, db_context, code_context, entity, usage, knowledge):
        has_code = bool(entity or (usage and usage.is_active))
        mt = _MatchedTable(
            table_name=table_name, db_context=db_context, code_context=code_context,
            has_code_info=has_code,
            entity_name=entity.name if entity else None,
            entity_file_path=entity.file_path if entity else None,
            read_count=len(usage.readers) if usage else 0,
            write_count=len(usage.writers) if usage else 0,
        )
        if entity and entity.columns:
            mt.code_columns_json = json.dumps(
                [{"name": c.name, "type": c.col_type, "fk_target": c.fk_target}
                 for c in entity.columns]
            )
        if usage:
            all_files = list(set(usage.readers + usage.writers + usage.orm_refs))
            mt.used_in_files_json = json.dumps(all_files[:20])
        return mt
```

- [ ] **Step 6: Edit `run()`** — compute `scrub`, budget pre-flight + sink, pass `scrub` to `_match_tables`, all-fallback guard, mid-run summary skip. At the top of `run()` after `wf_id` is set:

```python
        # H5: owner budget pre-flight + per-run usage sink.
        from app.services.sync_budget import build_sink, preflight_owner_budget
        if settings.sync_budget_enforcement_enabled:
            async with async_session_factory() as s:
                ok, reason, owner_id = await preflight_owner_budget(s, project_id)
            if not ok:
                async with async_session_factory() as s:
                    await self._sync_svc.set_sync_status(s, connection_id, "failed")
                    await s.commit()
                await self._tracker.end(wf_id, "code_db_sync", "failed", reason or "budget")
                return {"status": "failed", "error": reason, "budget_blocked": True,
                        "workflow_id": wf_id}
            if owner_id:
                self._llm = LLMRouter(usage_sink=build_sink(owner_id, project_id))
                self._analyzer = CodeDbSyncAnalyzer(self._llm)

        # H6: per-connection opt-out + global scrub flag.
        scrub_send = True
        async with async_session_factory() as s:
            from app.models.connection import Connection
            conn = await s.get(Connection, connection_id)
            send = getattr(conn, "send_sample_data_to_llm", True) if conn else True
        scrub = settings.sync_pii_scrubbing_enabled and send
        # When send is False we omit samples entirely by passing empty contexts:
        self._omit_samples = not send
```

Replace the `_match_tables(...)` call (Step 3, line ~149) to pass scrub:

```python
                    matched_tables = self._match_tables(
                        knowledge, db_entries, rules_context,
                        scrub=(scrub and not self._omit_samples),
                    )
```

> When `send is False`, `_build_db_context` must omit sample+distinct entirely. Implement by guarding inside `_build_db_context`: pass `scrub=False, omit=self._omit_samples`. Simpler: add `omit_samples: bool = False` param to `_build_db_context` and `_match_tables`; when True, skip the distinct/sample blocks. Add the param and the two `if not omit_samples:` guards around the distinct and sample blocks.

- [ ] **Step 7: All-fallback guard** — after Step 4 builds `analyses`, before Step 5 store block:

```python
                total = len(analyses)
                non_fallback = sum(1 for a in analyses if not a.is_fallback)
                if total and (non_fallback / total) < settings.sync_min_success_ratio_to_persist:
                    logger.warning(
                        "CODE_DB_SYNC kept previous rows: only %d/%d tables analyzed",
                        non_fallback, total,
                    )
                    async with async_session_factory() as session:
                        await self._sync_svc.set_sync_status(session, connection_id, "failed")
                        await session.commit()
                    await self._tracker.end(
                        wf_id, "code_db_sync", "failed",
                        f"LLM degraded: {non_fallback}/{total} analyzed; kept previous sync",
                    )
                    return {"status": "failed", "error": "llm_degraded_kept_previous",
                            "workflow_id": wf_id}
```

- [ ] **Step 8: Mid-run summary skip** — wrap the Step-6 `generate_summary` call:

```python
                    sink = getattr(self._llm, "_sink", None)
                    if sink is not None and sink.budget_exceeded():
                        summary_result = SyncSummaryResult()  # skip LLM summary
                    else:
                        summary_result = await self._analyzer.generate_summary(...)  # unchanged args
```

(Import `SyncSummaryResult` from the analyzer module at top of file.)

- [ ] **Step 9: Store-by-name guard** (H2) — in the Step 5 loop, before building `sync_data`:

```python
                            mt = mt_lookup.get(analysis.table_name)
                            if mt is None:
                                logger.warning("store_sync: no matched table for %s — skipped",
                                               analysis.table_name)
                                continue
```

(and drop the `if mt else …` ternaries since `mt` is now guaranteed.)

- [ ] **Step 10: M7 graph_db_bridge** — move over-broad verbs to ambiguous + label op_kind heuristic. In `graph_db_bridge.py`:
  - Add `_AMBIGUOUS_VERBS = ("process_", "handle_", "sync_", "set_", "add_", "register_")` and remove those six from `_WRITE_VERBS`.
  - In `classify_op_kind`, after the write/read checks, `for verb in _AMBIGUOUS_VERBS: if name.startswith(verb): return "unknown"`.
  - In `code_db_sync_pipeline._build_code_context` (the `Code callers` block, line ~558), change the printed line to drop fabricated depth and mark heuristic:

```python
                    parts.append(f"  - {name} ({op}, conf={conf:.2f}, heuristic) in {file_}")
```

  Add test `test_ambiguous_verbs_not_write` in `test_graph_db_bridge.py`:

```python
def test_ambiguous_verbs_classified_unknown():
    from app.knowledge.graph_db_bridge import classify_op_kind
    class _S:
        name = "process_report"; decorators = ()
    assert classify_op_kind(_S()) == "unknown"
```

- [ ] **Step 11: Run all pipeline + bridge tests — expect PASS**; ruff/mypy.

`cd backend && .venv/bin/pytest tests/unit/knowledge/test_code_db_sync_pipeline_run.py tests/unit/knowledge/test_graph_db_bridge.py -v`

- [ ] **Step 12: Commit**

```bash
git add backend/app/knowledge/code_db_sync_pipeline.py backend/app/knowledge/graph_db_bridge.py backend/tests/unit/knowledge/test_code_db_sync_pipeline_run.py backend/tests/unit/knowledge/test_graph_db_bridge.py
git commit -m "fix(sync): schema-qualified identity, all-fallback guard, PII scrub, budget wiring, op_kind heuristic label (M2,H4,H6,H5,H2,M7,L4)"
```

---

## Task T6: `code_db_sync_service` — enrichment validation/deep-merge, header gating (M6, L2)

**Files:**
- Modify: `backend/app/services/code_db_sync_service.py`
- Test: `backend/tests/unit/services/test_code_db_sync_service.py` (add tests)

**Interfaces — Produces:** safe `add_runtime_enrichment`; `sync_to_prompt_context` neutral header for non-completed.

- [ ] **Step 1: Failing tests**

```python
# append to backend/tests/unit/services/test_code_db_sync_service.py
async def test_enrichment_rejects_metadata_keys_in_required_filters(db_session, seed_sync_row):
    svc = CodeDbSyncService()
    await svc.add_runtime_enrichment(db_session, conn_id, "orders",
        "required_filters_json", '{"source": "investigation", "filter": "x"}')
    row = await svc.get_table_sync(db_session, conn_id, "orders")
    import json
    assert json.loads(row.required_filters_json) == {}  # metadata keys dropped


async def test_enrichment_deep_merges_value_mappings(db_session, seed_sync_row):
    svc = CodeDbSyncService()
    # seed: {"status": {"0": "pending", "1": "processed"}}
    await svc.add_runtime_enrichment(db_session, conn_id, "orders",
        "column_value_mappings_json", '{"status": {"2": "failed"}}')
    row = await svc.get_table_sync(db_session, conn_id, "orders")
    import json
    assert json.loads(row.column_value_mappings_json)["status"] == {
        "0": "pending", "1": "processed", "2": "failed"}
```

(`seed_sync_row` fixture: upsert one `orders` row with the seed mappings; reuse the conftest helpers.)

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Edit `add_runtime_enrichment`** — replace the `mergeable_json_fields` branch:

```python
        if field == "required_filters_json":
            existing_json = self._safe_load_dict(getattr(entry, field, None))
            new_data = self._safe_load_dict(value)
            _META = {"source", "filter", "_meta"}
            for col, cond in new_data.items():
                if col in _META or not isinstance(cond, str):
                    continue  # only {column: condition_string} pairs are valid filters
                existing_json[col] = cond
            setattr(entry, field, json.dumps(existing_json))
        elif field == "column_value_mappings_json":
            existing_json = self._safe_load_dict(getattr(entry, field, None))
            new_data = self._safe_load_dict(value)
            for col, mapping in new_data.items():
                if isinstance(mapping, dict) and isinstance(existing_json.get(col), dict):
                    existing_json[col].update(mapping)  # deep-merge per column
                else:
                    existing_json[col] = mapping
            setattr(entry, field, json.dumps(existing_json))
        elif field in appendable_text_fields:
            existing_lines = [ln.strip() for ln in (getattr(entry, field, "") or "").split("\n")]
            if value.strip() not in existing_lines:
                combined = f"{getattr(entry, field, '') or ''}\n{value}".strip()
                setattr(entry, field, combined[-8000:])  # cap growth (keep newest)
        else:
            return None
```

Add the helper:

```python
    @staticmethod
    def _safe_load_dict(raw) -> dict:
        if not raw:
            return {}
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
```

(Remove the now-unused `mergeable_json_fields` set; keep `appendable_text_fields`.)

- [ ] **Step 4: L2 header gating** — in `sync_to_prompt_context`, replace the header block:

```python
        status = getattr(summary, "sync_status", None) if summary else None
        if summary and summary.synced_at and status in ("completed", "stale"):
            parts.append(f"## Code-DB Sync (analyzed {summary.synced_at.strftime('%Y-%m-%d %H:%M')})\n")
        else:
            parts.append("## Code-DB Sync\n")
```

- [ ] **Step 5: Run tests — expect PASS**; ruff/mypy.
- [ ] **Step 6: Commit**

```bash
git add backend/app/services/code_db_sync_service.py backend/tests/unit/services/test_code_db_sync_service.py
git commit -m "fix(sync): validate required_filters payload, deep-merge value mappings, gate prompt header (M6,L2)"
```

---

## Task T7: SQL agent — confidence gate on enforced filters (H4)

**Files:**
- Modify: `backend/app/agents/sql_agent.py` (`_load_required_filters_by_table` ~1543, `_load_sync_filters_and_mappings` ~1502)
- Test: `backend/tests/unit/agents/test_sql_agent_required_filters.py` (add or create)

**Interfaces — Consumes:** `settings.sync_min_confidence_to_enforce_filters`, `CodeDbSync.confidence_score`.

- [ ] **Step 1: Failing test**

```python
# backend/tests/unit/agents/test_sql_agent_required_filters.py
async def test_low_confidence_filters_not_enforced(monkeypatch, sql_agent, conn_cfg, seed_entries):
    # seed: table "orders" required_filters {"status":"=1"} confidence_score=1
    monkeypatch.setattr("app.config.settings.sync_min_confidence_to_enforce_filters", 2)
    out = await sql_agent._load_required_filters_by_table(conn_cfg)
    assert "orders" not in out  # confidence 1 < 2 → skipped
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Add the confidence gate** in `_load_required_filters_by_table` (the loop over sync entries):

```python
        from app.config import settings
        min_conf = settings.sync_min_confidence_to_enforce_filters
        for sync_entry in entries:
            if (getattr(sync_entry, "confidence_score", 0) or 0) < min_conf:
                continue
            raw = getattr(sync_entry, "required_filters_json", "{}") or "{}"
            ...
```

And the same `if confidence < min_conf: continue` guard in `_load_sync_filters_and_mappings` (the `for e in entries:` loop, before reading `rf`).

- [ ] **Step 4: Run test — expect PASS**; ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/sql_agent.py backend/tests/unit/agents/test_sql_agent_required_filters.py
git commit -m "fix(sync): do not enforce SQL required-filters from low-confidence/fallback rows (H4)"
```

---

## Task T8: DB-index subsystem — is_indexed whitelist, get_index_age None-guard, schema-qualified uniqueness, db-index LLM scrub (H7, M9, M2, H6-db-egress)

**Files:**
- Modify: `backend/app/services/db_index_service.py` (`is_indexed` ~164, `get_index_age` ~178, `upsert_table` ~25, `delete_stale_tables` ~79)
- Modify: `backend/app/models/db_index.py` (`__table_args__`)
- Modify: `backend/app/knowledge/db_index_pipeline.py` (store block ~652 caller; pass `scrub` into validator)
- Modify: `backend/app/knowledge/db_index_validator.py` (`analyze_table`/`analyze_table_batch`/`_build_table_prompt` add `scrub`)
- Create: `backend/alembic/versions/<rev3>_sync_remediation_schema_qualified_uniqueness.py`
- Test: `backend/tests/unit/services/test_db_index_service.py` (add)

**Interfaces — Consumes:** `pii_scrubber` (T2). **Produces:** schema-aware `upsert_table` / `delete_stale_tables(connection_id, current_keys: set[str])` where keys are `f"{schema}.{name}"`.

- [ ] **Step 1: Failing tests**

```python
# append to backend/tests/unit/services/test_db_index_service.py
async def test_is_indexed_false_for_failed_only(db_session):
    svc = DbIndexService()
    await svc.set_indexing_status(db_session, "c1", "running")
    await svc.set_indexing_status(db_session, "c1", "failed")
    await db_session.commit()
    assert await svc.is_indexed(db_session, "c1") is False


async def test_is_indexed_true_for_completed_partial(db_session):
    svc = DbIndexService()
    await svc.set_indexing_status(db_session, "c2", "completed_partial")
    await db_session.commit()
    assert await svc.is_indexed(db_session, "c2") is True


async def test_get_index_age_none_when_indexed_at_null(db_session, summary_with_null_indexed_at):
    svc = DbIndexService()
    assert await svc.get_index_age(db_session, "c3") is None  # no AttributeError
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Fix `is_indexed`** (spec §5.9a):

```python
    async def is_indexed(self, session, connection_id) -> bool:
        summary = await self.get_summary(session, connection_id)
        if not summary:
            return False
        status = (getattr(summary, "indexing_status", "idle") or "idle")
        if status not in ("completed", "completed_partial"):
            return False
        return summary.indexed_at is not None
```

- [ ] **Step 4: Fix `get_index_age`** None-guard:

```python
        indexed_at = summary.indexed_at
        if indexed_at is None:
            return None
        if indexed_at.tzinfo is None:
            indexed_at = indexed_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - indexed_at
```

- [ ] **Step 5: Schema-aware `upsert_table`** — match on `(connection_id, table_schema, table_name)`:

```python
        table_name = table_data["table_name"]
        table_schema = table_data.get("table_schema", "public")
        result = await session.execute(
            select(DbIndex).where(
                DbIndex.connection_id == connection_id,
                DbIndex.table_schema == table_schema,
                DbIndex.table_name == table_name,
            )
        )
```

- [ ] **Step 6: Schema-aware `delete_stale_tables`** — keys are `f"{schema}.{name}"`, implemented via fetch-ids-then-delete (portable, 2 queries):

```python
    async def delete_stale_tables(
        self, session, connection_id, current_keys: set[str]
    ) -> int:
        rows = (await session.execute(
            select(DbIndex.id, DbIndex.table_schema, DbIndex.table_name)
            .where(DbIndex.connection_id == connection_id)
        )).all()
        stale_ids = [
            rid for rid, sch, nm in rows
            if f"{(sch or 'public')}.{nm}" not in current_keys
        ]
        if not stale_ids:
            return 0
        await session.execute(delete(DbIndex).where(DbIndex.id.in_(stale_ids)))
        await session.flush()
        return len(stale_ids)
```

- [ ] **Step 7: Update the db_index_pipeline caller** (`db_index_pipeline.py:652`):

```python
                        current_keys = {
                            f"{(t.schema or 'public')}.{t.name}" for t in schema.tables
                        }
                        deleted = await self._svc.delete_stale_tables(
                            session, connection_id, current_keys
                        )
```

- [ ] **Step 8: Model constraint** (`db_index.py`) — replace `uq_db_index_conn_table`:

```python
    __table_args__ = (
        UniqueConstraint("connection_id", "table_schema", "table_name",
                         name="uq_db_index_conn_schema_table"),
    )
```

- [ ] **Step 9: Migration `<rev3>`** — generate then hand-edit to drop+create (guarded for SQLite batch):

```bash
cd backend && PYTHONPATH=. .venv/bin/alembic revision -m "sync_remediation_schema_qualified_uniqueness"
```

Body:

```python
def upgrade() -> None:
    with op.batch_alter_table("db_index") as b:
        b.drop_constraint("uq_db_index_conn_table", type_="unique")
        b.create_unique_constraint(
            "uq_db_index_conn_schema_table",
            ["connection_id", "table_schema", "table_name"],
        )

def downgrade() -> None:
    with op.batch_alter_table("db_index") as b:
        b.drop_constraint("uq_db_index_conn_schema_table", type_="unique")
        b.create_unique_constraint("uq_db_index_conn_table",
                                   ["connection_id", "table_name"])
```

- [ ] **Step 10: db-index LLM scrub (H6 second egress)** — `db_index_validator.py`:
  - `analyze_table(self, table, sample_data, code_context, rules_context, *, scrub: bool = True, ...)` and `analyze_table_batch(..., scrub: bool = True)` thread `scrub` into `_build_table_prompt`.
  - `_build_table_prompt(self, table, sample_data, code_context, rules_context, *, scrub: bool = True)` — scrub the rows before formatting (lines ~427-434):

```python
        if sample_data and sample_data.rows:
            from app.knowledge import pii_scrubber
            rows = pii_scrubber.scrub_row_cells(sample_data.columns, sample_data.rows, enabled=scrub)
            parts.append(f"\nSample data ({len(rows)} newest rows):")
            parts.append("| " + " | ".join(sample_data.columns) + " |")
            parts.append("| " + " | ".join(["---"] * len(sample_data.columns)) + " |")
            for row in rows:
                parts.append("| " + " | ".join(str(c) for c in row) + " |")
```

  - In `db_index_pipeline.py` where `validate_tables`/`analyze_table*` are called, compute `scrub = settings.sync_pii_scrubbing_enabled and connection.send_sample_data_to_llm` (the pipeline already loads the connection config; resolve the `Connection` row once) and pass `scrub=scrub`. When `send_sample_data_to_llm` is False, pass `sample_data=None` to omit entirely.

- [ ] **Step 11: Run tests — expect PASS**; run migration up/down on a scratch SQLite (`alembic upgrade head` then `downgrade -1`); ruff/mypy.
- [ ] **Step 12: Commit**

```bash
git add backend/app/services/db_index_service.py backend/app/models/db_index.py backend/app/knowledge/db_index_pipeline.py backend/app/knowledge/db_index_validator.py backend/alembic/versions/*schema_qualified_uniqueness.py backend/tests/unit/services/test_db_index_service.py
git commit -m "fix(sync): is_indexed status whitelist, get_index_age None-guard, schema-qualified db_index, scrub db-index LLM egress (H7,M9,M2,H6)"
```

---

## Task T9: Investigation enrichment producer reroute (M6)

**Files:**
- Modify: `backend/app/api/routes/data_investigations.py` (`_enrich_sync_from_investigation` ~319-352)
- Test: `backend/tests/unit/api/test_data_investigations_enrich.py` (add or extend)

- [ ] **Step 1: Failing test** — assert a `missing_filter` investigation routes to `query_recommendations`, not `required_filters_json`:

```python
async def test_missing_filter_routes_to_recommendations(monkeypatch):
    captured = {}
    async def _fake(self, db, *, connection_id, table_name, field, value):
        captured["field"] = field; captured["value"] = value
    monkeypatch.setattr("app.services.code_db_sync_service.CodeDbSyncService.add_runtime_enrichment", _fake)
    # ... build inv with root_cause_category="missing_filter", call _enrich_sync_from_investigation
    assert captured["field"] == "query_recommendations"
    assert "[from investigation]" in captured["value"]
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Edit the `missing_filter` branch** (spec §5.6c):

```python
        if inv.root_cause_category == "missing_filter":
            await sync_svc.add_runtime_enrichment(
                db, connection_id=inv.connection_id, table_name=table,
                field="query_recommendations",
                value=f"[from investigation] {inv.root_cause}",
            )
```

- [ ] **Step 4: Run test — PASS**; ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/data_investigations.py backend/tests/unit/api/test_data_investigations_enrich.py
git commit -m "fix(sync): route investigation hints to query_recommendations not required_filters (M6)"
```

---

# WAVE 3 — Reliability / concurrency / traceability

## Task T10: RunCoordinator — IntegrityError→409 + model index parity (H8)

**Files:**
- Modify: `backend/app/services/run_coordinator.py` (`start` ~134-173; imports)
- Modify: `backend/app/models/indexing_run.py` (`__table_args__`)
- Create: `backend/alembic/versions/<rev2>_sync_remediation_indexing_run_active_index.py`
- Test: `backend/tests/unit/services/test_run_coordinator.py` (add)

- [ ] **Step 1: Failing test** — simulate a unique-violation on commit:

```python
async def test_start_translates_integrity_error_to_already_active(monkeypatch, db_session):
    from app.services.run_coordinator import RunCoordinator, RunAlreadyActiveError
    from sqlalchemy.exc import IntegrityError
    coord = RunCoordinator()
    # first run holds the slot
    await coord.start(db_session, kind="code_db_sync", project_id="p1", connection_id="c1")
    # second concurrent start must raise RunAlreadyActiveError, not IntegrityError
    with pytest.raises(RunAlreadyActiveError):
        # force the app-level check to miss so we hit the DB index:
        monkeypatch.setattr(coord, "_find_active",
                            lambda *a, **k: _async_none())
        await coord.start(db_session, kind="code_db_sync", project_id="p1", connection_id="c1")
```

(`_async_none` returns `None` first then the real row on the recovery lookup — use a small async stub returning None on the pre-check.)

- [ ] **Step 2: Run — expect FAIL** (raises `IntegrityError`).

- [ ] **Step 3: Edit `start()`** — wrap the commit (spec §5.8a):

```python
        from sqlalchemy.exc import IntegrityError
        db.add(run)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            existing = await self._find_active(db, project_id, kind, connection_id)
            raise RunAlreadyActiveError(existing.id if existing else "unknown") from exc
        await db.refresh(run)
```

- [ ] **Step 4: Model parity** (`indexing_run.py` `__table_args__`) — add (import `Index`, `text`):

```python
        Index(
            "uq_indexing_runs_active_one",
            "project_id", "kind", text("coalesce(connection_id, '')"),
            unique=True,
            sqlite_where=text("status IN ('queued','running','cancelling')"),
            postgresql_where=text("status IN ('queued','running','cancelling')"),
        ),
```

- [ ] **Step 5: Migration `<rev2>`** (idempotent parity for envs missing it):

```python
def upgrade() -> None:
    bind = op.get_bind()
    op.create_index(
        "uq_indexing_runs_active_one", "indexing_runs",
        ["project_id", "kind", sa.text("coalesce(connection_id, '')")],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running','cancelling')"),
        sqlite_where=sa.text("status IN ('queued','running','cancelling')"),
        if_not_exists=True,
    )

def downgrade() -> None:
    op.drop_index("uq_indexing_runs_active_one", table_name="indexing_runs", if_exists=True)
```

- [ ] **Step 6: Run tests — PASS**; ruff/mypy.
- [ ] **Step 7: Commit**

```bash
git add backend/app/services/run_coordinator.py backend/app/models/indexing_run.py backend/alembic/versions/*indexing_run_active_index.py backend/tests/unit/services/test_run_coordinator.py
git commit -m "fix(sync): translate single-active IntegrityError to 409 + rollback; model index parity (H8)"
```

---

## Task T11: Daily sync — parent heartbeat, adopt-not-run, progress steps, budget skip, overview regen (H1, H9, M3, H5, M5)

**Files:**
- Modify: `backend/app/services/daily_knowledge_sync_service.py`
- Modify: `backend/app/knowledge/run_manifests.py` (drop dead `freshness_reconcile` from `daily_sync`)
- Test: `backend/tests/unit/services/test_daily_knowledge_sync.py` (add)

**Interfaces — Consumes:** `heartbeat` (`app.core.heartbeat`), `sync_budget.preflight_owner_budget` (T3), `RunCoordinator` (T10).

- [ ] **Step 1: Failing tests**

```python
async def test_parent_run_heartbeat_refreshed_during_orchestrate(monkeypatch, db_session):
    # Stub _orchestrate to sleep > heartbeat interval; assert heartbeat_at advanced.
    ...

async def test_child_skips_when_already_active(monkeypatch):
    # _start_child_wf returns (None, True) when RunAlreadyActiveError → sub-step SKIPPED
    ...
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: H1 — wrap `_orchestrate` in a parent heartbeat** in `run_for_project`:

```python
        from app.core.heartbeat import heartbeat
        from datetime import UTC, datetime

        async def _hb() -> None:
            async with async_session_factory() as s:
                r = await s.get(IndexingRun, run_id)
                if r and r.status == "running":
                    r.heartbeat_at = datetime.now(UTC)
                    await s.commit()

        async with heartbeat(_hb, interval_seconds=settings.heartbeat_interval_seconds):
            result = await self._orchestrate(project_id, run_id=run_id)
```

(Import `settings` if not already.)

- [ ] **Step 4: H9 — `_start_child_wf` returns `(wf_id | None, already_active: bool)`:**

```python
    async def _start_child_wf(self, kind, connection_id, project_id):
        from app.services.run_coordinator import RunAlreadyActiveError, RunCoordinator
        try:
            async with async_session_factory() as rdb:
                run = await RunCoordinator().start(
                    rdb, kind=kind, project_id=project_id,
                    connection_id=connection_id, trigger="schedule")
                return run.workflow_id, False
        except RunAlreadyActiveError:
            return None, True
```

Update the three callers (`_run_repo_index`, `_run_db_index`, `_run_code_db_sync`): on `already_active`, return `(_STEP_SKIPPED, "already running (adopted)")` BEFORE launching the pipeline.

- [ ] **Step 5: H5 — budget skip** in `_run_code_db_sync` (and `_run_db_index`): after the existing `get_sync_status`/`is_indexed` checks:

```python
        from app.services.sync_budget import preflight_owner_budget
        async with async_session_factory() as session:
            ok, reason, _ = await preflight_owner_budget(session, project_id)
        if not ok:
            return _STEP_SKIPPED, f"owner budget: {reason}"
```

- [ ] **Step 6: M5 — overview regen after sync** in the `final_status == _STEP_COMPLETED` branch of `_run_code_db_sync`:

```python
            try:
                from app.api.routes.connections import _regenerate_overview
                await _regenerate_overview(project_id, connection_id)
            except Exception:
                logger.debug("daily sync overview regen failed", exc_info=True)
```

- [ ] **Step 7: M3 — progress steps + manifest align.** Change `_orchestrate(self, project_id)` → `_orchestrate(self, project_id, *, run_id)`; emit `tracker.emit(workflow_id, step, "started"/"completed")` around `repo_index`, per-connection `db_index`, `code_db_sync`, and a final `summarize`. Fetch the parent run's `workflow_id` once. In `run_manifests.py`, remove the `Step("freshness_reconcile", ...)` line from the `daily_sync` manifest (leaving `plan_targets, db_index, code_db_sync, summarize`).

> The emit keys MUST match the manifest keys (`plan_targets`, `db_index`, `code_db_sync`, `summarize`). The coordinator `_on_event`→`_apply_event` projection advances `progress_pct`.

- [ ] **Step 8: Run tests — PASS**; ruff/mypy.
- [ ] **Step 9: Commit**

```bash
git add backend/app/services/daily_knowledge_sync_service.py backend/app/knowledge/run_manifests.py backend/tests/unit/services/test_daily_knowledge_sync.py
git commit -m "fix(sync): parent-run heartbeat, adopt-not-run, progress steps, budget skip, overview regen (H1,H9,M3,H5,M5)"
```

---

## Task T12: Reaper observability (L1)

**Files:**
- Modify: `backend/app/services/stale_run_reaper.py` (`reap_once`)
- Test: `backend/tests/unit/services/test_stale_run_reaper.py` (add)

- [ ] **Step 1: Failing test** — when a driver returns `-1` rowcount, an INFO sweep line is logged.

```python
async def test_reaper_logs_sweep_when_rowcount_unknown(caplog, monkeypatch, db_session):
    # monkeypatch the four execute results' .rowcount to -1; assert a sweep log line emitted
    ...
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Edit `reap_once`** — after computing `out`, add an unknown-count branch:

```python
        unknown = any(
            (r.rowcount is not None and r.rowcount < 0)
            for r in (db_res, sync_res, repo_res, runs_failed, runs_cancelled)
        )
        if any(out.values()):
            logger.info("Reaper: reset stale runs — db_index=%d sync=%d repo=%d runs=%d (timeout=%ds)",
                        out["db_index"], out["sync"], out["repo"], out["runs"], timeout_seconds)
        elif unknown:
            logger.info("Reaper: swept stale runs (rowcount unknown on this driver, timeout=%ds)",
                        timeout_seconds)
        return out
```

- [ ] **Step 4: Run — PASS**; ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/services/stale_run_reaper.py backend/tests/unit/services/test_stale_run_reaper.py
git commit -m "fix(sync): reaper logs a sweep even when driver rowcount is unknown (L1)"
```

---

## Task T13: Worker — synced_tables log key (M5)

**Files:**
- Modify: `backend/app/worker.py` (`run_code_db_sync` log line ~151)
- Test: covered by reading the result dict; add a tiny assertion test in `backend/tests/unit/test_worker_sync.py`.

- [ ] **Step 1: Failing test** — `run_code_db_sync` logs `matched=` from the `synced` key. (Patch the pipeline to return `{"status":"completed","total_tables":3,"synced":2}`; assert log contains `matched=2`.)

- [ ] **Step 2: Run — expect FAIL** (currently logs `matched=None`).

- [ ] **Step 3: Edit** the log block:

```python
            tables = result.get("total_tables") if isinstance(result, dict) else None
            matched = result.get("synced") if isinstance(result, dict) else None
```

- [ ] **Step 4: PASS**; ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/worker.py backend/tests/unit/test_worker_sync.py
git commit -m "fix(sync): worker logs matched count from correct 'synced' key (M5)"
```

---

# WAVE 4 — Egress opt-in + freshness

## Task T14: Connection opt-in flag + migration + route budget gate (H6 opt-in, H5 429)

**Files:**
- Modify: `backend/app/models/connection.py` (add column after `is_active` ~58)
- Create: `backend/alembic/versions/<rev1>_sync_remediation_connection_flag.py`
- Modify: `backend/app/api/routes/connections.py` (`ConnectionCreate`, `ConnectionResponse`, `trigger_sync` ~1008)
- Test: `backend/tests/unit/models/test_connection_flag.py`, `backend/tests/integration/test_trigger_sync_budget.py`

- [ ] **Step 1: Failing tests** — default True on model; `trigger_sync` returns 429 when owner over budget.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Model column** (`connection.py` after `is_active`):

```python
    send_sample_data_to_llm: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
```

- [ ] **Step 4: Migration `<rev1>`:**

```python
def upgrade() -> None:
    op.add_column("connections", sa.Column(
        "send_sample_data_to_llm", sa.Boolean(), nullable=False, server_default=sa.text("1")))

def downgrade() -> None:
    with op.batch_alter_table("connections") as b:
        b.drop_column("send_sample_data_to_llm")
```

- [ ] **Step 5: Surface in schemas** — add `send_sample_data_to_llm: bool = True` to `ConnectionCreate` and include in `ConnectionResponse` (it is NOT a secret).

- [ ] **Step 6: `trigger_sync` 429 pre-flight** — after `require_role(editor)` and before the start-lock dispatch:

```python
    from app.services.sync_budget import preflight_owner_budget
    ok, reason, _ = await preflight_owner_budget(db, conn.project_id)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)
```

- [ ] **Step 7: Run tests — PASS**; migration up/down on scratch SQLite; ruff/mypy.
- [ ] **Step 8: Commit**

```bash
git add backend/app/models/connection.py backend/app/api/routes/connections.py backend/alembic/versions/*connection_flag.py backend/tests/unit/models/test_connection_flag.py backend/tests/integration/test_trigger_sync_budget.py
git commit -m "feat(sync): per-connection send_sample_data_to_llm opt-out + trigger_sync budget 429 (H6,H5)"
```

---

## Task T15: Freshness dataclass + stale/failed split (M8)

**Files:**
- Modify: `backend/app/services/knowledge_freshness_service.py`
- Test: `backend/tests/unit/services/test_knowledge_freshness_service.py` (add)

- [ ] **Step 1: Failing tests** — `KnowledgeFreshness()` default `warnings == []`; `overall_stale is False`; a `failed` sync sets `sync_failed=True`.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Edit dataclass:**

```python
    warnings: list[str] = field(default_factory=list)
    sync_failed: bool = False
```

(remove `= None # type: ignore`). In `evaluate`'s sync block, set `snapshot.sync_failed = (snapshot.sync_status == "failed")` alongside `sync_stale`.

- [ ] **Step 4: Run — PASS**; ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/services/knowledge_freshness_service.py backend/tests/unit/services/test_knowledge_freshness_service.py
git commit -m "fix(sync): freshness warnings default-list + sync_failed flag (M8)"
```

---

# WAVE 5 — Glue, schedule honesty, loop-closure, integration

## Task T16: Cron wave honors per-project hour + reconciler all-connections (M4, M1)

**Files:**
- Modify: `backend/app/main.py` (`_dispatch_daily_knowledge_sync_wave` ~692, `_daily_knowledge_sync_cron_loop` ~751, `_freshness_reconcile` ~603)
- Modify: `backend/app/services/daily_knowledge_sync_service.py` (`list_eligible_projects` returns effective hour) — **NOTE:** this file is owned by T11; T16 depends on T11 and edits a *different method*. To keep ownership disjoint, the `list_eligible_projects` hour-return change is moved INTO T11 (add it there). T16 only edits `main.py`.

- [ ] **Step 1: Failing test** — wave dispatches a project only when its effective hour == current local hour.

```python
async def test_wave_filters_by_effective_hour(monkeypatch):
    # two projects: one effective hour=current, one hour=current+1 → only first dispatched
    ...
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: M4 — wave filters by hour.** In `_dispatch_daily_knowledge_sync_wave`, compute `current_hour = datetime.now(tz).hour`; change the eligible loop to dispatch only projects whose `SyncScheduleService.effective(...)["hour"] == current_hour`. Change the Redis lock to `cron:daily_sync:{run_date}:{current_hour}`.

- [ ] **Step 4: M4 — cron loop wakes hourly.** Replace the `compute_next_scheduled_run`-based sleep in `_daily_knowledge_sync_cron_loop` with a top-of-next-hour sleep:

```python
            now = datetime.now(tz)
            next_hour = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
            await asyncio.sleep(max(1.0, (next_hour - now).total_seconds()))
            await _dispatch_daily_knowledge_sync_wave()
```

(Keep `compute_next_scheduled_run` for the `/sync-schedule` `next_run` display in projects.py.)

- [ ] **Step 5: M1 — reconciler all connections.** In `_freshness_reconcile`, replace `conn_id = connections[0].id if connections else None` and the single-connection block with a `for conn in connections:` loop that evaluates freshness and calls `maybe_autostart_db_index` / `maybe_autostart_sync` per connection. For `fresh.sync_failed`, guard with an in-memory per-cycle set so a perpetually-failed sync is retried at most once per reconcile pass (anti retry-storm, spec §5.12).

- [ ] **Step 6: Run tests — PASS**; ruff/mypy.
- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/tests/unit/test_main_cron.py
git commit -m "fix(sync): cron wave honors per-project hour; reconciler covers all connections (M4,M1)"
```

---

## Task T17: Projects route — schedule consistency + get_index_age guard surfaced (M4 display, M9)

**Files:**
- Modify: `backend/app/api/routes/projects.py` (`get_sync_schedule` ~500; readiness probe ~391-416 uses sync/index status)
- Test: `backend/tests/integration/test_sync_schedule_route.py` (add)

- [ ] **Step 1: Failing test** — `/sync-schedule` `next_run` reflects the per-project hour and is consistent with the now-hourly cron (the cron honors it).

- [ ] **Step 2-3:** Verify `get_sync_schedule` still computes `next_run` from the effective per-project hour (it already does, line ~518). Add a regression test asserting the displayed `next_run` hour equals the effective hour. No code change unless the test reveals drift; if drift, align the displayed `next_run` with the hourly cron contract.

- [ ] **Step 4: Run — PASS**; ruff/mypy.
- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/projects.py backend/tests/integration/test_sync_schedule_route.py
git commit -m "test(sync): assert sync-schedule next_run matches per-project hour (M4)"
```

---

## Task T18: Integration — migration linearization, full check, docs, issue closure, validation cycle

**Files:**
- Modify: `backend/alembic/versions/*` (down_revision chaining of `<rev1>`,`<rev2>`,`<rev3>`)
- Modify: `CHANGELOG.md` (`[Unreleased]`), `qa-audit/issues.md` (close all 22), `CLAUDE.md` (note R5 flags if needed)

- [ ] **Step 1: Linearize migrations** — set each new revision's `down_revision` to chain after the current head (run `alembic heads`; if multiple heads, add a merge revision). Run `cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head` then `alembic downgrade -3 && alembic upgrade head` on a scratch DB — expect no errors.
- [ ] **Step 2: Full backend gate** — `cd backend && .venv/bin/ruff format --check app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ --ignore-missing-imports && .venv/bin/pytest tests/ -q` then `coverage report --fail-under=72`. Expect all green.
- [ ] **Step 3: Frontend gate** (no frontend changes expected, but confirm) — `cd frontend && npx tsc --noEmit && npx eslint . --max-warnings=0 && npm test`.
- [ ] **Step 4: CHANGELOG + issues** — add an `[Unreleased]` R5 block listing all 22 fixes; mark each finding closed in `qa-audit/issues.md`.
- [ ] **Step 5: VALIDATION CYCLE (required by user)** — for EACH finding H1..L4, re-read the touched code and confirm: (a) the business-logic understanding in the spec matches the live code, (b) the fix is present and behaves, (c) no regression to the documented invariants (vision §7: read-only, credentials never exposed, freshness tracked, traceability, graceful degradation). Record a one-line confirmation per finding in `docs/superpowers/plans/2026-06-25-sync-remediation.md` under a "Validation log" appended section.
- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs(sync): R5 changelog + close 22 audit findings + validation log"
```

---

## Self-review (author checklist — done)

- **Spec coverage:** every spec § maps to a task — §5.1→T1, §5.2→T2, §5.10→T3, §5.4→T4, §5.5→T5, §5.6→T6, §5.8(sqlagent gate)→T7, §5.9→T8, §5.6c→T9, §5.8→T10, §5.7→T11, §5.15→T12, §5.14→T13, §5.13→T14, §5.12→T15, §5.11→T16, §5.13(sync_now/projects)→T17, integration→T18. All 22 finding IDs appear in the §6 traceability table and in a task.
- **Placeholder scan:** Alembic `<rev1/2/3>` are autogenerated revision IDs (resolved by the `alembic revision` command in-task) — not TBDs. No "implement later"/"add error handling" placeholders; every code step shows code.
- **Type consistency:** `is_fallback` (T4) consumed in T5; `delete_stale_tables(current_keys: set[str])` (T8) — both callers updated in T8 (db_index_pipeline) and CodeDbSync's own delete stays name-based (unchanged); `preflight_owner_budget -> (ok, reason, owner_id)` (T3) consumed identically in T5/T11/T14; `_start_child_wf -> (wf_id|None, bool)` (T11) — all three callers updated in T11; manifest keys (`plan_targets, db_index, code_db_sync, summarize`) match the emit keys in T11 and the `run_manifests.py` edit.
- **Cross-file ownership:** the one cross-task edit (`list_eligible_projects` hour return) is explicitly moved into T11 to keep `daily_knowledge_sync_service.py` single-owner; T16 touches only `main.py`.
