# Module 09 — Data Validation / Investigations / DataGate — Audit Report

**Round 1** · 2026-06-24 · Scope: `agents/data_gate.py`, `agents/investigation_agent.py`,
`routes/data_validation.py`, `routes/data_investigations.py`, `routes/reconciliation.py` (routes
scanned). Focus: the DataGate "block impossible numbers" guarantee (`vision.md §7` — data
quality / impossible numbers blocked when `data_gate_hard_checks_enabled`).

**Positive notes (verified):**
- `data_gate_hard_checks_enabled = True` by default — the hard-fail path is active out of the box.
- `InvestigationAgent` is bounded (`max_investigation_iterations` loop, `:99-101`) and runs its
  SQL through `SafetyGuard` (`:194-195`) — no unbounded investigation loops, no unguarded SQL.
- Null / duplicate / type-mix checks are **warnings** (non-blocking) — correct severity; only
  value-range violations hard-fail.
- Cross-stage consistency and truncation checks exist.

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-DG-01 — 🟡 Medium — `Decimal` values bypass the percent/date hard-check (the most common numeric DB type is never range-checked)

**Type:** Bug (guarantee gap)
**Location:** `agents/data_gate.py:262` (`if kind == "percent" and isinstance(val, (int, float))`)
and the date branch below it.

**Description.** The value-range hard-check only inspects values that are `int` or `float`. But
`asyncpg` (and most drivers) return SQL `NUMERIC`/`DECIMAL` columns as `decimal.Decimal`, which is
**not** an instance of `int`/`float`. Percentages and ratios are very commonly `NUMERIC`, so the
"impossible percentage" hard-fail silently **does not apply** to them. The same gap affects
string-encoded numbers (e.g. `"150"`).

**Impact.** The headline "block impossible numbers" guarantee misses the most common numeric type
— an out-of-range `Decimal('150')` percentage passes the gate and reaches the user.

**Proposed fix.** Coerce to a numeric check that includes `Decimal` (and numeric strings):
`isinstance(val, numbers.Real)` plus a `Decimal`/`str`→`float` attempt with a `try/except`. Add a
test with a `Decimal` out-of-range percentage.

---

## F-DG-02 — 🟡 Medium — Hard checks run on a sample, so impossible values outside the sample window pass

**Type:** Bug (guarantee gap)
**Location:** `data_gate.py:241` (`sample = qr.rows[:self._max_sample]`), `:255`
(`for row in sample[:sample_limit]`).

**Description.** The range check only scans the first `data_gate_value_range_sample` rows of the
first `_max_sample` rows. An impossible value at row N (beyond the window) is never inspected, so a
result set with one bad row past the sample passes the hard-fail gate.

**Impact.** "Impossible numbers blocked" holds only for the sampled prefix; a single out-of-range
value deeper in the result is returned to the user as if validated.

**Proposed fix.** For the *hard-fail* range check specifically, scan all returned rows (it's a
cheap numeric comparison), or push the bound into SQL (`HAVING`/`WHERE` sanity predicate) so the
DB enforces it on the full set. Keep sampling only for the expensive/heuristic warnings.

---

## F-DG-03 — 🟡 Medium — Hard-FAIL keys on fuzzy column classification (keyword heuristic by default)

**Type:** Bug (false positives & negatives on a consequential gate)
**Location:** `data_gate.py:212-237` (`_classify_columns`); default `data_gate_llm_semantics =
False` so the **keyword heuristic** (`_PERCENT_KEYWORDS`/`_DATE_KEYWORDS` on column *names*) is the
default path; the LLM classifier silently falls back on exception (`:225-226`).

**Description.** Whether a column is range-checked depends on matching its **name** against a
keyword list. This drives a *hard fail* (which forces a stage replan and can discard an otherwise
correct answer), so misclassification is costly both ways:
- **False negative:** a percentage column aliased `x`/`ctr`/`roi` isn't classified as percent →
  never range-checked (compounds F-DG-01/02).
- **False positive:** a non-percentage column named e.g. `percentage_id` or `completion_pct`
  holding a count gets range-checked and can hard-fail a correct result, triggering wasteful
  replans.
- The LLM classifier (when enabled) is non-deterministic — the same data can classify differently
  across runs → a flaky gate — and its failures are swallowed to the heuristic silently.

**Proposed fix.** Prefer the actual SQL column **type** + a value-distribution heuristic over the
column *name*; only hard-fail when classification confidence is high; log (don't swallow) LLM
classifier failures; make the LLM path cache results per (column signature) for determinism.

---

## F-DG-04 — 🟡 Medium — Unhashable cell (JSON/array column) crashes the duplicate check

**Type:** Bug (crash / gate fails)
**Location:** `data_gate.py:197-204` (`key = tuple(row); if key in seen: … seen.add(key)`); called
unguarded from `check()` (`:133`), invoked at `stage_executor.py:301`.

**Description.** `_check_duplicates` builds `tuple(row)` and uses it as a set key. If any cell is a
`list`/`dict` (a Postgres `JSON`/`JSONB`/array column, returned by asyncpg as Python `list`/`dict`),
the tuple is **unhashable** → `TypeError`. `check()` has no `try/except`, so the gate raises on any
result containing a JSON/array column. Depending on `stage_executor`'s wrapping, that either errors
the stage or is swallowed (gate fails open — no quality checks run).

**Impact.** Any query returning a JSON/array column breaks the DataGate — either failing the stage
or silently skipping all quality checks for that result.

**Proposed fix.** Build a hashable key (`tuple(repr(c) for c in row)` or JSON-serialize unhashables)
and wrap each sub-check in a defensive `try/except` that logs and degrades to "check skipped"
rather than crashing the gate.

---

## F-DG-05 — 🟢 Low — Percent bounds are lenient (`-1..200`), so many wrong percentages pass the "impossible" check

**Type:** Inaccuracy (weaker guarantee than implied)
**Location:** `config.py:555-556` (`data_gate_percent_min=-1.0`, `data_gate_percent_max=200.0`).

**Description.** The "impossible percentage" hard-fail only triggers below `-1` or above `200`. A
value like `150` on a 0–100 column passes. The bounds are deliberately lenient (to avoid false
positives on growth/ratio columns), but the effect is that the "blocks impossible numbers" framing
overstates the guarantee.

**Proposed fix.** Document the bounds explicitly; consider a tighter bound when the column is
confidently a 0–100 percentage, and keep the lenient bound only for ambiguous cases.

---

## F-DG-06 — 🟢 Low — Type-consistency check is off-by-design at the boundaries

**Type:** Minor accuracy
**Location:** `data_gate.py:186` (`if len(type_set) > 2`).

**Description.** Warns only when **more than two** distinct Python types appear, so a genuine
`int`+`str` 2-type mix is never flagged, while a legitimately-numeric column returning a mix of
`int`/`float`/`Decimal` (3 types) is falsely flagged as "mixed types".

**Proposed fix.** Normalise numeric types (`int`/`float`/`Decimal` → "number") before counting, and
flag at `>1` distinct *normalised* kind.

---

## Test gaps (⚪ Info)

- No test that an out-of-range `Decimal` percentage hard-fails (F-DG-01).
- No test that an impossible value beyond the sample window is caught (F-DG-02).
- No test that a JSON/array column doesn't crash the gate (F-DG-04).
- No test for classification false-positive hard-fails (F-DG-03).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-DG-01 | 🟡 | `Decimal` percent/date values bypass the range hard-check (NUMERIC is the common type) |
| F-DG-02 | 🟡 | Hard checks run on a sample → impossible values past the window pass |
| F-DG-03 | 🟡 | Hard-FAIL keys on fuzzy name-based classification → false pos/neg, wasteful replans |
| F-DG-04 | 🟡 | JSON/array cell makes `tuple(row)` unhashable → DataGate crashes |
| F-DG-05 | 🟢 | Percent bounds `-1..200` are lenient; many wrong percentages pass |
| F-DG-06 | 🟢 | Type-consistency `>2` boundary mis-flags/​misses numeric type mixes |

**Next-round focus:** `_check_cross_stage_consistency` and `_check_truncation` logic;
reconciliation route (insight confirm/dismiss authorization); `data_investigations` route access
control + whether investigation results can leak cross-connection; `data_validation` feedback
rollback path; whether DataGate failures correctly trigger replan vs silently warn at budget edge.
