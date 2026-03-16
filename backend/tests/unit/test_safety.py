
from app.core.safety import SafetyGuard, SafetyLevel


class TestSafetyGuardReadOnly:
    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.READ_ONLY)

    def test_select_allowed(self):
        result = self.guard.validate_sql("SELECT * FROM users LIMIT 10")
        assert result.is_safe

    def test_select_with_join_allowed(self):
        result = self.guard.validate_sql(
            "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        )
        assert result.is_safe

    def test_insert_blocked(self):
        result = self.guard.validate_sql("INSERT INTO users (name) VALUES ('test')")
        assert not result.is_safe
        assert "DML" in result.reason

    def test_update_blocked(self):
        result = self.guard.validate_sql("UPDATE users SET name = 'test' WHERE id = 1")
        assert not result.is_safe

    def test_delete_blocked(self):
        result = self.guard.validate_sql("DELETE FROM users WHERE id = 1")
        assert not result.is_safe

    def test_drop_table_blocked(self):
        result = self.guard.validate_sql("DROP TABLE users")
        assert not result.is_safe
        assert "dangerous" in result.reason.lower() or "Blocked" in result.reason

    def test_truncate_blocked(self):
        result = self.guard.validate_sql("TRUNCATE users")
        assert not result.is_safe

    def test_alter_blocked(self):
        result = self.guard.validate_sql("ALTER TABLE users ADD COLUMN email VARCHAR(255)")
        assert not result.is_safe

    def test_create_table_blocked(self):
        result = self.guard.validate_sql("CREATE TABLE test (id INT PRIMARY KEY)")
        assert not result.is_safe


class TestSafetyGuardAllowDML:
    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.ALLOW_DML)

    def test_insert_allowed(self):
        result = self.guard.validate_sql("INSERT INTO users (name) VALUES ('test')")
        assert result.is_safe

    def test_update_allowed(self):
        result = self.guard.validate_sql("UPDATE users SET name = 'test' WHERE id = 1")
        assert result.is_safe

    def test_drop_still_blocked(self):
        result = self.guard.validate_sql("DROP TABLE users")
        assert not result.is_safe


class TestSafetyGuardMongo:
    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.READ_ONLY)

    def test_find_allowed(self):
        result = self.guard.validate_mongo('{"collection": "users", "operation": "find", "filter": {}}')
        assert result.is_safe

    def test_aggregate_allowed(self):
        result = self.guard.validate_mongo('{"collection": "users", "operation": "aggregate", "pipeline": []}')
        assert result.is_safe

    def test_delete_blocked(self):
        result = self.guard.validate_mongo('{"collection": "users", "operation": "delete", "filter": {}}')
        assert not result.is_safe

    def test_invalid_json_blocked(self):
        result = self.guard.validate_mongo("not json")
        assert not result.is_safe


class TestSafetyGuardUnrestricted:
    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.UNRESTRICTED)

    def test_everything_allowed(self):
        assert self.guard.validate("DROP TABLE users", "postgres").is_safe
        assert self.guard.validate("DELETE FROM users", "mysql").is_safe
