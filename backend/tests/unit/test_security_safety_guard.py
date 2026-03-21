"""Security hardening tests for the SafetyGuard.

Covers SQL injection patterns, CTE-wrapped DML bypass attempts,
multi-statement attacks, and dialect-specific edge cases.
"""

from app.core.safety import SafetyGuard, SafetyLevel


class TestSQLInjectionPatterns:
    """Adversarial patterns an LLM might generate."""

    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.READ_ONLY)

    def test_cte_wrapping_insert(self):
        query = "WITH x AS (SELECT 1) INSERT INTO users (name) VALUES ('hack')"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_cte_wrapping_delete(self):
        query = "WITH x AS (SELECT 1) DELETE FROM users WHERE id = 1"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_create_table_as_select(self):
        query = "CREATE TABLE exfil AS SELECT * FROM users"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_insert_into_select(self):
        query = "INSERT INTO backup SELECT * FROM users"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_multi_statement_with_semicolon(self):
        query = "SELECT 1; DROP TABLE users"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_multi_statement_with_semicolon_and_newline(self):
        query = "SELECT * FROM users;\nDROP TABLE users"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_drop_database(self):
        query = "DROP DATABASE production"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_drop_schema(self):
        query = "DROP SCHEMA public CASCADE"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_grant_privilege(self):
        query = "GRANT ALL PRIVILEGES ON *.* TO 'hacker'@'%'"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_revoke_privilege(self):
        query = "REVOKE SELECT ON users FROM readonly_user"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_alter_table_drop_column(self):
        query = "ALTER TABLE users DROP COLUMN password_hash"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_create_user(self):
        query = "CREATE USER hacker IDENTIFIED BY 'password'"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_create_role(self):
        query = "CREATE ROLE admin"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_truncate_with_schema(self):
        query = "TRUNCATE TABLE public.users"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_update_with_subquery(self):
        query = "UPDATE users SET role = 'admin' WHERE id = (SELECT id FROM users LIMIT 1)"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_delete_with_join(self):
        query = "DELETE FROM users USING sessions WHERE users.id = sessions.user_id"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_case_variation_drop(self):
        query = "dRoP tAbLe users"
        result = self.guard.validate_sql(query)
        assert not result.is_safe

    def test_case_variation_insert(self):
        query = "iNsErT iNtO users (name) VALUES ('x')"
        result = self.guard.validate_sql(query)
        assert not result.is_safe


class TestSafeQueriesAllDialects:
    """Legitimate queries that MUST pass for each dialect."""

    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.READ_ONLY)

    def test_postgres_cte_select(self):
        query = """
        WITH monthly AS (
            SELECT date_trunc('month', created_at) AS month, COUNT(*) AS cnt
            FROM orders GROUP BY 1
        )
        SELECT * FROM monthly ORDER BY month
        """
        assert self.guard.validate_sql(query).is_safe

    def test_mysql_backtick_identifiers(self):
        query = (
            "SELECT `user`.`name`, `order`.`total` "
            "FROM `user` JOIN `order` "
            "ON `user`.`id` = `order`.`user_id`"
        )
        assert self.guard.validate_sql(query).is_safe

    def test_postgres_schema_prefix(self):
        query = 'SELECT * FROM "public"."users" WHERE "created_at" > NOW() - INTERVAL \'30 days\''
        assert self.guard.validate_sql(query).is_safe

    def test_clickhouse_approximate_functions(self):
        query = "SELECT uniqExact(user_id), quantile(0.95)(response_time) FROM events"
        assert self.guard.validate_sql(query).is_safe

    def test_window_function(self):
        query = """
        SELECT user_id, amount,
               ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) AS rn
        FROM orders
        """
        assert self.guard.validate_sql(query).is_safe

    def test_explain_query(self):
        query = "EXPLAIN SELECT * FROM users WHERE email = 'test@test.com'"
        assert self.guard.validate_sql(query).is_safe

    def test_show_tables(self):
        query = "SHOW TABLES"
        assert self.guard.validate_sql(query).is_safe

    def test_information_schema(self):
        query = (
            "SELECT table_name, column_name "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
        assert self.guard.validate_sql(query).is_safe

    def test_union_select(self):
        query = "SELECT id, name FROM users UNION ALL SELECT id, title FROM products"
        assert self.guard.validate_sql(query).is_safe

    def test_select_with_limit_offset(self):
        query = "SELECT * FROM orders ORDER BY created_at DESC LIMIT 100 OFFSET 50"
        assert self.guard.validate_sql(query).is_safe


class TestMongoSecurityPatterns:
    """MongoDB write operation blocking."""

    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.READ_ONLY)

    def test_insert_blocked(self):
        result = self.guard.validate_mongo(
            '{"collection": "users", "operation": "insert", "document": {"name": "hack"}}'
        )
        assert not result.is_safe

    def test_update_blocked(self):
        mongo_op = (
            '{"collection": "users", "operation": "update",'
            ' "filter": {}, "update": {"$set": {"admin": true}}}'
        )
        result = self.guard.validate_mongo(mongo_op)
        assert not result.is_safe

    def test_drop_blocked(self):
        result = self.guard.validate_mongo('{"collection": "users", "operation": "drop"}')
        assert not result.is_safe

    def test_rename_blocked(self):
        result = self.guard.validate_mongo('{"collection": "users", "operation": "rename"}')
        assert not result.is_safe

    def test_create_index_blocked(self):
        result = self.guard.validate_mongo('{"collection": "users", "operation": "create_index"}')
        assert not result.is_safe

    def test_drop_index_blocked(self):
        result = self.guard.validate_mongo('{"collection": "users", "operation": "drop_index"}')
        assert not result.is_safe

    def test_count_allowed(self):
        result = self.guard.validate_mongo(
            '{"collection": "users", "operation": "count_documents", "filter": {}}'
        )
        assert result.is_safe

    def test_distinct_allowed(self):
        result = self.guard.validate_mongo(
            '{"collection": "users", "operation": "distinct", "field": "country"}'
        )
        assert result.is_safe


class TestValidateDispatch:
    """Test the validate() dispatcher picks correct handler."""

    def setup_method(self):
        self.guard = SafetyGuard(level=SafetyLevel.READ_ONLY)

    def test_postgres_dispatch(self):
        result = self.guard.validate("DROP TABLE users", "postgres")
        assert not result.is_safe

    def test_mysql_dispatch(self):
        result = self.guard.validate("DROP TABLE users", "mysql")
        assert not result.is_safe

    def test_clickhouse_dispatch(self):
        result = self.guard.validate("DROP TABLE users", "clickhouse")
        assert not result.is_safe

    def test_mongo_dispatch(self):
        result = self.guard.validate(
            '{"collection": "users", "operation": "delete", "filter": {}}',
            "mongodb",
        )
        assert not result.is_safe

    def test_mongo_alias_dispatch(self):
        result = self.guard.validate(
            '{"collection": "users", "operation": "delete", "filter": {}}',
            "mongo",
        )
        assert not result.is_safe
