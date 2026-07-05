"""Unit tests for the deterministic schema-completeness gate.

All tests are pure-function (no network, no DB, no LLM).  They hand-build
SchemaInfo / TableInfo / ColumnInfo / ForeignKeyInfo fixtures and verify
that check_schema_completeness() returns the expected CompletenessIssue records.
"""

from app.connectors.base import ColumnInfo, ForeignKeyInfo, SchemaInfo, TableInfo
from app.knowledge.db_index_completeness import CompletenessIssue, check_schema_completeness

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table(name: str, *, columns=None, fks=None, object_kind="table") -> TableInfo:
    return TableInfo(
        name=name,
        columns=columns or [],
        foreign_keys=fks or [],
        object_kind=object_kind,
    )


def _col(name: str, data_type: str, *, pk: bool = False) -> ColumnInfo:
    return ColumnInfo(name=name, data_type=data_type, is_primary_key=pk)


def _fk(column: str, references_table: str, references_column: str = "id") -> ForeignKeyInfo:
    return ForeignKeyInfo(
        column=column,
        references_table=references_table,
        references_column=references_column,
    )


# ---------------------------------------------------------------------------
# no_columns
# ---------------------------------------------------------------------------


def test_flags_table_with_no_columns():
    s = SchemaInfo(tables=[_table("empty")])
    issues = check_schema_completeness(s)
    assert any(i.kind == "no_columns" and i.table == "empty" for i in issues)


def test_table_with_columns_not_flagged_no_columns():
    s = SchemaInfo(tables=[_table("ok", columns=[_col("id", "int", pk=True)])])
    issues = check_schema_completeness(s)
    assert not any(i.kind == "no_columns" for i in issues)


def test_multiple_tables_only_empty_one_flagged():
    s = SchemaInfo(
        tables=[
            _table("empty"),
            _table("ok", columns=[_col("id", "int", pk=True)]),
        ]
    )
    issues = check_schema_completeness(s)
    no_col_tables = [i.table for i in issues if i.kind == "no_columns"]
    assert no_col_tables == ["empty"]


# ---------------------------------------------------------------------------
# empty_type (column with blank data_type)
# ---------------------------------------------------------------------------


def test_flags_column_with_empty_type():
    s = SchemaInfo(
        tables=[
            _table(
                "things",
                columns=[
                    _col("id", "int", pk=True),
                    ColumnInfo(name="mystery", data_type=""),
                ],
            )
        ]
    )
    issues = check_schema_completeness(s)
    assert any(i.kind == "empty_type" and i.table == "things" for i in issues)


def test_flags_column_with_whitespace_only_type():
    s = SchemaInfo(
        tables=[
            _table(
                "things",
                columns=[
                    ColumnInfo(name="x", data_type="   "),
                ],
            )
        ]
    )
    issues = check_schema_completeness(s)
    assert any(i.kind == "empty_type" for i in issues)


def test_column_with_valid_type_not_flagged():
    s = SchemaInfo(tables=[_table("ok", columns=[_col("id", "bigint", pk=True)])])
    issues = check_schema_completeness(s)
    assert not any(i.kind == "empty_type" for i in issues)


# ---------------------------------------------------------------------------
# fk_target_missing
# ---------------------------------------------------------------------------


def test_flags_fk_target_missing():
    s = SchemaInfo(
        tables=[
            _table(
                "orders",
                columns=[_col("uid", "int")],
                fks=[_fk("uid", "ghost")],
            )
        ]
    )
    assert any(i.kind == "fk_target_missing" for i in check_schema_completeness(s))


def test_fk_target_present_ok():
    s = SchemaInfo(
        tables=[
            _table("users", columns=[_col("id", "int", pk=True)]),
            _table(
                "orders",
                columns=[_col("uid", "int", pk=True)],
                fks=[_fk("uid", "users")],
            ),
        ]
    )
    assert not any(i.kind == "fk_target_missing" for i in check_schema_completeness(s))


def test_fk_target_case_insensitive_match():
    """FK target match is case-insensitive (DB names vary by engine)."""
    s = SchemaInfo(
        tables=[
            _table("Users", columns=[_col("id", "int", pk=True)]),
            _table(
                "orders",
                columns=[_col("uid", "int", pk=True)],
                fks=[_fk("uid", "users")],
            ),
        ]
    )
    assert not any(i.kind == "fk_target_missing" for i in check_schema_completeness(s))


def test_fk_qualified_reference_ok():
    """schema.table qualified reference resolves against the bare table name."""
    s = SchemaInfo(
        tables=[
            _table("users", columns=[_col("id", "int", pk=True)]),
            _table(
                "orders",
                columns=[_col("uid", "int", pk=True)],
                fks=[_fk("uid", "public.users")],
            ),
        ]
    )
    assert not any(i.kind == "fk_target_missing" for i in check_schema_completeness(s))


# ---------------------------------------------------------------------------
# no_pk
# ---------------------------------------------------------------------------


def test_flags_no_pk():
    s = SchemaInfo(tables=[_table("log", columns=[_col("msg", "text")])])
    assert any(i.kind == "no_pk" for i in check_schema_completeness(s))


def test_table_with_pk_not_flagged():
    s = SchemaInfo(tables=[_table("users", columns=[_col("id", "int", pk=True)])])
    assert not any(i.kind == "no_pk" for i in check_schema_completeness(s))


def test_view_without_pk_not_flagged():
    """Views and matviews are exempt from the PK requirement."""
    s = SchemaInfo(
        tables=[
            _table("v", columns=[_col("x", "int")], object_kind="view"),
        ]
    )
    assert not any(i.kind == "no_pk" for i in check_schema_completeness(s))


def test_matview_without_pk_not_flagged():
    s = SchemaInfo(
        tables=[
            _table("mv", columns=[_col("x", "int")], object_kind="matview"),
        ]
    )
    assert not any(i.kind == "no_pk" for i in check_schema_completeness(s))


# ---------------------------------------------------------------------------
# Clean schema — no issues
# ---------------------------------------------------------------------------


def test_complete_schema_returns_no_issues():
    s = SchemaInfo(
        tables=[
            _table("users", columns=[_col("id", "int", pk=True), _col("email", "text")]),
            _table(
                "orders",
                columns=[_col("id", "int", pk=True), _col("user_id", "int")],
                fks=[_fk("user_id", "users")],
            ),
        ]
    )
    assert check_schema_completeness(s) == []


# ---------------------------------------------------------------------------
# CompletenessIssue structure
# ---------------------------------------------------------------------------


def test_issue_has_expected_fields():
    s = SchemaInfo(tables=[_table("empty")])
    issues = check_schema_completeness(s)
    assert issues
    issue = issues[0]
    assert isinstance(issue, CompletenessIssue)
    assert issue.table
    assert issue.kind
    assert issue.detail


def test_empty_schema_returns_no_issues():
    assert check_schema_completeness(SchemaInfo(tables=[])) == []
