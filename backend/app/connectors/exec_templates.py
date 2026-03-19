"""Predefined command templates for SSH exec mode.

Templates use placeholders: {db_host}, {db_port}, {db_user}, {db_name}.
Password is passed via environment variable to avoid process-list exposure.
Query is piped via stdin to avoid shell metacharacter issues.
"""

import re

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
            ' -e "SELECT table_name, table_rows, table_comment'
            " FROM information_schema.tables"
            " WHERE table_schema = '{db_name}' AND table_type = 'BASE TABLE'\""
        ),
        "introspect_columns": (
            'MYSQL_PWD="{db_password}" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            ' -e "SELECT table_name, column_name, column_type, is_nullable,'
            " column_default, column_key, column_comment"
            " FROM information_schema.columns"
            " WHERE table_schema = '{db_name}'"
            ' ORDER BY table_name, ordinal_position"'
        ),
        "introspect_fks": (
            'MYSQL_PWD="{db_password}" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            ' -e "SELECT table_name, column_name,'
            " referenced_table_name, referenced_column_name"
            " FROM information_schema.key_column_usage"
            " WHERE table_schema = '{db_name}'"
            ' AND referenced_table_name IS NOT NULL"'
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
            " -A -F $'\\t' --pset footer=off"
        ),
        "introspect_tables": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            " -c \"SELECT t.tablename, c.reltuples::bigint AS approx_rows"
            " FROM pg_tables t"
            " JOIN pg_class c ON c.relname = t.tablename"
            " JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.schemaname"
            " WHERE t.schemaname = 'public'"
            ' ORDER BY t.tablename"'
        ),
        "introspect_columns": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            ' -c "SELECT table_name, column_name, data_type, is_nullable,'
            " column_default"
            " FROM information_schema.columns"
            " WHERE table_schema = 'public'"
            ' ORDER BY table_name, ordinal_position"'
        ),
        "introspect_fks": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            ' -c "SELECT cl_child.relname AS table_name,'
            " a_child.attname AS column_name,"
            " cl_parent.relname AS references_table,"
            " a_parent.attname AS references_column"
            " FROM pg_constraint con"
            " JOIN pg_class cl_child ON cl_child.oid = con.conrelid"
            " JOIN pg_namespace ns ON ns.oid = cl_child.relnamespace"
            " JOIN pg_class cl_parent ON cl_parent.oid = con.confrelid"
            " CROSS JOIN LATERAL unnest(con.conkey, con.confkey)"
            "   WITH ORDINALITY AS u(child_attnum, parent_attnum, ord)"
            " JOIN pg_attribute a_child ON a_child.attrelid = con.conrelid"
            "   AND a_child.attnum = u.child_attnum"
            " JOIN pg_attribute a_parent ON a_parent.attrelid = con.confrelid"
            "   AND a_parent.attnum = u.parent_attnum"
            " WHERE con.contype = 'f'"
            "   AND ns.nspname = 'public'"
            ' ORDER BY cl_child.relname"'
        ),
        "introspect_indexes": (
            'PGPASSWORD="{db_password}" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            ' -c "SELECT tc.relname AS table_name,'
            " ic.relname AS index_name,"
            " i.indisunique::text,"
            " array_to_string(array_agg(a.attname ORDER BY k.n), ',')"
            " FROM pg_index i"
            " JOIN pg_class ic ON ic.oid = i.indexrelid"
            " JOIN pg_class tc ON tc.oid = i.indrelid"
            " JOIN pg_namespace ns ON ns.oid = tc.relnamespace"
            " CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, n)"
            " JOIN pg_attribute a ON a.attrelid = tc.oid AND a.attnum = k.attnum"
            " WHERE NOT i.indisprimary AND ns.nspname = 'public'"
            ' GROUP BY tc.relname, ic.relname, i.indisunique"'
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
            ' -q "SELECT table, name, type FROM system.columns'
            " WHERE database = '{db_name}'"
            ' ORDER BY table, position"'
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


_SHELL_SAFE_RE = re.compile(r"^[a-zA-Z0-9._@/:=-]+$")


def _shell_escape(value: str) -> str:
    """Escape a value for safe embedding in a bare (unquoted) shell context.

    Values that are purely alphanumeric (plus safe chars) pass through unchanged.
    All others are single-quoted with internal single quotes escaped.
    """
    if not value:
        return "''"
    if _SHELL_SAFE_RE.match(value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _dquote_escape(value: str) -> str:
    """Escape a value for safe embedding inside double quotes."""
    if not value:
        return value
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def format_template(template: str, config_vars: dict[str, str]) -> str:
    """Substitute placeholders in a template string.

    Values for db_name, db_user, db_host, and db_password are shell-escaped.
    When a placeholder sits inside double quotes (e.g. "{db_password}"),
    the value is escaped for double-quote context. Otherwise it is
    single-quoted for bare shell context.
    """
    _escape_keys = {"db_name", "db_user", "db_host", "db_password"}
    result = template
    for key, value in config_vars.items():
        placeholder = f"{{{key}}}"
        if key not in _escape_keys:
            result = result.replace(placeholder, value)
            continue
        dq_placeholder = f'"{placeholder}"'
        if dq_placeholder in result:
            result = result.replace(dq_placeholder, '"' + _dquote_escape(value) + '"')
        if placeholder in result:
            result = result.replace(placeholder, _shell_escape(value))
    return result
