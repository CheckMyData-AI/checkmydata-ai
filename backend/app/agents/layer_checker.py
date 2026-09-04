"""The gate between a parallel layer and the node that consumes it (Ш3).

:class:`~app.agents.stage_executor.StageExecutor` runs up to
``PIPELINE_MAX_PARALLEL_STAGES`` stages at once and then synthesises. Every check
it had was **per stage** — :class:`~app.agents.stage_validator.StageValidator` on
a stage's own shape, :class:`~app.agents.data_gate.DataGate` on a stage's own
rows. Nothing compared the arriving siblings, and synthesis took its edges
straight from them.

That is the diamond's silent failure, and it belongs to the *convergence* rather
than to any branch: three branches run, one returns a hallucination or an empty
result, and the synthesis node cannot tell — so it answers confidently from
partly-garbage input. In a chain a bad step produces a visibly bad output; at a
convergence the bad output is **mixed** with good ones, the damage spreads thin,
and the trace back to its source is gone.

**Four of the six contract items are implemented here, and two are not.** The
four are pure code and cost nothing. ``contradictory`` and ``off_topic`` need a
model call per layer, on a path whose worst measured request already ran 296 s
against a documented 180 s budget — so they are *declared* unimplemented rather
than quietly omitted. A verdict names what it asserted and what it did not,
because a checker that cannot say which of the six it is asserting is not a
checker, and silence about two of them reads as a clean bill of health on all six.

Confidence is deliberately absent. An uncalibrated judge is an opinion with a
number attached; for anything consequential the control is a deterministic limit
or a human, never a classifier's confidence. Low confidence would flag — absent
evidence blocks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.agents.stage_validator import _TEXT_STAGE_TOOLS

if TYPE_CHECKING:
    from app.agents.stage_context import PlanStage, StageResult

logger = logging.getLogger(__name__)

#: The contract, in the order it must be evaluated — cheap first.
CHECKER_ITEMS: tuple[str, ...] = (
    "missing",
    "empty",
    "unevidenced",
    "malformed",
    "contradictory",
    "off_topic",
)

#: Pure code, no model, no cost.
CODE_ITEMS: tuple[str, ...] = ("missing", "empty", "unevidenced", "malformed")

#: Need an LLM to judge. Not implemented — see the module docstring.
MODEL_ITEMS: tuple[str, ...] = ("contradictory", "off_topic")


@dataclass(frozen=True)
class LayerVerdict:
    """Whether a parallel layer may be consumed, and on what grounds."""

    passed: bool
    #: Which contract items actually ran. Never a claim about the others.
    asserted: tuple[str, ...]
    #: Which did not, so the gap is visible at the call site rather than inferred.
    not_asserted: tuple[str, ...]
    #: One line per rejection, naming the item and the stage.
    failures: list[str] = field(default_factory=list)
    #: Which items rejected something — the scores that make *"has this checker
    #: ever rejected anything?"* an answerable question rather than a hope.
    rejected_items: tuple[str, ...] = ()


class LayerChecker:
    """Decides *usable / not usable* for a batch of sibling stages.

    Synthesises nothing and writes nothing. The convergence must depend on this
    verdict rather than on the branches, or the gate has a bypass and the shape
    is decoration.
    """

    #: Tools whose evidence is prose. Imported from the validator rather than
    #: re-listed: two lists of text tools is how the two sides of a split come to
    #: disagree, which is the defect ``app/core/failure_kind.py`` exists to record.
    _PROSE_TOOLS = _TEXT_STAGE_TOOLS

    def check(
        self,
        *,
        expected: int,
        batch: list[PlanStage],
        results: list[StageResult | None],
    ) -> LayerVerdict:
        """Judge the arriving siblings.

        ``expected`` is a **given**, never inferred: the fan-out is fixed when the
        layer is built, so the count to expect is handed in. Without it a vanished
        branch is caught only when its slot happens to hold nothing — item 2 by
        luck rather than item 1 by design, and only on a host that fills the slot
        at all.
        """
        if expected <= 0:
            raise ValueError(f"expected must be a positive arrival count, got {expected}")

        failures: list[str] = []
        rejected: list[str] = []

        def reject(item: str, message: str) -> None:
            failures.append(f"{item}: {message}")
            if item not in rejected:
                rejected.append(item)

        # 1. missing — by the count, before anything looks at content.
        arrived = [r for r in results if r is not None]
        if len(arrived) != expected:
            reject(
                "missing",
                f"the layer promised {expected} result(s) and {len(arrived)} arrived",
            )

        tools = {stage.stage_id: stage.tool for stage in batch}
        for result in arrived:
            if result.status != "success":
                # A non-success stage is the per-stage machinery's business; the
                # executor short-circuits on it before this checker is reached.
                continue
            stage_id = result.stage_id
            tool = tools.get(stage_id, "")
            qr = result.query_result
            summary = (result.summary or "").strip()
            has_rows = bool(qr and qr.rows)

            # 2. empty — arrived and carries nothing usable at all.
            if not summary and not has_rows and qr is None:
                reject("empty", f"stage '{stage_id}' succeeded with no summary and no result")
                continue

            # 3. unevidenced — a claim with no receipt a later reader could check.
            #    Prose tools are evidenced by their summary by design; demanding
            #    rows of them is the false positive the validator already learned.
            if tool not in self._PROSE_TOOLS and qr is None and not result.query:
                reject(
                    "unevidenced",
                    f"stage '{stage_id}' ({tool or 'unknown tool'}) claims a result with "
                    "no query and no rows behind it",
                )
                continue

            # 4. malformed — a shape that will break the convergence's parsing.
            if qr is not None and qr.rows:
                if not qr.columns:
                    reject("malformed", f"stage '{stage_id}' returned rows with no column names")
                    continue
                width = len(qr.columns)
                ragged = next((i for i, row in enumerate(qr.rows) if len(row) != width), None)
                if ragged is not None:
                    reject(
                        "malformed",
                        f"stage '{stage_id}' row {ragged} has {len(qr.rows[ragged])} value(s) "
                        f"for {width} column(s)",
                    )

        if failures:
            logger.warning("layer checker rejected a parallel layer: %s", "; ".join(failures))

        return LayerVerdict(
            passed=not failures,
            asserted=CODE_ITEMS,
            not_asserted=MODEL_ITEMS,
            failures=failures,
            rejected_items=tuple(rejected),
        )
