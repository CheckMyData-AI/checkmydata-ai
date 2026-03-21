"""Unit tests for _compute_sql_complexity in the chat routes."""

from app.api.routes.chat import _compute_sql_complexity


class TestComputeSqlComplexity:
    def test_simple_select(self):
        assert _compute_sql_complexity("SELECT * FROM users") == "simple"

    def test_simple_with_where(self):
        assert _compute_sql_complexity("SELECT id, name FROM orders WHERE total > 100") == "simple"

    def test_moderate_single_join(self):
        sql = "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        assert _compute_sql_complexity(sql) == "moderate"

    def test_moderate_two_joins(self):
        sql = (
            "SELECT u.name, o.total, p.name "
            "FROM users u "
            "JOIN orders o ON u.id = o.user_id "
            "JOIN products p ON o.product_id = p.id"
        )
        assert _compute_sql_complexity(sql) == "moderate"

    def test_complex_with_cte(self):
        sql = "WITH active AS (SELECT * FROM users WHERE active = true) SELECT * FROM active"
        assert _compute_sql_complexity(sql) == "complex"

    def test_complex_with_window_function(self):
        sql = (
            "SELECT name, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) FROM employees"
        )
        assert _compute_sql_complexity(sql) == "complex"

    def test_complex_with_subquery(self):
        sql = "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE total > 1000)"
        assert _compute_sql_complexity(sql) == "complex"

    def test_complex_many_joins(self):
        sql = (
            "SELECT * FROM a "
            "JOIN b ON a.id = b.a_id "
            "JOIN c ON b.id = c.b_id "
            "JOIN d ON c.id = d.c_id"
        )
        assert _compute_sql_complexity(sql) == "complex"

    def test_expert_recursive_cte(self):
        sql = (
            "WITH RECURSIVE tree AS ("
            "  SELECT id, parent_id, name FROM categories WHERE parent_id IS NULL "
            "  UNION ALL "
            "  SELECT c.id, c.parent_id, c.name FROM categories c JOIN tree t ON c.parent_id = t.id"
            ") SELECT * FROM tree"
        )
        assert _compute_sql_complexity(sql) == "expert"

    def test_expert_cte_with_window(self):
        sql = (
            "WITH monthly AS (SELECT date_trunc('month', created_at) "
            "AS month, COUNT(*) AS cnt FROM orders GROUP BY 1) "
            "SELECT month, cnt, AVG(cnt) OVER "
            "(ORDER BY month ROWS BETWEEN 2 PRECEDING "
            "AND CURRENT ROW) FROM monthly"
        )
        assert _compute_sql_complexity(sql) == "expert"

    def test_case_insensitive(self):
        sql = "select * from users join orders on users.id = orders.user_id"
        assert _compute_sql_complexity(sql) == "moderate"
