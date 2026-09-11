r"""Predefined command templates for SSH exec mode.

Templates use placeholders: {db_host}, {db_port}, {db_user}, {db_name}.
Password is passed via environment variable to avoid process-list exposure.

**The query is passed as an ARGUMENT, not on stdin** (SQL-01, 2026-09-11). It used to be
piped — `echo <sql> | psql …` — on the reasoning that a pipe avoids shell metacharacter
problems. It does, and it hands the text to a place where a different language applies:
`psql` reads client meta-commands from stdin in non-interactive mode exactly as it does
interactively, so `\!` runs a shell command on the bastion, `\copy … TO PROGRAM` runs one,
and `\i`/`\o` read and write files. `QUERY_ARG_FLAG` below carries each client's
"run this one statement" flag, where none of that is processed.
"""

import re

EXEC_TEMPLATES: dict[str, dict[str, str]] = {
    "mysql": {
        "query": (
            'MYSQL_PWD="$DBPASS" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
        ),
        "introspect_tables": (
            'MYSQL_PWD="$DBPASS" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            ' -e "SELECT table_name, table_rows, table_comment'
            " FROM information_schema.tables"
            " WHERE table_schema = '{db_name}' AND table_type = 'BASE TABLE'\""
        ),
        "introspect_columns": (
            'MYSQL_PWD="$DBPASS" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            ' -e "SELECT table_name, column_name, column_type, is_nullable,'
            " column_default, column_key, column_comment"
            " FROM information_schema.columns"
            " WHERE table_schema = '{db_name}'"
            ' ORDER BY table_name, ordinal_position"'
        ),
        "introspect_fks": (
            'MYSQL_PWD="$DBPASS" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            ' -e "SELECT table_name, column_name,'
            " referenced_table_name, referenced_column_name"
            " FROM information_schema.key_column_usage"
            " WHERE table_schema = '{db_name}'"
            ' AND referenced_table_name IS NOT NULL"'
        ),
        "test": (
            'MYSQL_PWD="$DBPASS" mysql'
            " -h {db_host} -P {db_port} -u {db_user} {db_name}"
            " --batch --raw"
            ' -e "SELECT 1 AS ok"'
        ),
    },
    "postgres": {
        "query": (
            'PGPASSWORD="$DBPASS" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -A -F $'\\t' --pset footer=off"
        ),
        "introspect_tables": (
            'PGPASSWORD="$DBPASS" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            ' -c "SELECT t.tablename, c.reltuples::bigint AS approx_rows'
            " FROM pg_tables t"
            " JOIN pg_class c ON c.relname = t.tablename"
            " JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.schemaname"
            " WHERE t.schemaname = 'public'"
            ' ORDER BY t.tablename"'
        ),
        "introspect_columns": (
            'PGPASSWORD="$DBPASS" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            ' -c "SELECT table_name, column_name, data_type, is_nullable,'
            " column_default"
            " FROM information_schema.columns"
            " WHERE table_schema = 'public'"
            ' ORDER BY table_name, ordinal_position"'
        ),
        "introspect_fks": (
            'PGPASSWORD="$DBPASS" psql'
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
            'PGPASSWORD="$DBPASS" psql'
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
            'PGPASSWORD="$DBPASS" psql'
            " -h {db_host} -p {db_port} -U {db_user} -d {db_name}"
            " -t -A -F $'\\t' --pset footer=off"
            ' -c "SELECT 1 AS ok"'
        ),
    },
    "clickhouse": {
        "query": (
            'CLICKHOUSE_PASSWORD="$DBPASS" clickhouse-client'
            " -h {db_host} --port {db_port} -u {db_user}"
            " -d {db_name}"
            " --format TabSeparatedWithNames"
        ),
        "introspect_tables": (
            'CLICKHOUSE_PASSWORD="$DBPASS" clickhouse-client'
            " -h {db_host} --port {db_port} -u {db_user}"
            " -d {db_name}"
            " --format TabSeparatedWithNames"
            " -q \"SELECT name FROM system.tables WHERE database = '{db_name}'\""
        ),
        "introspect_columns": (
            'CLICKHOUSE_PASSWORD="$DBPASS" clickhouse-client'
            " -h {db_host} --port {db_port} -u {db_user}"
            " -d {db_name}"
            " --format TabSeparatedWithNames"
            ' -q "SELECT table, name, type FROM system.columns'
            " WHERE database = '{db_name}'"
            ' ORDER BY table, position"'
        ),
        "test": (
            'CLICKHOUSE_PASSWORD="$DBPASS" clickhouse-client'
            " -h {db_host} --port {db_port} -u {db_user}"
            " -d {db_name}"
            " --format TabSeparatedWithNames"
            ' -q "SELECT 1 AS ok"'
        ),
    },
}


#: The flag each client takes a single statement on. This is the difference between the
#: query being DATA for the client and being INPUT to it.
QUERY_ARG_FLAG: dict[str, str] = {"postgres": "-c", "mysql": "-e", "clickhouse": "-q"}

#: How to ask each client for a session the ENGINE refuses writes in (SQL-02). Native
#: connectors have done this since they were written — `postgres.py:119`, `mysql.py:66`,
#: `clickhouse.py:119` — and ssh-exec never did, so on that connector `is_read_only` meant
#: only "this query may be retried after a reconnect" and the guard's regex was the whole
#: defence.
#:
#: Applied by substring surgery on the client invocation, which is why it works only for the
#: templates in this file: a custom template names a client this module has never heard of,
#: and guessing its flags would produce a command that either fails or silently does nothing.
#: `SSHExecConnector._build_command` warns in that case rather than implying enforcement.
READ_ONLY_DECORATION: dict[str, tuple[str, str]] = {
    # (what to find, what to replace it with)
    "postgres": (
        'PGPASSWORD="$DBPASS" psql',
        "PGOPTIONS='-c default_transaction_read_only=on' PGPASSWORD=\"$DBPASS\" psql",
    ),
    "mysql": ("mysql", 'mysql --init-command="SET SESSION TRANSACTION READ ONLY"'),
    "clickhouse": ("clickhouse-client", "clickhouse-client --readonly=1"),
}


def apply_read_only(template: str, db_type: str) -> str | None:
    """Return *template* asking for an engine-enforced read-only session, or ``None``.

    ``None`` means this module cannot decorate that template — an unknown ``db_type``, or a
    client whose invocation is not in it. The caller must treat that as "not enforced" and
    say so, never as "nothing to do".
    """
    decoration = READ_ONLY_DECORATION.get(db_type)
    if not decoration:
        return None
    needle, replacement = decoration
    if needle not in template:
        return None
    return template.replace(needle, replacement, 1)


#: Shell metacharacters a command template may not contain. Deliberately the SAME pattern
#: `ssh_pre_commands` is screened with — the two halves end up on one shell line joined by
#: `&&`, and screening one of them was the whole defect (SQL-06). `"$DBPASS"` and `$'\t'`
#: survive it: a bare `$VAR` expansion is not command substitution, `$(` is.
_TEMPLATE_DANGEROUS = re.compile(r"[;&|<>\n\r`]|\$\(")

#: Long enough for every template in this file with room to spare; short enough that the
#: field cannot become a shell script.
MAX_TEMPLATE_LENGTH = 2000


class CommandTemplateValidationError(ValueError):
    """Raised when ``ssh_command_template`` carries something a template must not (SQL-06)."""


def validate_command_template(template: str) -> str:
    """Validate a custom ``ssh_command_template``; return it unchanged.

    Checked at save **and** at build time. Saving alone is not enough: a row written before
    this function existed would otherwise keep running, and the reason to validate a field
    is so that everything downstream may stop assuming it is hostile.
    """
    if not isinstance(template, str) or not template.strip():
        raise CommandTemplateValidationError("ssh_command_template must be a non-empty string")
    if len(template) > MAX_TEMPLATE_LENGTH:
        raise CommandTemplateValidationError(
            f"ssh_command_template exceeds {MAX_TEMPLATE_LENGTH} characters"
        )
    match = _TEMPLATE_DANGEROUS.search(template)
    if match:
        raise CommandTemplateValidationError(
            "ssh_command_template contains forbidden shell metacharacters "
            f"({match.group(0)!r}): it is joined onto one shell line with ssh_pre_commands, "
            "which are screened for exactly these"
        )
    return template


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


def _sql_literal_escape(value: str) -> str:
    """Escape a value that sits inside a SQL single-quoted literal, inside shell double quotes.

    Two languages, in this order: the SQL literal is closed by a single quote, which SQL
    escapes by doubling; then the surrounding double-quoted shell word is escaped as usual.

    SQL-13: this context had no branch at all, so `_shell_escape` — which quotes for a BARE
    shell word — ran on it. A database called `my db` became `\'\'my db\'\'`, malformed SQL for
    any ordinary multi-word name, and a name containing a quote reached the database's parser
    with no SQL escaping whatsoever.
    """
    return _dquote_escape(value.replace("'", "''"))


def format_template(template: str, config_vars: dict[str, str]) -> str:
    """Substitute placeholders in a template string.

    **Every** value is shell-escaped. When a placeholder sits inside double quotes
    (e.g. "{db_password}"), the value is escaped for double-quote context. Otherwise
    it is single-quoted for bare shell context.

    F-SSH-04: ``db_port`` used to be excluded. It was not exploitable — the request
    schema bounds it (``db_port: int | None = Field(ge=1, le=65535)``), the column is
    ``Integer``, and both ``ConnectionConfig`` construction sites build from the model,
    so a metacharacter has no path in. But that guarantee was spread across three
    files and two call sites, and escaping costs nothing: ``shlex.quote`` of digits
    returns the digits. An allowlist of *which values are dangerous* is the kind of
    list that goes stale when a template gains a placeholder; escaping everything
    cannot.
    """
    result = template
    for key, value in config_vars.items():
        placeholder = f"{{{key}}}"
        sq_placeholder = f"'{placeholder}'"
        dq_placeholder = f'"{placeholder}"'
        # Order matters: the SQL-literal form is the most specific and sits INSIDE the
        # double-quoted form in every introspection template.
        if sq_placeholder in result:
            result = result.replace(sq_placeholder, "'" + _sql_literal_escape(value) + "'")
        if dq_placeholder in result:
            result = result.replace(dq_placeholder, '"' + _dquote_escape(value) + '"')
        if placeholder in result:
            result = result.replace(placeholder, _shell_escape(value))
    return result
