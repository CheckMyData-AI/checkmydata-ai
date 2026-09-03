import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.base import ConnectionConfig
from app.connectors.registry import get_connector
from app.connectors.ssh_known_hosts import connect_with_policy
from app.core.redaction import safe_error
from app.core.retry import retry
from app.models.connection import Connection
from app.services.demo_data import repair_demo_db_if_missing
from app.services.encryption import decrypt, encrypt
from app.services.ssh_key_service import SshKeyService

logger = logging.getLogger(__name__)

_ssh_key_svc = SshKeyService()

#: How many owed periods a status response names explicitly. The count is
#: always exact; the sample is capped so a connection that has never collected
#: a 400-day backfill does not return four hundred strings to the UI.
PENDING_SAMPLE_LIMIT = 10

#: Why an analytics connection could not be resolved. Machine-readable because
#: the flat loop renders it as text for a model and the pipeline renders it as
#: an error category for the scheduler; deriving one from the other's prose is
#: how two callers drift apart.
ANALYTICS_UNAVAILABLE_REASONS = ("not_found", "wrong_project", "none_connected")


class AnalyticsConnectionUnavailableError(Exception):
    """No analytics connection this project may read matches the request."""

    def __init__(self, reason: str, *, connection_id: str | None = None) -> None:
        if reason not in ANALYTICS_UNAVAILABLE_REASONS:
            # A typo'd reason must fail here rather than render as a blank
            # message in front of a user.
            raise ValueError(
                f"unknown reason {reason!r}; expected one of {ANALYTICS_UNAVAILABLE_REASONS}"
            )
        self.reason = reason
        self.connection_id = connection_id
        super().__init__(reason)


_UPDATABLE_FIELDS = {
    "name",
    "db_type",
    "ssh_host",
    "ssh_port",
    "ssh_user",
    "ssh_key_id",
    "db_host",
    "db_port",
    "db_name",
    "db_user",
    "is_read_only",
    "send_sample_data_to_llm",
    "ssh_exec_mode",
    "ssh_command_template",
    "ssh_pre_commands",
    "mcp_server_command",
    "mcp_server_args",
    "mcp_server_url",
    "mcp_transport_type",
    "source_type",
    # Analytics sources (spec §1.2). ``source_config`` arrives as a dict and is
    # serialised into ``source_config_json`` before this set is consulted.
    "vendor_credential_id",
    "source_config_json",
    "collection_enabled",
    "collection_hour",
}


#: Human names for the analytics vendors, used in user-facing refusals. Keys are
#: ``Connection.source_type`` values.
_VENDOR_LABELS: dict[str, str] = {
    "ga4": "Google Analytics",
    "appstore": "App Store Connect",
    "googleplay": "Google Play",
}


def is_analytics_source(source_type: str | None) -> bool:
    """True when *source_type* is served by an analytics vendor adapter.

    Imported lazily: :mod:`app.services.analytics_collect_service` pulls in the
    vendor SDKs transitively, and this module is imported by nearly every route.
    """
    if not source_type:
        return False
    from app.services.analytics_collect_service import ANALYTICS_SOURCE_TYPES

    return source_type in ANALYTICS_SOURCE_TYPES


def unavailable_analytics_source_detail(source_type: str | None) -> str | None:
    """Why no connection may be created for *source_type* yet, or ``None``.

    ``ANALYTICS_SOURCE_TYPES`` deliberately names the whole vendor family,
    including the ``appstore``/``googleplay`` slots reserved for modules m1/m2 —
    connection *gating* is vendor-agnostic. Collection is not:
    ``FACT_TABLES_BY_SOURCE`` is what says where a report's rows land, and a
    source missing from it has nowhere to put them.

    Without this check such a connection is accepted, scheduled, and dispatched
    by the hourly cron every single day — journalling a failure every day for a
    module that does not exist. Refusing it at the door is the honest answer,
    and the refusal disappears on its own the moment m1/m2 register their fact
    tables, because that table is the source of truth here rather than a second
    hand-maintained list.
    """
    if not is_analytics_source(source_type):
        return None
    from app.services.analytics_collect_service import FACT_TABLES_BY_SOURCE

    if source_type in FACT_TABLES_BY_SOURCE:
        return None
    label = _VENDOR_LABELS.get(source_type or "", source_type or "")
    available = ", ".join(sorted(FACT_TABLES_BY_SOURCE))
    return (
        "App Store Connect and Google Play sources are not available yet, so a "
        f"{label} connection cannot be created. Analytics source types this "
        f"release can collect: {available}."
    )


def is_queryable_database(config: ConnectionConfig | None) -> bool:
    """True when *config* points at an engine the SQL tools can actually query.

    "Is a connection attached?" and "is there a database to query?" are two
    different questions, and conflating them is a user-visible bug: an analytics
    connection produces a config whose ``db_type`` carries the **vendor** id
    (``"ga4"``) because that is what the analytics adapter dispatches on. A
    caller that derives SQL availability from ``config is not None`` therefore
    advertises ``query_database`` for a GA4 source, and ``get_connector("ga4")``
    raises ``ValueError: Unsupported adapter: ga4`` in the middle of the user's
    chat the moment the model takes the offer.

    MCP sources stay queryable: they are dispatched through the connector
    registry like any engine.
    """
    if config is None:
        return False
    if is_analytics_source(config.db_type):
        return False
    return bool(config.db_type)


class ConnectionService:
    @staticmethod
    def _sanitize_strings(kwargs: dict) -> dict:
        """Strip whitespace/tabs from string fields that go into SSH."""
        for field in ("ssh_host", "ssh_user", "db_host", "db_user", "db_name", "name"):
            if field in kwargs and isinstance(kwargs[field], str):
                kwargs[field] = kwargs[field].strip()
        return kwargs

    @staticmethod
    def _encode_source_config(kwargs: dict) -> dict:
        """Serialise an inbound ``source_config`` dict into ``source_config_json``.

        The API speaks dicts; the column stores text. Popping the key
        unconditionally (when present) keeps ``Connection(**kwargs)`` from
        choking on a field that is not a column.
        """
        if "source_config" not in kwargs:
            return kwargs
        raw = kwargs.pop("source_config")
        kwargs["source_config_json"] = json.dumps(raw) if raw else None
        return kwargs

    async def create(self, session: AsyncSession, **kwargs) -> Connection:
        kwargs = self._sanitize_strings(kwargs)
        kwargs = self._encode_source_config(kwargs)
        if "db_password" in kwargs and kwargs["db_password"]:
            kwargs["db_password_encrypted"] = encrypt(kwargs.pop("db_password"))
        if "connection_string" in kwargs and kwargs["connection_string"]:
            kwargs["connection_string_encrypted"] = encrypt(kwargs.pop("connection_string"))
        kwargs.pop("db_password", None)
        kwargs.pop("connection_string", None)

        if "ssh_pre_commands" in kwargs and isinstance(kwargs["ssh_pre_commands"], list):
            kwargs["ssh_pre_commands"] = json.dumps(kwargs["ssh_pre_commands"])

        if "mcp_env" in kwargs and kwargs["mcp_env"]:
            kwargs["mcp_env_encrypted"] = encrypt(json.dumps(kwargs.pop("mcp_env")))
        kwargs.pop("mcp_env", None)

        if "mcp_server_args" in kwargs and isinstance(kwargs["mcp_server_args"], list):
            kwargs["mcp_server_args"] = json.dumps(kwargs["mcp_server_args"])

        connection = Connection(**kwargs)
        session.add(connection)
        await session.commit()
        await session.refresh(connection)
        return connection

    async def update(
        self,
        session: AsyncSession,
        connection_id: str,
        **kwargs,
    ) -> Connection | None:
        conn = await self.get(session, connection_id)
        if not conn:
            return None

        # R1-3: snapshot the pre-update config so we can tear down the tunnel
        # and evict the pooled connector that were built for the *old*
        # endpoint/credentials. Without this, editing host/port/SSH/creds
        # leaves a live tunnel to the old target and a cached connector that
        # keeps serving stale (or wrong-credential) data until process restart.
        old_config: ConnectionConfig | None = None
        try:
            old_config = await self.to_config(session, conn)
        except Exception:
            logger.debug("update(): could not snapshot old config", exc_info=True)

        kwargs = self._sanitize_strings(kwargs)
        kwargs = self._encode_source_config(kwargs)
        if "db_password" in kwargs:
            pw = kwargs.pop("db_password")
            conn.db_password_encrypted = encrypt(pw) if pw else None
        if "connection_string" in kwargs:
            cs = kwargs.pop("connection_string")
            conn.connection_string_encrypted = encrypt(cs) if cs else None

        if "ssh_pre_commands" in kwargs and isinstance(kwargs["ssh_pre_commands"], list):
            kwargs["ssh_pre_commands"] = json.dumps(kwargs["ssh_pre_commands"])

        if "mcp_env" in kwargs:
            mcp_env = kwargs.pop("mcp_env")
            conn.mcp_env_encrypted = encrypt(json.dumps(mcp_env)) if mcp_env else None

        if "mcp_server_args" in kwargs and isinstance(kwargs["mcp_server_args"], list):
            kwargs["mcp_server_args"] = json.dumps(kwargs["mcp_server_args"])

        for key, value in kwargs.items():
            if key in _UPDATABLE_FIELDS:
                setattr(conn, key, value)

        conn.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(conn)

        # R1-3: evict stale runtime state built for the previous config.
        try:
            new_config = await self.to_config(session, conn)
            await self._evict_runtime_caches(old_config, new_config)
        except Exception:
            logger.debug("update(): runtime cache eviction failed", exc_info=True)

        return conn

    async def get(self, session: AsyncSession, connection_id: str) -> Connection | None:
        """Resolve by id ALONE — carries no tenant scope.

        Correct only where the caller has already established that this connection belongs
        to something the user may reach. Where the project is known, use
        :meth:`get_in_project`: three chat entry points called this one after checking
        membership on a *caller-supplied* project id, so naming your own project and
        someone else's connection resolved that connection and decrypted its credentials.
        """
        result = await session.execute(select(Connection).where(Connection.id == connection_id))
        return result.scalar_one_or_none()

    async def get_in_project(
        self, session: AsyncSession, connection_id: str, project_id: str
    ) -> Connection | None:
        """Resolve a connection only if it belongs to *project_id*.

        The scope is in the query rather than in an `if` at the call site, because the `if`
        is what went missing: it is written out verbatim in six sibling route modules
        (`batch.py:71`, `notes.py:117`, `notes.py:243`, `schedules.py:118`,
        `data_investigations.py:99`, `chat_utility.py:456`) and absent from the three that
        matter most. A getter that cannot be called without a project cannot be forgotten
        at a fourth entry point.
        """
        result = await session.execute(
            select(Connection).where(
                Connection.id == connection_id,
                Connection.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def resolve_analytics_connection(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        connection_id: str | None = None,
    ) -> Connection:
        """Resolve the analytics connection a project may read, or refuse.

        Two callers ask this question and they must not answer it twice: the
        orchestrator's tool dispatcher (flat loop) and the pipeline's analytics
        stage. #267 was one check written per entry point where one entry point
        did not have it, so the decision lives here and the callers only render
        it — the dispatcher as a string an LLM reads, the stage as a typed
        ``error_category`` the scheduler acts on.

        ``connection_id`` comes from an LLM, which means it comes from whatever
        the user typed: "the model asked for it" is not authority to read
        another tenant's collected analytics (R3).

        Raises:
            AnalyticsConnectionUnavailableError: with a machine-readable ``reason``,
                because the two callers render different things and neither may
                re-derive *why* by matching prose.
        """
        from app.analytics.source_types import ANALYTICS_SOURCE_TYPES

        if connection_id:
            conn = await self.get(session, connection_id)
            if conn is None or conn.source_type not in ANALYTICS_SOURCE_TYPES:
                # Right project but wrong kind is also "not found": the project
                # may well own that connection, so calling it wrong_project
                # would be a false statement about ownership.
                raise AnalyticsConnectionUnavailableError("not_found", connection_id=connection_id)
            if conn.project_id != project_id:
                raise AnalyticsConnectionUnavailableError(
                    "wrong_project", connection_id=connection_id
                )
            return conn

        connections = await self.list_by_project(session, project_id)
        for conn in connections:
            if conn.source_type in ANALYTICS_SOURCE_TYPES:
                return conn
        raise AnalyticsConnectionUnavailableError("none_connected")

    async def list_by_project(
        self,
        session: AsyncSession,
        project_id: str,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Connection]:
        result = await session.execute(
            select(Connection)
            .where(Connection.project_id == project_id)
            .order_by(Connection.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, session: AsyncSession, connection_id: str) -> bool:
        conn = await self.get(session, connection_id)
        if not conn:
            return False

        try:
            config = await self.to_config(session, conn)
            # Re-audit fix: reuse the update-path eviction so delete() also
            # evicts the pooled connector + schema cache (not just the tunnel),
            # and the tunnel teardown is ref-counted (siblings sharing the same
            # bastion/DB endpoint keep their live transport).
            await self._evict_runtime_caches(config, None)
        except Exception:
            logger.debug("Failed to clean up runtime caches on delete", exc_info=True)

        await session.delete(conn)
        await session.commit()

        # Wipe the per-connection schema BM25 snapshot so future re-creates
        # don't accidentally serve stale tables. Postgres rows are removed by
        # FK cascade; the BM25 snapshot file is not.
        try:
            from app.services.indexing_artifacts import cleanup_connection_artifacts

            cleanup_connection_artifacts(connection_id)
        except Exception:
            logger.debug(
                "ConnectionService.delete: schema BM25 cleanup failed for %s",
                connection_id,
                exc_info=True,
            )
        return True

    @staticmethod
    async def _close_ssh_tunnels(config: ConnectionConfig) -> None:
        """Close the SSH tunnel for *config* via the shared tunnel manager.

        R1-4: connectors now share a single tunnel manager, so one
        ``close_for_config`` is enough. We still import lazily to avoid a
        circular import at module load.
        """
        try:
            from app.connectors.ssh_tunnel import shared_tunnel_manager

            await shared_tunnel_manager.close_for_config(config)
        except Exception:
            logger.debug("Error closing shared SSH tunnel", exc_info=True)

    @classmethod
    async def _evict_runtime_caches(
        cls,
        old_config: ConnectionConfig | None,
        new_config: ConnectionConfig | None,
    ) -> None:
        """Tear down stale tunnels + pooled connectors after an update (R1-3).

        Closes the tunnel for the old endpoint (and the new one, if it
        differs) and evicts the live connector/schema caches keyed by the
        connector key so the next query rebuilds against current settings.
        """

        def _ident(c: ConnectionConfig | None) -> tuple | None:
            if c is None or not c.ssh_host:
                return None
            return (c.ssh_host, c.ssh_port, c.ssh_user, c.db_host, c.db_port)

        # Re-audit fix: skip tunnel teardown entirely on a metadata-only update
        # (transport identity unchanged) — the live tunnel is still valid and
        # tearing it down would needlessly disrupt this and sibling connections.
        old_ident = _ident(old_config)
        new_ident = _ident(new_config)
        transport_unchanged = old_ident is not None and old_ident == new_ident
        if not transport_unchanged:
            configs = [c for c in (old_config, new_config) if c is not None and c.ssh_host]
            seen: set[tuple] = set()
            for cfg in configs:
                ident = (cfg.ssh_host, cfg.ssh_port, cfg.ssh_user, cfg.db_host, cfg.db_port)
                if ident in seen:
                    continue
                seen.add(ident)
                # Ref-counted: only tears down when no sibling connection still
                # references the shared tunnel.
                await cls._close_ssh_tunnels(cfg)

        # Evict pooled connectors in the long-lived chat agent (best-effort:
        # the agent may not be initialised in every process, e.g. workers).
        try:
            from app.connectors.base import connector_key

            keys = {connector_key(c) for c in (old_config, new_config) if c is not None}
            from app.api.routes import chat as _chat

            sql = getattr(
                getattr(getattr(_chat, "_agent", None), "_orchestrator", None), "_sql", None
            )
            if sql is None:
                return
            pool = getattr(sql, "_connectors", {})
            schema_cache = getattr(sql, "_schema_cache", {})
            for key in keys:
                conn = pool.pop(key, None)
                if conn is not None:
                    try:
                        await conn.disconnect()
                    except Exception:
                        logger.debug("evict: connector disconnect failed", exc_info=True)
                schema_cache.pop(key, None)
        except Exception:
            logger.debug("evict: runtime connector pool eviction skipped", exc_info=True)

    async def test_connection(self, session: AsyncSession, connection_id: str) -> dict:
        conn = await self.get(session, connection_id)
        if not conn:
            return {"success": False, "error": "Connection not found"}

        if is_analytics_source(conn.source_type):
            # An analytics source has no engine to open a socket to; "does this
            # work?" means "can the credential read the property?".
            return await self._test_analytics_connection(session, conn)

        db_type = conn.db_type
        if db_type is None:
            # Since the analytics spine ``db_type`` is nullable. A non-analytics
            # connection without one cannot be routed to a connector, and
            # ``get_connector(None)`` would die with "Unsupported adapter",
            # which tells the user nothing.
            from app.services.batch_service import not_a_database_detail

            return {
                "success": False,
                "error": not_a_database_detail(conn, subject="Testing this connection"),
            }

        config = await self.to_config(session, conn)
        connector = get_connector(db_type, ssh_exec_mode=config.ssh_exec_mode)
        try:

            @retry(
                max_attempts=3,
                backoff_seconds=1.0,
                retryable_exceptions=(TimeoutError, ConnectionError, OSError),
            )
            async def _connect_with_retry():
                await connector.connect(config)

            await _connect_with_retry()
            try:
                alive = await connector.test_connection()
            finally:
                await connector.disconnect()
            if not alive:
                logger.warning(
                    "Connection test query failed for '%s' (id=%s, type=%s)",
                    conn.name,
                    connection_id,
                    conn.db_type,
                )
                return {"success": False, "error": "Database responded but test query failed"}
            logger.info("Connection test OK for '%s' (id=%s)", conn.name, connection_id)
            return {"success": True}
        except Exception as e:
            logger.warning(
                "Connection test error for '%s' (id=%s, type=%s): %s",
                conn.name,
                connection_id,
                conn.db_type,
                e,
            )
            # F-CONN-08: this string reaches the UI and the platform's log
            # retention. `safe_error` scrubs and caps in one place rather than
            # each call site re-deciding what a secret looks like.
            return {"success": False, "error": safe_error(e)}

    async def _test_analytics_connection(self, session: AsyncSession, conn: Connection) -> dict:
        """Probe an analytics source with the vendor adapter (spec §7).

        Returns the same ``{"success": bool, "error": str}`` shape as the
        database path so the UI has one contract. A wrong credential and an
        unshared property both come back as ``success: False`` with the vendor's
        own message — never as a 500, and never as a silent success.
        """
        from app.services.analytics_collect_service import build_adapter

        try:
            adapter = build_adapter(conn.source_type)
        except ValueError as exc:
            # A reserved source type (appstore / googleplay) with no adapter yet.
            return {"success": False, "error": str(exc)}

        try:
            config = await self._analytics_config(session, conn)
            await adapter.connect(config)
            try:
                alive = await adapter.test_connection()
            finally:
                await adapter.disconnect()
        except Exception as exc:
            logger.warning(
                "Analytics connection test error for '%s' (source=%s): %s",
                conn.name,
                conn.source_type,
                exc,
            )
            return {"success": False, "error": str(exc)[:500]}

        if not alive:
            logger.info("Analytics connection test failed for '%s'", conn.name)
            return {
                "success": False,
                "error": (
                    "The vendor rejected this credential or the configured property "
                    "is not shared with it. Grant the service account Viewer access "
                    "on the property and try again."
                ),
            }
        logger.info("Analytics connection test OK for '%s' (id=%s)", conn.name, conn.id[:8])
        return {"success": True}

    async def test_ssh(
        self,
        session: AsyncSession,
        connection_id: str,
        user_id: str | None = None,
    ) -> dict:
        """Test SSH connectivity independently from the database."""
        import asyncssh

        conn = await self.get(session, connection_id)
        if not conn:
            return {"success": False, "error": "Connection not found"}
        if not conn.ssh_host:
            return {"success": False, "error": "No SSH host configured"}

        ssh_key_content = None
        ssh_key_passphrase = None
        if conn.ssh_key_id:
            decrypted = await _ssh_key_svc.get_decrypted(session, conn.ssh_key_id, user_id=user_id)
            if decrypted:
                ssh_key_content, ssh_key_passphrase = decrypted

        connect_kwargs: dict = {
            "host": (conn.ssh_host or "").strip(),
            "port": conn.ssh_port,
            "username": (conn.ssh_user or "").strip(),
            "login_timeout": 30,
            "connect_timeout": 30,
        }
        if ssh_key_content:
            key = asyncssh.import_private_key(ssh_key_content.strip(), ssh_key_passphrase)
            connect_kwargs["client_keys"] = [key]

        _marker = "__SSH_TEST_OK__"
        try:
            # R1-2: host-key verification is governed by ssh_host_key_policy.
            async with await connect_with_policy(connect_kwargs, timeout=40) as ssh_conn:
                result = await ssh_conn.run(
                    f"echo {_marker} && hostname",
                    timeout=10,
                    check=False,
                )
                stdout = str(result.stdout or "").strip()
                ok = _marker in stdout
                hostname = "unknown"
                if ok:
                    for line in stdout.splitlines():
                        stripped = line.strip()
                        if stripped and stripped != _marker:
                            hostname = stripped
                    logger.info("SSH test OK for '%s' -> %s", conn.name, hostname)
                else:
                    logger.warning(
                        "SSH test: marker not found for '%s' (exit=%s, stdout=%r)",
                        conn.name,
                        result.exit_status,
                        stdout[:200],
                    )
                return {
                    "success": ok,
                    "hostname": hostname,
                    **(
                        {}
                        if ok
                        else {
                            "error": "SSH connected but test command returned unexpected output",
                            "stdout": stdout[:200],
                        }
                    ),
                }
        except Exception as e:
            logger.warning("SSH test error for '%s' (host=%s): %s", conn.name, conn.ssh_host, e)
            return {"success": False, "error": safe_error(e)}
        # Defensive: only reachable if the context manager's __aexit__ swallows
        # an exception (so the in-block return never ran). Keep the contract that
        # this coroutine always returns a result dict.
        return {"success": False, "error": "SSH test did not complete"}

    @staticmethod
    async def _analytics_config(session: AsyncSession, conn: Connection) -> ConnectionConfig:
        """The adapter-facing config for an analytics connection.

        Delegates to :meth:`AnalyticsCollectService._build_config` rather than
        rebuilding the same dict: that method *is* the contract the GA4 adapter
        reads (``extra[SOURCE_CONFIG_KEY]`` + ``extra[CREDENTIAL_SECRET_KEY]``,
        empty host/port/name), and two copies of it would drift the first time a
        knob is added. The collect service owns that file; keeping one
        definition is worth reaching across the boundary for.

        The credential is resolved with ``user_id=None`` — a trusted internal
        lookup. Ownership was settled when the credential was attached to the
        connection (see ``connections`` route), and the scheduler that calls the
        same builder has no request principal at all.
        """
        from app.services.analytics_collect_service import AnalyticsCollectService

        return await AnalyticsCollectService()._build_config(session, conn)

    async def to_config(
        self,
        session: AsyncSession,
        conn: Connection,
        user_id: str | None = None,
    ) -> ConnectionConfig:
        if is_analytics_source(conn.source_type):
            # No host, no port, no database, no SSH, no DSN — building any of
            # that here would fabricate a database that does not exist.
            return await self._analytics_config(session, conn)

        db_type = conn.db_type
        if db_type is None:
            # Nullable since the analytics spine. This row is not an analytics
            # source (handled above) and has no engine either, so no connector
            # can be dispatched for it. Unlike host/port/name there is no
            # "absent" value for an engine — inventing one would route the
            # query at whichever adapter happens to be first.
            from app.services.batch_service import not_a_database_detail

            raise ValueError(not_a_database_detail(conn, subject="Building a connection config"))

        try:
            db_password = None
            if conn.db_password_encrypted:
                db_password = decrypt(conn.db_password_encrypted)

            connection_string = None
            if conn.connection_string_encrypted:
                connection_string = decrypt(conn.connection_string_encrypted)
        except Exception as exc:
            logger.error("Failed to decrypt connection '%s' credentials: %s", conn.name, exc)
            raise ValueError(
                f"Cannot decrypt credentials for connection '{conn.name}'. "
                "The encryption key may have changed."
            ) from exc

        ssh_key_content = None
        ssh_key_passphrase = None
        if conn.ssh_key_id:
            decrypted = await _ssh_key_svc.get_decrypted(session, conn.ssh_key_id, user_id=user_id)
            if decrypted:
                ssh_key_content, ssh_key_passphrase = decrypted

        pre_commands: list[str] | None = None
        if conn.ssh_pre_commands:
            try:
                pre_commands = json.loads(conn.ssh_pre_commands)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Invalid JSON in ssh_pre_commands for connection '%s': %s",
                    conn.name,
                    (conn.ssh_pre_commands or "")[:100],
                )
                pre_commands = None

        # Documented footgun: a raw connection_string (DSN) takes precedence over
        # the discrete db_host/db_port, so an SSH tunnel — which rewrites those to
        # 127.0.0.1:<local_port> — is bypassed entirely. Warn loudly rather than
        # silently connecting straight to the DB host.
        if connection_string and conn.ssh_host:
            logger.warning(
                "Connection '%s' sets both a connection_string and ssh_host: the "
                "DSN bypasses the SSH tunnel (it connects directly to the DSN "
                "host). Drop the connection_string to route through the tunnel.",
                conn.name,
            )

        extra: dict = {}
        if conn.source_type == "mcp":
            extra["mcp_transport_type"] = conn.mcp_transport_type or "stdio"
            extra["mcp_server_command"] = conn.mcp_server_command or ""
            try:
                extra["mcp_server_args"] = (
                    json.loads(conn.mcp_server_args) if conn.mcp_server_args else []
                )
            except (json.JSONDecodeError, TypeError):
                extra["mcp_server_args"] = []
            extra["mcp_server_url"] = conn.mcp_server_url or ""
            if conn.mcp_env_encrypted:
                try:
                    extra["mcp_env"] = json.loads(decrypt(conn.mcp_env_encrypted))
                except Exception:
                    logger.warning("Failed to decrypt MCP env for connection '%s'", conn.name)
                    extra["mcp_env"] = {}

        # ``db_port``/``db_name`` are nullable since the analytics spine, but a
        # DSN-only or MCP connection legitimately has neither, and
        # ``ConnectionConfig`` already carries an "absent" value for both: port
        # ``0`` (never a real port — the analytics builder uses the same marker)
        # and the empty database name MCP rows have always used. Mapping NULL
        # onto those markers keeps "unset" visible; defaulting to 5432 would
        # invent a Postgres endpoint that was never configured.
        db_port = 0 if conn.db_port is None else conn.db_port
        db_name = "" if conn.db_name is None else conn.db_name

        # The demo's sample database is disposable by design and its filesystem is
        # ephemeral: a Heroku restart takes the file while the Connection row survives,
        # and a second web dyno never had it. Every query, index and health check builds
        # its config here, so this is the one seam where a missing demo file can be
        # rebuilt before anything tries to open it. Scoped by directory containment
        # (`is_demo_db`) — a user's own SQLite file is never written to.
        repair_demo_db_if_missing(db_name)

        return ConnectionConfig(
            # R1-7: carry the connection id so ``connector_key`` (R1-1) can use
            # it as the credential discriminator — without it the key falls back
            # to endpoint-only and two connections to the same host/db could
            # share a pooled connector under the wrong credentials.
            connection_id=conn.id,
            db_type=db_type,
            db_host=conn.db_host,
            db_port=db_port,
            db_name=db_name,
            db_user=conn.db_user,
            db_password=db_password,
            connection_string=connection_string,
            ssh_host=conn.ssh_host,
            ssh_port=conn.ssh_port,
            ssh_user=conn.ssh_user,
            ssh_key_content=ssh_key_content,
            ssh_key_passphrase=ssh_key_passphrase,
            ssh_exec_mode=conn.ssh_exec_mode,
            ssh_command_template=conn.ssh_command_template,
            ssh_pre_commands=pre_commands,
            is_read_only=conn.is_read_only,
            send_sample_data_to_llm=getattr(conn, "send_sample_data_to_llm", True),
            extra=extra,
        )

    # ------------------------------------------------------------------
    # Analytics collection status (spec §5)
    # ------------------------------------------------------------------

    async def collection_status(self, session: AsyncSession, conn: Connection) -> dict:
        """Summarise one analytics connection's collection state, per report.

        Reads the import journal — the only thing that can tell "collected as
        zero" from "never collected" — and joins it against the periods the
        current backfill window expects.

        Two distinctions are the whole point of this payload and neither may be
        collapsed:

        * **``last_error`` vs ``caveat``.** The journal records a ``degraded``
          sentence in ``error`` on an otherwise ``ok`` row (a truncated vendor
          page, say). That is a caveat on real data, not a failure; rendering it
          as an error would make a successful collection look broken. Only rows
          whose *status* is ``failed`` populate ``last_error``.
        * **pending vs empty.** ``pending_periods`` counts periods the window
          expects that the journal has not completed. A period recorded
          ``empty`` is complete — the vendor genuinely had no data — so it is
          not pending, while a ``failed`` period stays owed forever (the hole
          below the watermark refills, see :mod:`app.analytics.journal`).

        Note the tail-refetch union that :func:`journal.pending_periods` applies
        is deliberately *not* used here: the last couple of periods are always
        refetched because vendors revise data, which would make a fully
        collected connection permanently report work outstanding.
        """
        from app.analytics.base import Grain
        from app.models.analytics_import import AnalyticsImport
        from app.services.analytics_collect_service import (
            AnalyticsCollectService,
            build_adapter,
            period_range,
        )

        rows = (
            await session.execute(
                select(
                    AnalyticsImport.report,
                    AnalyticsImport.period,
                    AnalyticsImport.status,
                    AnalyticsImport.rows_written,
                    AnalyticsImport.error,
                    AnalyticsImport.fetched_at,
                ).where(AnalyticsImport.connection_id == conn.id)
            )
        ).all()

        # The collect service owns the window definition (backfill knob + the
        # "ends yesterday" rule in the scheduler's timezone). Reading it from
        # there rather than recomputing keeps "pending" meaning exactly what the
        # collector will fetch next.
        collector = AnalyticsCollectService()
        backfill_days = collector._backfill_days(conn)
        today = collector._today()

        grains: dict[str, Grain] = {}
        try:
            for spec in build_adapter(conn.source_type).available_reports():
                grains[spec.name] = spec.grain
        except Exception:
            # A reserved source type with no adapter yet, or a missing vendor
            # SDK. The journal still has something to say, so degrade to it
            # rather than failing a read-only status call.
            logger.debug(
                "collection_status: no adapter for source_type %r", conn.source_type, exc_info=True
            )

        # Imported lazily: analytics_collect_service imports this module, so a
        # module-level import here would close the cycle.
        from app.services.analytics_collect_service import CONNECT_SENTINEL_REPORT

        # The ``_connect`` sentinel records a connection-level failure (bad
        # credential, adapter unbuildable) and is not a vendor report. It drives
        # the top-level status/last_error below, but listing it as a report would
        # put a row literally named "_connect" in the UI's per-report table.
        report_names = sorted(
            (set(grains) | {row.report for row in rows}) - {CONNECT_SENTINEL_REPORT}
        )
        reports = [
            _report_status(
                report=name,
                grain=grains.get(name),
                entries=[row for row in rows if row.report == name],
                expected=(
                    period_range(grains[name], backfill_days=backfill_days, today=today)
                    if name in grains
                    else []
                ),
            )
            for name in report_names
        ]

        total_ok = sum(r["ok_periods"] for r in reports)
        total_failed = sum(r["failed_periods"] for r in reports)
        total_pending = sum(r["pending_periods"] for r in reports)

        # Mirrors CollectOutcome.status (spec §2.4) and keeps its rule: zero rows
        # is only a failure when something actually failed. A window that came
        # back genuinely ``empty`` everywhere collected fine — the vendor just
        # had no data — and calling that "failed" would send users hunting for a
        # broken credential.
        # A ``_connect`` row means the connection itself could not be opened, so
        # no report could have run. It is excluded from ``reports`` above (it is
        # not a vendor report), which also keeps it out of ``total_failed`` — so
        # check it directly. Without this a broken credential reads as "partial",
        # implying some data landed when none could.
        connect_failed = any(
            row.report == CONNECT_SENTINEL_REPORT and row.status == "failed" for row in rows
        )

        if not rows:
            status = "never_collected"
        elif connect_failed or (total_ok == 0 and total_failed):
            status = "failed"
        elif total_failed or total_pending:
            status = "partial"
        else:
            status = "ok"

        newest_failure = _newest(rows, lambda row: row.status == "failed" and bool(row.error))
        newest_caveat = _newest(rows, lambda row: row.status != "failed" and bool(row.error))
        newest_row = _newest(rows, lambda _row: True)

        return {
            "connection_id": conn.id,
            "source_type": conn.source_type,
            "collection_enabled": conn.collection_enabled,
            "collection_hour": conn.collection_hour,
            "next_scheduled_hour": conn.collection_hour if conn.collection_enabled else None,
            "timezone": settings.daily_knowledge_sync_timezone,
            "backfill_days": backfill_days,
            "status": status,
            "last_run_at": _iso(newest_row.fetched_at) if newest_row else None,
            "last_error": newest_failure.error if newest_failure else None,
            "caveat": newest_caveat.error if newest_caveat else None,
            "pending_periods": total_pending,
            "reports": reports,
        }


def _recency_key(row: Any) -> tuple:
    """Sort key ordering journal rows oldest → newest, NULL timestamps first.

    The leading flag keeps a NULL ``fetched_at`` from ever being compared
    against a datetime (which raises), and ``period`` breaks ties inside one
    batch written in the same microsecond.
    """
    return (row.fetched_at is not None, row.fetched_at, row.period)


def _newest(rows: Sequence[Any], predicate: Callable[[Any], bool]) -> Any | None:
    """The most recently fetched row satisfying *predicate*, or None."""
    matching = [row for row in rows if predicate(row)]
    return max(matching, key=_recency_key) if matching else None


def _report_status(
    *,
    report: str,
    grain: str | None,
    entries: Sequence[Any],
    expected: list[str],
) -> dict:
    """One report's entry in the collection-status payload."""
    ok_periods = [e.period for e in entries if e.status == "ok"]
    empty_periods = [e.period for e in entries if e.status == "empty"]
    failed_periods = [e.period for e in entries if e.status == "failed"]
    done = set(ok_periods) | set(empty_periods)
    pending = sorted(set(expected) - done)

    last_failure = _newest(entries, lambda e: e.status == "failed" and bool(e.error))
    # A caveat rides in ``error`` on a row whose status is *not* failed.
    last_caveat = _newest(entries, lambda e: e.status != "failed" and bool(e.error))
    last_run = _newest(entries, lambda _e: True)

    return {
        "report": report,
        "grain": grain,
        "latest_ok_period": max(ok_periods) if ok_periods else None,
        "latest_collected_period": max(done) if done else None,
        "ok_periods": len(ok_periods),
        "empty_periods": len(empty_periods),
        "failed_periods": len(failed_periods),
        "rows_written": sum(int(e.rows_written or 0) for e in entries),
        "pending_periods": len(pending),
        "pending_sample": pending[:PENDING_SAMPLE_LIMIT],
        "last_run_at": _iso(last_run.fetched_at) if last_run else None,
        "last_error": last_failure.error if last_failure else None,
        "caveat": last_caveat.error if last_caveat else None,
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
