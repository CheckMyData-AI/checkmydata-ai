"""Tests for schema-aware pre-validator."""

from app.connectors.base import ColumnInfo, SchemaInfo, TableInfo
from app.core.pre_validator import PreValidator
from app.core.query_validation import QueryErrorType


def _schema() -> SchemaInfo:
    return SchemaInfo(
        tables=[
            TableInfo(
                name="users",
                columns=[
                    ColumnInfo(name="id", data_type="int"),
                    ColumnInfo(name="username", data_type="varchar"),
                    ColumnInfo(name="email", data_type="varchar"),
                ],
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(name="id", data_type="int"),
                    ColumnInfo(name="user_id", data_type="int"),
                    ColumnInfo(name="total", data_type="decimal"),
                ],
            ),
        ],
        db_type="postgresql",
    )


class TestPreValidator:
    def test_valid_query(self):
        v = PreValidator(_schema())
        result = v.validate(
            "SELECT users.username FROM users",
            "postgresql",
        )
        assert result.is_valid

    def test_wrong_table(self):
        v = PreValidator(_schema())
        result = v.validate(
            "SELECT * FROM userz",
            "postgresql",
        )
        assert not result.is_valid
        assert result.error is not None
        assert result.error.error_type == QueryErrorType.TABLE_NOT_FOUND

    def test_wrong_column_qualified(self):
        v = PreValidator(_schema())
        result = v.validate(
            "SELECT users.user_name FROM users",
            "postgresql",
        )
        assert not result.is_valid
        assert result.error is not None
        assert result.error.error_type == QueryErrorType.COLUMN_NOT_FOUND
        assert len(result.error.suggested_columns) > 0

    def test_ambiguous_column(self):
        v = PreValidator(_schema())
        result = v.validate(
            "SELECT id FROM users JOIN orders ON users.id = orders.user_id",
            "postgresql",
        )
        if not result.is_valid and result.error:
            assert result.error.error_type == QueryErrorType.AMBIGUOUS_COLUMN

    def test_mongodb_skipped(self):
        v = PreValidator(_schema())
        result = v.validate(
            '{"collection": "users", "operation": "find"}',
            "mongodb",
        )
        assert result.is_valid

    def test_valid_join(self):
        v = PreValidator(_schema())
        result = v.validate(
            "SELECT users.username, orders.total "
            "FROM users JOIN orders ON users.id = orders.user_id",
            "postgresql",
        )
        assert result.is_valid

    def test_fuzzy_suggestions(self):
        v = PreValidator(_schema())
        result = v.validate(
            "SELECT users.user_name FROM users",
            "postgresql",
        )
        assert not result.is_valid
        assert result.error is not None
        suggestions = result.error.suggested_columns
        assert len(suggestions) > 0

    def test_table_not_found_suggestions(self):
        v = PreValidator(_schema())
        result = v.validate(
            "SELECT * FROM userss",
            "postgresql",
        )
        assert not result.is_valid
        assert result.error is not None
        assert len(result.error.suggested_tables) > 0
