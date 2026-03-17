import pytest

from app.connectors.exec_templates import (
    EXEC_TEMPLATES,
    format_template,
    get_default_template,
)


class TestGetDefaultTemplate:
    def test_mysql(self):
        t = get_default_template("mysql")
        assert t is not None
        assert "mysql" in t
        assert "{db_host}" in t

    def test_postgres(self):
        t = get_default_template("postgres")
        assert t is not None
        assert "psql" in t

    def test_clickhouse(self):
        t = get_default_template("clickhouse")
        assert t is not None
        assert "clickhouse-client" in t

    def test_unknown(self):
        assert get_default_template("oracle") is None

    def test_mongodb_not_supported(self):
        assert get_default_template("mongodb") is None


class TestFormatTemplate:
    def test_substitution(self):
        template = "mysql -h {db_host} -P {db_port} -u {db_user} {db_name}"
        result = format_template(template, {
            "db_host": "10.0.0.1",
            "db_port": "3306",
            "db_user": "admin",
            "db_name": "analytics",
        })
        assert result == "mysql -h 10.0.0.1 -P 3306 -u admin analytics"

    def test_no_placeholders(self):
        template = "echo hello"
        result = format_template(template, {"db_host": "x"})
        assert result == "echo hello"

    def test_password_with_special_chars(self):
        template = 'MYSQL_PWD="{db_password}" mysql'
        result = format_template(template, {"db_password": "p@ss$w0rd"})
        assert result == 'MYSQL_PWD="p@ss$w0rd" mysql'

    def test_empty_values(self):
        template = "mysql -u {db_user} -p{db_password}"
        result = format_template(template, {"db_user": "", "db_password": ""})
        assert result == "mysql -u  -p"


class TestExecTemplatesStructure:
    @pytest.mark.parametrize("db_type", ["mysql", "postgres", "clickhouse"])
    def test_has_required_kinds(self, db_type: str):
        templates = EXEC_TEMPLATES[db_type]
        assert "query" in templates
        assert "test" in templates

    @pytest.mark.parametrize("db_type", ["mysql", "clickhouse"])
    def test_has_introspect_tables(self, db_type: str):
        templates = EXEC_TEMPLATES[db_type]
        assert "introspect_tables" in templates
        assert "introspect_columns" in templates

    def test_mysql_has_fks(self):
        assert "introspect_fks" in EXEC_TEMPLATES["mysql"]
