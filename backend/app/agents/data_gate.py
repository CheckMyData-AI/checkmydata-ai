"""DataGate — intermediate data-quality checks between pipeline stages.

Sits *after* StageValidator (plan-criteria) and complements
AgentResultValidator (structural) by inspecting the actual data content:

- Null / empty rate anomalies
- Type consistency within columns
- Duplicate-row detection
- Value-range sanity (dates, bounded percentages, unbounded rates,
  non-negative counts)
- Cross-stage row-count consistency
- Truncation detection

Returns a ``DataGateOutcome`` that the executor can act on (warn, retry,
or replan).
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from app.agents.stage_context import PlanStage, StageContext, StageResult
from app.config import settings
from app.connectors.base import QueryResult

logger = logging.getLogger(__name__)

# Legacy constants kept for tests / backwards-compat imports. New code should
# read thresholds from :data:`app.config.settings` (``data_gate_*``).
_MAX_SAMPLE = settings.data_gate_max_sample
_HIGH_NULL_RATIO = settings.data_gate_high_null_ratio
_HIGH_DUPLICATE_RATIO = settings.data_gate_high_duplicate_ratio


# Keyword-based semantic hints used when LLM classification is disabled.
# These are a heuristic fallback, not the source of truth — when an LLM
# classifier is wired (``column_semantic_classifier``) it takes precedence.
#
# Matching is **token-based** (the column name is split into whole words),
# NOT substring-based: substring matching produced false positives that fed
# hard checks — e.g. "account"/"discount" contain "count" (a *negative
# account balance is legitimate*), "electric" contains "ctr", "operate"
# contains "rate". Whole-token matching avoids those.
#
# "Bounded percent" columns are conceptually a 0..100 share, so a value of
# 150 is impossible and gets the strict bound. "Rate" columns (rate/ratio/
# growth) can legitimately exceed 100% (e.g. 150% YoY growth) and get the
# loose bound. "Count" columns must be non-negative.
# Only tokens that are *unambiguously* a 0..100 share. Deliberately excludes
# retention/churn/utilization (NRR can exceed 100%, net churn can be negative,
# CPU utilization can exceed 100%) to avoid false-positive hard fails.
_PERCENT_BOUNDED_KEYWORDS: frozenset[str] = frozenset(
    {
        "percent",
        "percentage",
        "pct",
        "conversion",
        "completion",
        "occupancy",
        "ctr",
    }
)
_RATE_KEYWORDS: frozenset[str] = frozenset({"rate", "ratio", "growth"})
# When a delta/change token co-occurs with a percent token, the column is a
# signed percentage-delta (e.g. "percent_change", "pct_growth") which CAN
# exceed 100% or go negative — demote it from bounded-percent to rate.
_DELTA_KEYWORDS: frozenset[str] = frozenset(
    {"change", "delta", "growth", "diff", "increase", "decrease", "variance", "gain", "loss", "net"}
)
_COUNT_KEYWORDS: frozenset[str] = frozenset({"count", "cnt", "qty", "quantity", "num", "number"})
_DATE_KEYWORDS: frozenset[str] = frozenset({"date", "datetime", "created", "updated", "timestamp"})

# Split a column name into lowercase word tokens, handling snake_case and
# camelCase (e.g. "purchaseCount" / "purchase_count" -> {"purchase", "count"}).
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def _column_tokens(name: str) -> set[str]:
    snake = _CAMEL_BOUNDARY_RE.sub("_", name)
    return {t for t in _NON_WORD_RE.split(snake.lower()) if t}


def _parse_numeric_string(text: str) -> float | None:
    """Parse a numeric-looking string; ``None`` for anything non-numeric.

    AQ-5: connectors that return numbers as text (some drivers, CSV exports,
    MongoDB) previously bypassed every value-range hard check — ``"150"`` in a
    bounded-percent column passed silently. Non-finite results (``"nan"``,
    ``"inf"``) are not usable measures and also yield ``None``.
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        value = float(stripped)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _type_family(value: Any) -> str:
    """Group a value into a family, so a within-family mix is not reported as one.

    ``bool`` is deliberately its own family even though it is an ``int`` subclass in
    Python: a column holding both ``True`` and ``3`` is not a consistent column, and
    treating it as numeric is how that would go unnoticed. Order matters here — the
    bool test has to come before the numeric one for the same reason.
    """
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float | Decimal):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, bytes | bytearray | memoryview):
        return "binary"
    if isinstance(value, datetime | date | time):
        return "temporal"
    if isinstance(value, list | tuple | set | dict):
        return "container"
    return type(value).__name__


def _hashable(value: object) -> object:
    """A hashable stand-in for *value* that still distinguishes different contents.

    F-DG-04. `tuple(row)` is unhashable the moment a cell holds a `list` or `dict` — a
    Postgres ``json``/``jsonb`` or array column, a Mongo document, an aggregated array —
    so ``key in seen`` raised ``TypeError`` and took the whole answer down with it.
    DataGate sits on the answer path, and a check that breaks what it is checking is
    worse than no check.

    Recursing rather than falling back to ``repr`` matters for the check's purpose: two
    rows whose JSON differs only deep inside must still count as different, and two rows
    with identical JSON must still count as the same. A dict is keyed on its sorted
    items so ``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` are one value, which is what
    they are.
    """
    if isinstance(value, dict):
        return ("\x00dict", tuple(sorted((k, _hashable(v)) for k, v in value.items())))
    if isinstance(value, (list, tuple)):
        return ("\x00seq", tuple(_hashable(v) for v in value))
    if isinstance(value, set | frozenset):
        return ("\x00set", tuple(sorted(repr(_hashable(v)) for v in value)))
    try:
        hash(value)
    except TypeError:
        # Anything else unhashable (a bytearray, a driver-specific object): fall back to
        # its text form. Coarser than the structural cases above, and still honest —
        # equal text means equal cell for a duplicate count.
        return ("\x00repr", repr(value))
    return value


@dataclass
class DataGateOutcome:
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    @property
    def error_summary(self) -> str:
        return "; ".join(self.errors) if self.errors else ""

    def fail(self, msg: str, *, suggestion: str = "") -> None:
        self.passed = False
        self.errors.append(msg)
        if suggestion:
            self.suggestions.append(suggestion)

    def warn(self, msg: str, *, suggestion: str = "") -> None:
        self.warnings.append(msg)
        if suggestion:
            self.suggestions.append(suggestion)

    def merge(self, other: DataGateOutcome) -> None:
        if not other.passed:
            self.passed = False
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        self.suggestions.extend(other.suggestions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "warnings": self.warnings,
            "errors": self.errors,
            "suggestions": self.suggestions,
        }


class DataGate:
    """Runs data-quality checks on a ``StageResult``.

    Thresholds come from :mod:`app.config` (``data_gate_*`` knobs) so ops
    can tune them without redeploying. Explicit constructor args still win
    (used by tests).
    """

    def __init__(
        self,
        *,
        null_threshold: float | None = None,
        duplicate_threshold: float | None = None,
        max_sample: int | None = None,
        llm_semantics: bool | None = None,
        column_semantic_classifier: Any = None,
    ) -> None:
        self._null_threshold = (
            null_threshold if null_threshold is not None else settings.data_gate_high_null_ratio
        )
        self._dup_threshold = (
            duplicate_threshold
            if duplicate_threshold is not None
            else settings.data_gate_high_duplicate_ratio
        )
        self._max_sample = max_sample if max_sample is not None else settings.data_gate_max_sample
        self._llm_semantics = (
            llm_semantics if llm_semantics is not None else settings.data_gate_llm_semantics
        )
        # Optional callable: ``(columns, sample_rows) -> dict[col_name, kind]``
        # where ``kind`` ∈ {"percent", "rate", "count", "date", "amount",
        # "id", "other"}. When present, it takes precedence over the keyword
        # heuristic.
        self._semantic_classifier = column_semantic_classifier
        # One-shot guard so the "LLM semantics requested but no classifier
        # wired" degradation is surfaced exactly once per gate instance.
        self._warned_semantics_degraded = False

    def check(
        self,
        stage: PlanStage,
        result: StageResult,
        stage_ctx: StageContext,
    ) -> DataGateOutcome:
        outcome = DataGateOutcome()

        if result.status == "error":
            return outcome

        qr = result.query_result
        if qr is None or not qr.rows:
            return outcome

        self._check_nulls(qr, outcome)
        self._check_type_consistency(qr, outcome)
        self._check_duplicates(qr, outcome)
        self._check_value_ranges(qr, outcome)
        self._check_truncation(qr, stage, outcome)
        self._check_cross_stage_consistency(stage, result, stage_ctx, outcome)

        return outcome

    def check_query_result(
        self,
        qr: QueryResult,
        *,
        question: str = "",
    ) -> DataGateOutcome:
        """Run value-range hard-checks on a bare ``QueryResult``.

        This is the single-query counterpart of :meth:`check` — it runs only
        ``_check_value_ranges`` (the impossible-value detector) without needing
        stage / context objects. Used by :class:`~app.agents.result_validation.
        ResultValidation` on the flat-loop path so a 150% conversion or negative
        count is caught before being returned to the LLM.

        The *question* parameter is accepted for future context-aware
        classification; it is unused in the current keyword-heuristic path.
        """
        outcome = DataGateOutcome()
        if not qr.rows:
            return outcome
        self._check_value_ranges(qr, outcome)
        return outcome

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_nulls(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Flag columns where null/empty rate exceeds the threshold."""
        sample = qr.rows[: self._max_sample]
        if not sample:
            return
        n = len(sample)
        for col_idx, col_name in enumerate(qr.columns):
            nulls = 0
            for row in sample:
                try:
                    val = row[col_idx]
                except (IndexError, TypeError):
                    nulls += 1
                    continue
                if val is None or val == "" or (isinstance(val, float) and math.isnan(val)):
                    nulls += 1
            ratio = nulls / n
            if ratio >= self._null_threshold:
                outcome.warn(
                    f"Column '{col_name}' has {ratio:.0%} null/empty values "
                    f"({nulls}/{n} sampled rows — advisory, based on sample only)",
                    suggestion=(
                        f"Verify the query returns meaningful data for '{col_name}'; "
                        "consider adding a WHERE clause or choosing a different column."
                    ),
                )

    def _check_type_consistency(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Warn if a column mixes *unrelated* types.

        F-DG-06: this counted distinct type names and warned above two, which is wrong
        in both directions. ``{int, str}`` is two and is precisely the pairing that let
        ``"150"`` slip past the value-range hard checks; ``{int, float, Decimal}`` is
        three and is what any SQL numeric column looks like. The question is whether the
        types are *related*, and a count cannot answer it — so the comparison is by
        family, and a within-family mix is not a mix.
        """
        sample = qr.rows[: self._max_sample]
        if not sample:
            return
        for col_idx, col_name in enumerate(qr.columns):
            families: set[str] = set()
            names: set[str] = set()
            for row in sample:
                try:
                    val = row[col_idx]
                except (IndexError, TypeError):
                    continue
                if val is None:
                    continue
                families.add(_type_family(val))
                names.add(type(val).__name__)
            if len(families) > 1:
                outcome.warn(
                    f"Column '{col_name}' has mixed types: {sorted(names)}",
                    suggestion=(f"CAST '{col_name}' to a consistent type in the SQL query."),
                )

    def _check_duplicates(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Detect suspiciously high duplicate-row ratio.

        DATA-18: gate requires a minimum sample of 10 rows to avoid false
        positives on legitimately-sparse tables (e.g. a config table with
        3 rows where all values differ on one column).
        """
        sample = qr.rows[: self._max_sample]
        if len(sample) < 10:
            return
        seen: set[tuple] = set()
        dupes = 0
        for row in sample:
            key = tuple(_hashable(v) for v in row)
            if key in seen:
                dupes += 1
            else:
                seen.add(key)
        ratio = dupes / len(sample) if sample else 0
        if ratio >= self._dup_threshold:
            outcome.warn(
                f"{ratio:.0%} of sampled rows are exact duplicates "
                f"({dupes}/{len(sample)} sampled — signal based on sample only)",
                suggestion="Add DISTINCT or GROUP BY to the query if duplicates are unintended.",
            )

    def _classify_columns(self, qr: QueryResult) -> dict[str, str]:
        """Classify each column by semantic kind (percent / rate / count / …).

        Prefers the injected ``_semantic_classifier`` (wired when an LLM
        classifier is available); otherwise falls back to a keyword heuristic
        so the gate still works offline. Returns ``{column_name: kind}`` with
        kind ∈ {"percent", "rate", "count", "date", "other"}.
        """
        if self._semantic_classifier is not None:
            try:
                sample = qr.rows[: self._max_sample]
                result = self._semantic_classifier(list(qr.columns), sample)
                if isinstance(result, dict):
                    return {str(k): str(v) for k, v in result.items()}
            except Exception:
                logger.debug("LLM column semantic classifier failed", exc_info=True)
        elif self._llm_semantics and not self._warned_semantics_degraded:
            # The flag asked for LLM semantic classification but no classifier
            # was wired — surface the degradation instead of silently using
            # keywords (the flag previously "gated nothing").
            self._warned_semantics_degraded = True
            logger.warning(
                "DataGate: data_gate_llm_semantics is enabled but no column "
                "semantic classifier was provided — falling back to the "
                "keyword heuristic for value-range checks."
            )

        classified: dict[str, str] = {}
        for col in qr.columns:
            tokens = _column_tokens(col)
            is_pct = "%" in col or bool(tokens & _PERCENT_BOUNDED_KEYWORDS)
            is_delta = bool(tokens & _DELTA_KEYWORDS)
            # Bounded percent only when NOT a signed delta (e.g. "conversion" is
            # bounded, but "percent_change"/"pct_growth" is a signed rate).
            if is_pct and not is_delta:
                classified[col] = "percent"
            elif (tokens & _RATE_KEYWORDS) or (is_pct and is_delta):
                classified[col] = "rate"
            elif tokens & _DATE_KEYWORDS:
                classified[col] = "date"
            elif tokens & _COUNT_KEYWORDS:
                classified[col] = "count"
            else:
                classified[col] = "other"
        return classified

    @staticmethod
    def _flag_non_finite(
        scan_rows: list, col_idx: int, col_name: str, outcome: DataGateOutcome
    ) -> bool:
        """Fail on the first ``NaN``/``Infinity`` in one column. True if it fired.

        Restricted to real ``float``/``Decimal`` values on purpose. A text column
        holding the word "Nan" is a name, not a broken number, and a check that
        blocks an answer must not guess.
        """
        for row in scan_rows:
            try:
                val = row[col_idx]
            except (IndexError, TypeError):
                continue
            if isinstance(val, bool) or val is None:
                continue
            non_finite = (isinstance(val, float) and not math.isfinite(val)) or (
                isinstance(val, Decimal) and (val.is_nan() or val.is_infinite())
            )
            if not non_finite:
                continue
            if settings.data_gate_hard_checks_enabled:
                outcome.fail(
                    f"Column '{col_name}' contains {val}, which is not a usable "
                    "number — it comes from a division by zero, an overflow or a "
                    "bad cast.",
                    suggestion=(
                        f"Guard the expression behind '{col_name}' (NULLIF on the "
                        "divisor, or a CASE for the zero branch)."
                    ),
                )
            else:
                outcome.warn(f"Column '{col_name}' contains a non-finite value ({val}).")
            return True
        return False

    def _check_value_ranges(self, qr: QueryResult, outcome: DataGateOutcome) -> None:
        """Sanity-check obviously out-of-range values."""
        if not qr.rows:
            return
        kinds = self._classify_columns(qr)
        # Hard value-range checks catch IMPOSSIBLE values; missing even one
        # defeats the gate, and the per-cell comparison is cheap (and
        # short-circuits per column on the first hit). Scan the full in-memory
        # result by default; a positive cap bounds it for operators who need to.
        scan_cap = settings.data_gate_value_range_sample
        scan_rows = qr.rows if scan_cap <= 0 else qr.rows[:scan_cap]
        pct_min = settings.data_gate_percent_min
        pct_max = settings.data_gate_percent_max
        year_min = settings.data_gate_year_min
        year_max = settings.data_gate_year_max

        pct_bounded_max = settings.data_gate_percent_bounded_max

        for col_idx, col_name in enumerate(qr.columns):
            # Non-finite values first, and DELIBERATELY before the classifier.
            #
            # Everything below this point only looks at columns the model named
            # with one of 21 keywords; every other column is `other` and skipped
            # entirely, so "no impossible numbers" was enforced against naming
            # habits rather than against data. A `NaN` or an `Infinity` needs no
            # classification to be wrong: it arrives through a 0/0, an overflow
            # or a bad cast, and it is not a measure whatever the column is
            # called. Today it is worse than unchecked — `_check_nulls` counts a
            # NaN as a null and `_as_float` turns one into None, so the single
            # value that is impossible by construction is the one nothing reports.
            #
            # What is NOT added here, deliberately: a money kind with a sign
            # rule. A negative revenue is a refund, a chargeback or an
            # adjustment, and `fail` is a hard refusal to use the result — a gate
            # that blocks it is a product that cannot answer "how much did we
            # refund". The keyword list is already subtler than it looks:
            # `_DELTA_KEYWORDS` demotes `percent_change` to `rate` for exactly
            # this reason.
            if self._flag_non_finite(scan_rows, col_idx, col_name, outcome):
                continue

            kind = kinds.get(col_name, "other")
            if kind not in ("percent", "rate", "count", "date"):
                continue
            for row in scan_rows:
                try:
                    val = row[col_idx]
                except (IndexError, TypeError):
                    continue
                if val is None:
                    continue
                numeric = isinstance(val, (int, float, Decimal)) and not isinstance(val, bool)
                fval: float | None = float(val) if numeric else None
                if fval is None and isinstance(val, str) and kind != "date":
                    # AQ-5: coerce numeric strings so text-returning drivers
                    # cannot bypass the value-range hard checks. Date strings
                    # are handled by the ISO/epoch branches below instead.
                    fval = _parse_numeric_string(val)
                    numeric = fval is not None
                if kind == "percent" and numeric and fval is not None:
                    # Bounded percent (conversion/completion/ctr/occupancy/…) is
                    # a 0..100 share, so values outside [pct_min, bounded_max]
                    # are impossible (e.g. 150% conversion) — hard fail so the
                    # stage retries instead of returning bogus values.
                    if fval < pct_min or fval > pct_bounded_max:
                        if settings.data_gate_hard_checks_enabled:
                            outcome.fail(
                                f"Column '{col_name}' has value {val} "
                                "which is out of range for a percentage "
                                f"({pct_min}..{pct_bounded_max}).",
                                suggestion=(
                                    f"Cast '{col_name}' to a ratio (0..1) or "
                                    "filter the source so impossible values "
                                    "don't appear."
                                ),
                            )
                        else:
                            outcome.warn(
                                f"Column '{col_name}' has value {val} "
                                "which looks out of range for a percentage.",
                            )
                        break
                elif kind == "rate" and numeric and fval is not None:
                    # Rate/ratio/growth and percentage-deltas are signed and can
                    # legitimately exceed 100% (e.g. 150% YoY growth, NRR 130%,
                    # -50% decline). Only an absurd magnitude is suspicious, and
                    # only as a soft WARN — never a hard fail.
                    if fval < -pct_max or fval > pct_max:
                        outcome.warn(
                            f"Column '{col_name}' has value {val} "
                            f"with an unusually large magnitude for a rate (±{pct_max}).",
                        )
                        break
                elif kind == "count" and numeric and fval is not None:
                    if fval < 0:
                        # A negative count/quantity is impossible — hard fail
                        # so the stage retries (usually a bad JOIN or a signed
                        # aggregate). Vision §7: no impossible numbers.
                        if settings.data_gate_hard_checks_enabled:
                            outcome.fail(
                                f"Column '{col_name}' has negative value {val} "
                                "which is impossible for a count/quantity.",
                                suggestion=(
                                    "Check for a bad JOIN or a signed aggregate; "
                                    f"wrap '{col_name}' in ABS()/GREATEST() only "
                                    "if a negative is genuinely expected."
                                ),
                            )
                        else:
                            outcome.warn(
                                f"Column '{col_name}' has negative value {val} "
                                "which is unexpected for a count/quantity.",
                            )
                        break
                elif kind == "date" and isinstance(val, str):
                    try:
                        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                        if dt.year < year_min or dt.year > year_max:
                            # C4 (v1.13.0): wildly out-of-range dates
                            # (year<1900 or >2100 by default) almost always
                            # indicate a unit error (epoch seconds vs ms) or
                            # a string parse glitch — fail() forces a retry.
                            if settings.data_gate_hard_checks_enabled:
                                outcome.fail(
                                    f"Column '{col_name}' has suspicious "
                                    f"date {val}: year {dt.year} outside "
                                    f"[{year_min}, {year_max}].",
                                    suggestion=(
                                        "Confirm the column is actually a "
                                        "date and not epoch seconds/ms. "
                                        "Adjust the SELECT cast accordingly."
                                    ),
                                )
                            else:
                                outcome.warn(
                                    f"Column '{col_name}' has suspicious date: {val}",
                                )
                            break
                    except (ValueError, TypeError):
                        pass
                elif kind == "date" and isinstance(val, (datetime, date)):
                    # AQ-4: asyncpg/pymysql return native datetime/date objects,
                    # which previously matched NO branch — the year-range hard
                    # check was dead code on PostgreSQL/MySQL. (pandas Timestamp
                    # subclasses datetime, so it is covered here too.)
                    if val.year < year_min or val.year > year_max:
                        if settings.data_gate_hard_checks_enabled:
                            outcome.fail(
                                f"Column '{col_name}' has suspicious "
                                f"date {val.isoformat()}: year {val.year} outside "
                                f"[{year_min}, {year_max}].",
                                suggestion=(
                                    "Confirm the column is actually a "
                                    "date and not epoch seconds/ms. "
                                    "Adjust the SELECT cast accordingly."
                                ),
                            )
                        else:
                            outcome.warn(
                                f"Column '{col_name}' has suspicious date: {val.isoformat()}",
                            )
                        break
                elif kind == "date" and isinstance(val, (int, float)) and not isinstance(val, bool):
                    # I7: epoch timestamps arriving as numbers are the exact
                    # unit error (seconds vs ms) the string branch above can't
                    # see. Flag a number that is implausible as *both* epoch
                    # seconds and epoch ms — i.e. not a real timestamp at all.
                    plausible = False
                    for divisor in (1, 1000):
                        try:
                            yr = datetime.fromtimestamp(val / divisor, tz=UTC).year
                        except (ValueError, OverflowError, OSError):
                            continue
                        if year_min <= yr <= year_max:
                            plausible = True
                            break
                    if not plausible:
                        if settings.data_gate_hard_checks_enabled:
                            outcome.fail(
                                f"Column '{col_name}' has numeric value {val} "
                                "that is not a plausible epoch timestamp "
                                f"(seconds or ms) within [{year_min}, {year_max}].",
                                suggestion=(
                                    "Confirm the column is a real date; if it is "
                                    "epoch seconds/ms, convert it (to_timestamp / "
                                    "FROM_UNIXTIME) before returning."
                                ),
                            )
                        else:
                            outcome.warn(
                                f"Column '{col_name}' has numeric value {val} "
                                "that is not a plausible epoch timestamp.",
                            )
                        break

    @staticmethod
    def _check_truncation(
        qr: QueryResult,
        stage: PlanStage,
        outcome: DataGateOutcome,
    ) -> None:
        """Warn if the result looks truncated.

        Checks ``qr.truncated`` first (authoritative flag set by the connector);
        falls back to the common-limit heuristic when the flag is absent/False.
        """
        if qr.truncated:
            outcome.warn(
                f"Result is truncated (capped at {qr.row_count} rows) — aggregates over "
                "these rows are INCOMPLETE.",
                suggestion="Push aggregation into SQL (GROUP BY / aggregate functions).",
            )
            return
        common_limits = set(settings.data_gate_common_limits)
        if qr.row_count in common_limits:
            outcome.warn(
                f"Row count ({qr.row_count}) is a common LIMIT value — result may be truncated.",
                suggestion="Verify the query's LIMIT clause returns all needed data.",
            )

    def _check_cross_stage_consistency(
        self,
        stage: PlanStage,
        result: StageResult,
        stage_ctx: StageContext,
        outcome: DataGateOutcome,
    ) -> None:
        """Lightweight cross-stage data consistency checks."""
        qr = result.query_result
        if not qr or not stage.depends_on:
            return
        for dep_id in stage.depends_on:
            dep = stage_ctx.get_result(dep_id)
            if not dep or not dep.query_result:
                continue
            dep_qr = dep.query_result
            cartesian_mul = settings.data_gate_cartesian_multiplier

            # F-DG-08: `row_count` is the number of rows RETURNED; `truncated` is the
            # separate flag saying more existed. Dividing two capped counts yields a
            # ratio near 1 and the check would report nothing wrong — a reassuring
            # verdict that was never earned, since the true ratio is unknowable from
            # what is in hand. So it says it could not judge instead of judging.
            if qr.truncated or dep_qr.truncated:
                which = []
                if qr.truncated:
                    which.append(f"'{stage.stage_id}'")
                if dep_qr.truncated:
                    which.append(f"'{dep_id}'")
                outcome.warn(
                    f"Cannot check stage '{stage.stage_id}' for a cartesian join against "
                    f"'{dep_id}': {' and '.join(which)} returned a truncated result, so "
                    "the row counts are capped and their ratio means nothing.",
                    suggestion=(
                        "Push the aggregation into SQL, or narrow the query so the "
                        "result fits, and the check becomes meaningful."
                    ),
                )
                continue

            if dep_qr.row_count > 0 and qr.row_count > dep_qr.row_count * cartesian_mul:
                outcome.warn(
                    f"Stage '{stage.stage_id}' produced {qr.row_count} rows "
                    f"from dependency '{dep_id}' which had {dep_qr.row_count} — "
                    "possible cartesian join.",
                    suggestion="Check for missing JOIN conditions in the query.",
                )
