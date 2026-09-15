"""A completion cap on a tool call must be paired with a reader of ``finish_reason``.

The defect this closes, measured on production 2026-09-15. ``SYNC_ANALYSIS_TOOL``
declares ten parameters and the per-table call allowed 2048 completion tokens. Against
fourteen real tables, **all fourteen stopped at exactly 2048**: arguments arrive as a
JSON string, so the object never closed, ``json.loads`` raised, and the adapter
substituted ``args = {}`` and appended the tool call anyway. ``_analysis_from_args({})``
then wrote a full row of defaults — ``sync_status="unknown"``, every prose field empty —
and marked it ``is_fallback=False``.

That last flag is the whole reason it was invisible for five days.
``code_db_sync_pipeline`` already refuses to persist a run whose non-fallback ratio falls
below ``sync_min_success_ratio_to_persist``, precisely so a degraded LLM cannot overwrite
a good map. A truncated call is not a fallback, so the guard read 100% success while
every row it let through was empty: 126 of 263 map rows at ``unknown``, over a map that
had held 138 ``matched``.

The provider had said so plainly the entire time. All three adapters set
``LLMResponse.finish_reason`` and **no production code path read it** — the signal
existed, the reader did not. These tests are the reader's proof, and the AST guard is
there because raising the cap fixes today's document and nothing else: a bigger schema,
a wordier model or a larger table finds the next cap the same way.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.knowledge.code_db_sync_analyzer import CodeDbSyncAnalyzer
from app.knowledge.db_index_validator import DbIndexValidator
from app.llm.base import LLMResponse, ToolCall
from app.llm.tool_args import tool_call_truncated

APP = pathlib.Path(__file__).resolve().parents[2] / "app"


# --------------------------------------------------------------------------- unit


def _resp(*, finish: str = "stop", args: dict | None = None) -> LLMResponse:
    calls = [ToolCall(id="c1", name="table_sync_analysis", arguments=args or {})]
    return LLMResponse(content="", tool_calls=calls, usage={}, model="m", finish_reason=finish)


@pytest.mark.parametrize("reason", ["length", "LENGTH", "max_tokens"])
def test_every_provider_s_word_for_out_of_room_is_understood(reason: str) -> None:
    """OpenAI and OpenRouter say ``length``; Anthropic says ``max_tokens``."""
    assert tool_call_truncated(_resp(finish=reason, args={"sync_status": "matched"})) is True


def test_a_complete_call_is_not_truncated() -> None:
    assert tool_call_truncated(_resp(args={"sync_status": "matched"})) is False


def test_empty_arguments_are_truncation_even_when_the_reason_is_silent() -> None:
    """The adapters substitute ``{}`` for unparseable arguments.

    A provider that reports no reason, or one we do not know, still cannot have
    answered a schema whose first parameter is required with nothing at all.
    """
    assert tool_call_truncated(_resp(finish="", args={})) is True


def test_a_response_with_no_tool_call_at_all_is_not_truncation() -> None:
    """That is a model declining to call the tool — a different failure, handled
    by the caller's own no-tool-call branch, and conflating the two would send a
    plain refusal down the truncation path."""
    r = LLMResponse(content="no", tool_calls=[], usage={}, model="m", finish_reason="stop")
    assert tool_call_truncated(r) is False


# ------------------------------------------------------------------ behaviour


class _TruncatingRouter:
    """Answers exactly as the provider did on production: cut off, args unparseable."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, **_kw):
        self.calls += 1
        return _resp(finish="length", args={})


async def test_a_truncated_table_analysis_is_counted_as_a_fallback() -> None:
    """The flag the persist guard reads. Before this, it read ``False``."""
    analyzer = CodeDbSyncAnalyzer(llm_router=_TruncatingRouter())
    result = await analyzer.analyze_table(
        table_name="orders", db_context="cols: id, total", code_context="class Order"
    )
    assert result.is_fallback is True
    assert result.sync_status == "unknown"


async def test_a_truncated_batch_falls_back_for_every_table_in_it() -> None:
    analyzer = CodeDbSyncAnalyzer(llm_router=_TruncatingRouter())
    out = await analyzer.analyze_table_batch(
        tables=[("orders", "db", "code"), ("users", "db", "code")]
    )
    assert [a.table_name for a in out] == ["orders", "users"]
    assert all(a.is_fallback for a in out)


async def test_a_truncated_db_index_analysis_falls_back_too() -> None:
    """The second writer with the same shape — found by looking, not by a failure."""
    from app.connectors.base import TableInfo

    validator = DbIndexValidator(llm_router=_TruncatingRouter())
    analysis = await validator.analyze_table(
        table=TableInfo(name="orders", columns=[]),
        sample_data=None,
        code_context="",
        rules_context="",
    )
    assert analysis.business_description  # the deterministic fallback, not a blank row


# ------------------------------------------------------------------ AST guard


def _chooses_the_cap(value: ast.expr, enclosing: ast.AST) -> bool:
    """Distinguish choosing a completion cap from forwarding somebody else's.

    ``LLMRouter.complete`` takes ``max_tokens`` as its own parameter and hands it
    to the adapter unchanged. It is a pipe, and a pipe cannot decide what to do when
    the cap is hit — the caller who picked the number can, and it is the caller who
    knows what a half-written answer would mean for its own data. So a bare name
    bound to the enclosing function's parameter is forwarding; a literal, or a
    ``settings.…`` lookup, is a choice.
    """
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Attribute):
        return True
    if isinstance(value, ast.Name):
        args = getattr(enclosing, "args", None)
        if args is None:
            return True
        own = {
            a.arg
            for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]
            + ([args.vararg] if args.vararg else [])
            + ([args.kwarg] if args.kwarg else [])
        }
        return value.id not in own
    return True


def _sites_with_an_explicit_cap() -> list[tuple[str, int, str]]:
    """Every call that hands a model a tool AND chooses its own completion cap."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            body = ast.unparse(fn)
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                if "tools" not in kw or "max_tokens" not in kw:
                    continue
                if not _chooses_the_cap(kw["max_tokens"], fn):
                    continue
                found.append((str(path.relative_to(APP.parent)), node.lineno, body))
    return found


def test_a_capped_tool_call_is_always_read_for_truncation() -> None:
    """Whoever sets the cap owns the case where it is reached.

    An uncapped call inherits the provider's own maximum and is out of scope: there
    the model stops because it finished. A call that names a number has chosen a
    boundary, and choosing one without reading ``finish_reason`` is how a map gets
    overwritten with defaults while every gate reports success.
    """
    sites = _sites_with_an_explicit_cap()
    assert sites, "the walker found no capped tool call — it has stopped measuring"
    unguarded = sorted({(f, line) for f, line, body in sites if "tool_call_truncated" not in body})
    assert not unguarded, (
        "these hand a tool to a model with a completion cap and never ask whether it "
        f"was reached: {unguarded}"
    )
