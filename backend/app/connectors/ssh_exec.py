"""SSH Exec Connector: execute database queries via SSH command execution.

Instead of port-forwarding + native DB driver, this connector SSHes into the
remote server and runs queries through the CLI client (mysql, psql, etc.).
"""

import asyncio
import logging
import shlex
import time
from typing import Any

import asyncssh

from app.config import settings
from app.connectors.base import (
    BaseConnector,
    ColumnInfo,
    ConnectionConfig,
    ForeignKeyInfo,
    IndexInfo,
    QueryResult,
    SchemaInfo,
    TableInfo,
)
from app.connectors.cli_output_parser import MAX_OUTPUT_BYTES, CLIOutputParser
from app.connectors.exec_templates import (
    EXEC_TEMPLATES,
    format_template,
)

logger = logging.getLogger(__name__)

SSH_CONNECT_TIMEOUT = settings.ssh_connect_timeout
SSH_COMMAND_TIMEOUT = settings.ssh_command_timeout


class SSHExecConnector(BaseConnector):
    """Execute queries via SSH command execution instead of port forwarding."""

    def __init__(self) -> None:
        self._conn: asyncssh.SSHClientConnection | None = None
        self._config: ConnectionConfig | None = None
        self._reconnect_lock = asyncio.Lock()

    @property
    def db_type(self) -> str:
        return self._config.db_type if self._config else "unknown"

    def _config_vars(self) -> dict[str, str]:
        """Build template substitution variables from config."""
        c = self._config
        if not c:
            return {}
        return {
            "db_host": c.db_host,
            "db_port": str(c.db_port),
            "db_user": c.db_user or "",
            "db_password": c.db_password or "",
            "db_name": c.db_name,
        }

    def _get_template(self, kind: str) -> str:
        """Get the command template for a given kind (query, test, introspect_*)."""
        if kind == "query" and self._config and self._config.ssh_command_template:
            return self._config.ssh_command_template

        db_type = self._config.db_type if self._config else ""
        templates = EXEC_TEMPLATES.get(db_type, {})
        template = templates.get(kind)
        if not template:
            raise ValueError(
                f"No exec template for db_type={db_type!r}, kind={kind!r}. "
                f"Provide a custom ssh_command_template."
            )
        return template

    def _prepend_pre_commands(self, cmd: str) -> str:
        """Prepend ssh_pre_commands (e.g. PATH exports) to any command string."""
        pre = self._config.ssh_pre_commands if self._config else None
        if pre:
            return " && ".join(pre) + " && " + cmd
        return cmd

    def _build_command(self, kind: str, query: str | None = None) -> str:
        """Build the full SSH command string."""
        template = self._get_template(kind)
        variables = self._config_vars()
        cmd = format_template(template, variables)

        if query is not None and kind == "query":
            cmd = f"echo {shlex.quote(query)} | {cmd}"

        return self._prepend_pre_commands(cmd)

    async def connect(self, config: ConnectionConfig) -> None:
        self._config = config
        if not config.ssh_host:
            raise ValueError("SSH host is required for exec mode")

        connect_kwargs: dict[str, Any] = {
            "host": (config.ssh_host or "").strip(),
            "port": config.ssh_port,
            "username": (config.ssh_user or "").strip(),
            "known_hosts": None,
            "login_timeout": SSH_CONNECT_TIMEOUT,
            "connect_timeout": SSH_CONNECT_TIMEOUT,
            "keepalive_interval": 15,
        }
        if config.ssh_key_content:
            key = asyncssh.import_private_key(
                config.ssh_key_content.strip(),
                config.ssh_key_passphrase,
            )
            connect_kwargs["client_keys"] = [key]

        self._conn = await asyncio.wait_for(
            asyncssh.connect(**connect_kwargs),
            timeout=SSH_CONNECT_TIMEOUT + 10,
        )
        logger.info(
            "SSH exec connection established to %s:%d as %s",
            config.ssh_host,
            config.ssh_port,
            config.ssh_user,
        )

    async def disconnect(self) -> None:
        if self._conn:
            logger.debug("Disconnecting SSH exec session")
            try:
                self._conn.close()
                await asyncio.sleep(0.1)
                try:
                    await asyncio.wait_for(self._conn.wait_closed(), timeout=5)
                except Exception as exc:
                    logger.warning("SSH exec disconnect did not complete cleanly: %s", exc)
            finally:
                self._conn = None

    async def _run_command(
        self, command: str, timeout: int = SSH_COMMAND_TIMEOUT
    ) -> tuple[str, str, int]:
        """Run a command over SSH and return (stdout, stderr, exit_code).

        Automatically attempts one reconnection if the SSH connection is lost.
        """
        if not self._conn:
            raise RuntimeError("Not connected")

        try:
            result = await self._conn.run(command, timeout=timeout, check=False)
        except (asyncssh.ConnectionLost, asyncssh.DisconnectError, BrokenPipeError, OSError) as exc:
            logger.warning("SSH connection lost (%s), attempting reconnect", exc)
            async with self._reconnect_lock:
                if self._conn is None or not self._config:
                    if not self._config:
                        raise RuntimeError(
                            "SSH connection lost and no config to reconnect"
                        ) from exc
                    await self.connect(self._config)
                elif self._conn:
                    try:
                        _chk = await self._conn.run(
                            "echo __SSH_EXEC_ALIVE__",
                            timeout=5,
                            check=False,
                        )
                        if "__SSH_EXEC_ALIVE__" not in (_chk.stdout or ""):
                            raise RuntimeError("marker not in stdout")
                    except Exception:
                        self._conn = None
                        await self.connect(self._config)
            if not self._conn:
                raise RuntimeError("Reconnect failed")
            result = await self._conn.run(command, timeout=timeout, check=False)

        stdout = str(result.stdout or "")
        stderr = str(result.stderr or "")

        if len(stdout) > MAX_OUTPUT_BYTES:
            stdout = stdout[:MAX_OUTPUT_BYTES]
            logger.warning("SSH exec output truncated to %d bytes", MAX_OUTPUT_BYTES)

        return stdout, stderr, result.exit_status if result.exit_status is not None else -1

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        start = time.monotonic()
        try:
            command = self._build_command("query", query)
            stdout, stderr, exit_code = await self._run_command(command)
            elapsed = (time.monotonic() - start) * 1000

            if exit_code != 0:
                error_msg = stderr.strip() or f"Command exited with code {exit_code}"
                return QueryResult(error=error_msg, execution_time_ms=elapsed)

            if not stdout.strip():
                return QueryResult(row_count=0, execution_time_ms=elapsed)

            columns, rows = CLIOutputParser.detect_and_parse(stdout, self.db_type)
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed,
            )
        except asyncssh.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning("SSH exec query timed out after %.0fms", elapsed)
            return QueryResult(error="SSH command timed out", execution_time_ms=elapsed)
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning("SSH exec execute_query error: %s", e)
            return QueryResult(error=str(e), execution_time_ms=elapsed)

    async def introspect_schema(self) -> SchemaInfo:
        if not self._config:
            return SchemaInfo(db_type="unknown")

        db_type = self._config.db_type
        db_name = self._config.db_name

        if db_type == "mysql":
            return await self._introspect_mysql(db_name)
        elif db_type in ("postgres", "postgresql"):
            return await self._introspect_postgres(db_name)
        elif db_type == "clickhouse":
            return await self._introspect_clickhouse(db_name)
        else:
            return await self._introspect_via_query(db_name, db_type)

    def _check_introspection_result(
        self,
        step: str,
        stdout: str,
        stderr: str,
        exit_code: int,
    ) -> None:
        if exit_code != 0:
            logger.warning(
                "SSH exec introspection '%s' failed (exit=%d): %s",
                step,
                exit_code,
                stderr.strip()[:300],
            )
        elif stderr.strip():
            logger.debug("SSH exec introspection '%s' stderr: %s", step, stderr.strip()[:200])

    async def _introspect_mysql(self, db_name: str) -> SchemaInfo:
        variables = self._config_vars()

        tables_cmd = self._prepend_pre_commands(
            format_template(self._get_template("introspect_tables"), variables)
        )
        stdout, stderr, exit_code = await self._run_command(tables_cmd)
        self._check_introspection_result("mysql:tables", stdout, stderr, exit_code)
        _, table_rows = CLIOutputParser.parse_tsv_with_headers(stdout)

        cols_cmd = self._prepend_pre_commands(
            format_template(self._get_template("introspect_columns"), variables)
        )
        stdout, stderr, exit_code = await self._run_command(cols_cmd)
        self._check_introspection_result("mysql:columns", stdout, stderr, exit_code)
        _, col_rows = CLIOutputParser.parse_tsv_with_headers(stdout)

        fks_cmd = self._prepend_pre_commands(
            format_template(self._get_template("introspect_fks"), variables)
        )
        stdout, stderr, exit_code = await self._run_command(fks_cmd)
        self._check_introspection_result("mysql:fks", stdout, stderr, exit_code)
        _, fk_rows = CLIOutputParser.parse_tsv_with_headers(stdout)

        fk_map: dict[str, list[ForeignKeyInfo]] = {}
        for fk in fk_rows:
            if len(fk) >= 4:
                tname = fk[0]
                fk_map.setdefault(tname, []).append(
                    ForeignKeyInfo(column=fk[1], references_table=fk[2], references_column=fk[3])
                )

        col_map: dict[str, list[ColumnInfo]] = {}
        for c in col_rows:
            if len(c) >= 5:
                tname = c[0]
                col_map.setdefault(tname, []).append(
                    ColumnInfo(
                        name=c[1],
                        data_type=c[2],
                        is_nullable=c[3] == "YES",
                        default=c[4] if c[4] != "NULL" else None,
                        is_primary_key=c[5] == "PRI" if len(c) > 5 else False,
                        comment=c[6] if len(c) > 6 and c[6] != "NULL" else None,
                    )
                )

        tables: list[TableInfo] = []
        for tr in table_rows:
            if not tr:
                continue
            tname = tr[0]
            approx_rows = int(tr[1]) if len(tr) > 1 and tr[1] and tr[1].isdigit() else None
            comment = tr[2] if len(tr) > 2 and tr[2] else None
            tables.append(
                TableInfo(
                    name=tname,
                    columns=col_map.get(tname, []),
                    foreign_keys=fk_map.get(tname, []),
                    row_count=approx_rows,
                    comment=comment,
                )
            )

        return SchemaInfo(tables=tables, db_type="mysql", db_name=db_name)

    async def _introspect_postgres(self, db_name: str) -> SchemaInfo:
        variables = self._config_vars()

        # Tables (now includes approx row counts)
        tables_cmd = self._prepend_pre_commands(
            format_template(self._get_template("introspect_tables"), variables)
        )
        stdout, stderr, exit_code = await self._run_command(tables_cmd)
        self._check_introspection_result("postgres:tables", stdout, stderr, exit_code)
        table_info_raw: list[tuple[str, int | None]] = []
        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            tname = parts[0]
            row_count = None
            if len(parts) > 1 and parts[1]:
                try:
                    row_count = max(0, int(parts[1]))
                except ValueError:
                    pass
            table_info_raw.append((tname, row_count))

        # Columns
        cols_cmd = self._prepend_pre_commands(
            format_template(self._get_template("introspect_columns"), variables)
        )
        stdout, stderr, exit_code = await self._run_command(cols_cmd)
        self._check_introspection_result("postgres:columns", stdout, stderr, exit_code)
        col_map: dict[str, list[ColumnInfo]] = {}
        for line in stdout.strip().splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 4:
                tname = parts[0]
                col_map.setdefault(tname, []).append(
                    ColumnInfo(
                        name=parts[1],
                        data_type=parts[2],
                        is_nullable=parts[3] == "YES",
                        default=parts[4] if len(parts) > 4 else None,
                    )
                )

        # Foreign keys
        fk_map: dict[str, list[ForeignKeyInfo]] = {}
        try:
            fks_cmd = self._prepend_pre_commands(
                format_template(self._get_template("introspect_fks"), variables)
            )
            stdout, stderr, exit_code = await self._run_command(fks_cmd)
            self._check_introspection_result("postgres:fks", stdout, stderr, exit_code)
            for line in stdout.strip().splitlines():
                parts = line.strip().split("\t")
                if len(parts) >= 4:
                    fk_map.setdefault(parts[0], []).append(
                        ForeignKeyInfo(
                            column=parts[1],
                            references_table=parts[2],
                            references_column=parts[3],
                        )
                    )
        except Exception:
            logger.debug("Postgres exec FK introspection failed", exc_info=True)

        # Indexes
        idx_map: dict[str, list[IndexInfo]] = {}
        try:
            idx_cmd = self._prepend_pre_commands(
                format_template(self._get_template("introspect_indexes"), variables)
            )
            stdout, stderr, exit_code = await self._run_command(idx_cmd)
            self._check_introspection_result("postgres:indexes", stdout, stderr, exit_code)
            for line in stdout.strip().splitlines():
                parts = line.strip().split("\t")
                if len(parts) >= 4:
                    idx_map.setdefault(parts[0], []).append(
                        IndexInfo(
                            name=parts[1],
                            is_unique=parts[2].lower() in ("t", "true"),
                            columns=parts[3].split(","),
                        )
                    )
        except Exception:
            logger.debug("Postgres exec index introspection failed", exc_info=True)

        tables = [
            TableInfo(
                name=t,
                columns=col_map.get(t, []),
                foreign_keys=fk_map.get(t, []),
                indexes=idx_map.get(t, []),
                row_count=rc,
            )
            for t, rc in table_info_raw
        ]
        return SchemaInfo(tables=tables, db_type="postgres", db_name=db_name)

    async def _introspect_clickhouse(self, db_name: str) -> SchemaInfo:
        variables = self._config_vars()

        tables_cmd = self._prepend_pre_commands(
            format_template(self._get_template("introspect_tables"), variables)
        )
        stdout, stderr, exit_code = await self._run_command(tables_cmd)
        self._check_introspection_result("clickhouse:tables", stdout, stderr, exit_code)
        _, table_rows = CLIOutputParser.parse_tsv_with_headers(stdout)
        table_names = [r[0] for r in table_rows if r]

        cols_cmd = self._prepend_pre_commands(
            format_template(self._get_template("introspect_columns"), variables)
        )
        stdout, stderr, exit_code = await self._run_command(cols_cmd)
        self._check_introspection_result("clickhouse:columns", stdout, stderr, exit_code)
        _, col_rows = CLIOutputParser.parse_tsv_with_headers(stdout)

        col_map: dict[str, list[ColumnInfo]] = {}
        for c in col_rows:
            if len(c) >= 3:
                tname = c[0]
                col_map.setdefault(tname, []).append(ColumnInfo(name=c[1], data_type=c[2]))

        tables = [TableInfo(name=t, columns=col_map.get(t, [])) for t in table_names]
        return SchemaInfo(tables=tables, db_type="clickhouse", db_name=db_name)

    async def _introspect_via_query(self, db_name: str, db_type: str) -> SchemaInfo:
        """Fallback: try SHOW TABLES-style introspection via execute_query."""
        result = await self.execute_query("SHOW TABLES")
        if result.error or not result.rows:
            return SchemaInfo(db_type=db_type, db_name=db_name)

        tables: list[TableInfo] = []
        for row in result.rows:
            if row:
                tables.append(TableInfo(name=row[0]))
        return SchemaInfo(tables=tables, db_type=db_type, db_name=db_name)

    async def test_connection(self) -> bool:
        try:
            command = self._build_command("test")
            _, stderr, exit_code = await self._run_command(command, timeout=15)
            if exit_code != 0:
                logger.warning(
                    "SSH exec test_connection failed (exit=%d): %s",
                    exit_code,
                    stderr.strip()[:200],
                )
            return exit_code == 0
        except Exception as exc:
            logger.warning("SSH exec test_connection error: %s", exc)
            return False

    async def test_ssh_only(self) -> dict[str, Any]:
        """Test SSH connectivity without testing the database."""
        if not self._conn:
            return {"success": False, "error": "Not connected"}
        _marker = "__SSH_EXEC_TEST__"
        try:
            stdout, _, _ = await self._run_command(
                f"echo {_marker} && hostname",
                timeout=10,
            )
            ok = _marker in stdout
            hostname = "unknown"
            if ok:
                for line in stdout.strip().splitlines():
                    stripped = line.strip()
                    if stripped and stripped != _marker:
                        hostname = stripped
            return {"success": ok, "hostname": hostname}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _quote_identifier(self, name: str) -> str:
        """Quote a SQL identifier based on the DB type."""
        if self.db_type == "mysql":
            return f"`{name.replace('`', '``')}`"
        return f'"{name.replace(chr(34), chr(34) + chr(34))}"'

    async def sample_data(self, table_name: str, limit: int = 3) -> QueryResult:
        quoted = self._quote_identifier(table_name)
        return await self.execute_query(f"SELECT * FROM {quoted} LIMIT {limit}")
