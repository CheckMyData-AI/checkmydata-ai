"""A batch analysis lands on the table it describes (B-16, audit 2026-09-23 F-K1).

`DbIndexValidator.analyze_table_batch` mapped tool calls to tables by POSITION and skipped
a call whose arguments were empty without advancing — so one unparseable call in the
middle of a batch moved every later description, hint and relevance score onto the table
before it, and the last table fell back. Nothing failed: the index simply described the
wrong tables, every night, on the production connection.

The sync analyzer already had the fix (`table_name` in its tool, results keyed by name);
the validator now does the same, and keeps position only for a model that names nothing.
See `docs/audits/2026-09-23-recent-work-audit.md` §3.1.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import ColumnInfo, QueryResult, TableInfo
from app.knowledge.db_index_validator import ANALYZE_TABLE_TOOL, DbIndexValidator
from app.llm.base import LLMResponse, ToolCall


def _table(name: str, schema: str = "public") -> tuple[TableInfo, QueryResult]:
    return (
        TableInfo(
            name=name,
            schema=schema,
            columns=[ColumnInfo(name="id", data_type="integer", is_primary_key=True)],
            row_count=0,
        ),
        QueryResult(),
    )


def _args(description: str, table_name: str | None = None) -> dict:
    args = {
        "is_active": True,
        "relevance_score": 4,
        "business_description": description,
        "data_patterns": "",
        "column_notes": "{}",
        "query_hints": "",
        "code_match_status": "no_code_info",
    }
    if table_name is not None:
        args["table_name"] = table_name
    return args


def _call(i: int, args: dict) -> ToolCall:
    return ToolCall(id=f"c{i}", name="table_analysis", arguments=args)


async def _run(tables, calls) -> list:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=LLMResponse(content="", tool_calls=calls))
    return await DbIndexValidator(llm).analyze_table_batch(
        tables=tables, code_context="", rules_context=""
    )


def _descriptions(results) -> dict[str, str]:
    return {r.table_name: r.business_description for r in results}


def test_the_tool_asks_for_the_table_first_and_requires_it() -> None:
    first = ANALYZE_TABLE_TOOL.parameters[0]
    assert first.name == "table_name"
    assert first.required is True


@pytest.mark.asyncio
async def test_an_empty_call_in_the_middle_does_not_shift_the_rest() -> None:
    """The production defect, with a model that names nothing (position mode)."""
    tables = [_table("users"), _table("orders"), _table("payments")]
    calls = [_call(1, _args("people")), _call(2, {}), _call(3, _args("money in"))]

    out = _descriptions(await _run(tables, calls))

    assert out["users"] == "people"
    assert out["payments"] == "money in", "a later call slid onto the previous table"
    assert out["orders"] != "money in"


@pytest.mark.asyncio
async def test_named_calls_land_by_name_whatever_their_order() -> None:
    tables = [_table("users"), _table("orders"), _table("payments")]
    calls = [
        _call(1, _args("money in", "payments")),
        _call(2, {}),
        _call(3, _args("people", "USERS")),
    ]

    out = _descriptions(await _run(tables, calls))

    assert out["payments"] == "money in"
    assert out["users"] == "people"
    assert out["orders"] not in {"money in", "people"}


@pytest.mark.asyncio
async def test_an_unknown_name_is_dropped_and_a_duplicate_keeps_the_first() -> None:
    tables = [_table("users"), _table("orders")]
    calls = [
        _call(1, _args("invented", "ghosts")),
        _call(2, _args("first", "users")),
        _call(3, _args("second", "users")),
    ]

    out = _descriptions(await _run(tables, calls))

    assert out["users"] == "first"
    assert "invented" not in out.values()
    assert list(out) == ["users", "orders"], "results must stay in the caller's order"


@pytest.mark.asyncio
async def test_a_schema_qualified_name_resolves_and_an_ambiguous_bare_one_does_not() -> None:
    tables = [_table("orders", "sales"), _table("orders", "archive")]
    calls = [
        _call(1, _args("live orders", "sales.orders")),
        _call(2, _args("which one?", "orders")),
    ]

    results = await _run(tables, calls)

    assert results[0].business_description == "live orders"
    assert results[1].business_description != "which one?"
