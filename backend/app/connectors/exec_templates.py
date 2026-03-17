"""Predefined command templates for SSH exec mode.

Templates use placeholders: {db_host}, {db_port}, {db_user}, {db_name}.
Password is passed via environment variable to avoid process-list exposure.
Query is piped via stdin to avoid shell metacharacter issues.
"""

EXEC_TEMPLATES: dict[str, dict[str, str]] = {
    "mysql": {
        "query": (
            'MYSQL_PWD="{db_password}" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
        ),
        "introspect_tables": (
            'MYSQL_PWD="{db_password}" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            " -e \"SELECT table_name, table_rows, table_comment"
            " FROM information_schema.tables"
            " WHERE table_schema = '{db_name}' AND table_type = 'BASE TABLE'\""
        ),
        "introspect_columns": (
            'MYSQL_PWD="{db_password}" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            " -e \"SELECT table_name, column_name, column_type, is_nullable,"
            " column_default, column_key, column_comment"
            " FROM information_schema.columns"
            " WHERE table_schema = '{db_name}'"
            " ORDER BY table_name, ordinal_position\""
        ),
        "introspect_fks": (
            'MYSQL_PWD="{db_password}" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            " -e \"SELECT table_name, column_name,"
            " referenced_table_name, referenced_column_name"
            " FROM information_schema.key_column_usage"
            " WHERE table_schema = '{db_name}'"
            " AND referenced_table_name IS NOT NULL\""
        ),
        "test": (
            'MYSQL_PWD="{db_password}" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            ' -e "SELECT 1 AS ok"'
        ),
    },
    "postgres": {
        "query": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off --csv"
        ),
        "introspect_tables": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            " -c \"SELECT tablename FROM pg_tables WHERE schemaname = 'public'\""
        ),
        "introspect_columns": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            " -c \"SELECT table_name, column_name, data_type, is_nullable,"
            " column_default"
            " FROM information_schema.columns"
            " WHERE table_schema = 'public'"
            " ORDER BY table_name, ordinal_position\""
        ),
        "test": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            ' -c "SELECT 1 AS ok"'
        ),
    },
    "clickhouse": {
        "query": (
            "clickhouse-client"
            " -h {db_host} --port {db_port} -u {db_user}"
            ' --password "{db_password}" -d {db_name}'
            " --format TabSeparatedWithNames"
        ),
        "introspect_tables": (
            "clickhouse-client"
            " -h {db_host} --port {db_port} -u {db_user}"
            ' --password "{db_password}" -d {db_name}'
            " --format TabSeparatedWithNames"
            " -q \"SELECT name FROM system.tables WHERE database = '{db_name}'\""
        ),
        "introspect_columns": (
            "clickhouse-client"
            " -h {db_host} --port {db_port} -u {db_user}"
            ' --password "{db_password}" -d {db_name}'
            " --format TabSeparatedWithNames"
            " -q \"SELECT table, name, type FROM system.columns"
            " WHERE database = '{db_name}'"
            " ORDER BY table, position\""
        ),
        "test": (
            "clickhouse-client"
            " -h {db_host} --port {db_port} -u {db_user}"
            ' --password "{db_password}" -d {db_name}'
            " --format TabSeparatedWithNames"
            ' -q "SELECT 1 AS ok"'
        ),
    },
}


def get_default_template(db_type: str) -> str | None:
    """Return the default query template for a db type, or None if unsupported."""
    templates = EXEC_TEMPLATES.get(db_type)
    if templates:
        return templates["query"]
    return None


def format_template(template: str, config_vars: dict[str, str]) -> str:
    """Substitute placeholders in a template string."""
    result = template
    for key, value in config_vars.items():
        result = result.replace(f"{{{key}}}", value)
    return result
