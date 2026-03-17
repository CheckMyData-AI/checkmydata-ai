"""Tests for post-execution validator."""

from app.connectors.base import QueryResult, SchemaInfo
from app.core.post_validator import PostValidator
from app.core.query_validation import QueryErrorType, ValidationConfig


class TestPostValidator:
    def setup_method(self):
        self.validator = PostValidator()
        self.schema = SchemaInfo(db_type="postgresql", db_name="test")
        self.config = ValidationConfig()

    def test_success(self):
        result = QueryResult(
            columns=["id"],
            rows=[[1]],
            row_count=1,
            execution_time_ms=50,
        )
        vr = self.validator.validate(result, "SELECT 1", self.schema, self.config)
        assert vr.is_valid

    def test_db_error(self):
        result = QueryResult(error='column "bad" does not exist')
        vr = self.validator.validate(
            result,
            "SELECT bad FROM users",
            self.schema,
            self.config,
        )
        assert not vr.is_valid
        assert vr.error is not None

    def test_empty_result_no_retry(self):
        config = ValidationConfig(empty_result_retry=False)
        result = QueryResult(
            columns=["id"],
            rows=[],
            row_count=0,
            execution_time_ms=10,
        )
        vr = self.validator.validate(
            result,
            "SELECT * FROM empty_table",
            self.schema,
            config,
        )
        assert vr.is_valid
        assert any("0 rows" in w for w in vr.warnings)

    def test_empty_result_with_retry(self):
        config = ValidationConfig(empty_result_retry=True)
        result = QueryResult(
            columns=["id"],
            rows=[],
            row_count=0,
            execution_time_ms=10,
        )
        vr = self.validator.validate(
            result,
            "SELECT * FROM empty_table",
            self.schema,
            config,
        )
        assert not vr.is_valid
        assert vr.error is not None
        assert vr.error.error_type == QueryErrorType.EMPTY_RESULT

    def test_slow_query_warning(self):
        config = ValidationConfig(query_timeout_seconds=1)
        result = QueryResult(
            columns=["id"],
            rows=[[1]],
            row_count=1,
            execution_time_ms=2000,
        )
        vr = self.validator.validate(
            result,
            "SELECT * FROM big_table",
            self.schema,
            config,
        )
        assert vr.is_valid
        assert any("slow" in w.lower() for w in vr.warnings)
