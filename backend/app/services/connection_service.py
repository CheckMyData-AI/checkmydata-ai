import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import ConnectionConfig
from app.connectors.registry import get_connector
from app.models.connection import Connection
from app.services.encryption import decrypt, encrypt
from app.services.ssh_key_service import SshKeyService

logger = logging.getLogger(__name__)

_ssh_key_svc = SshKeyService()

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
    "ssh_exec_mode",
    "ssh_command_template",
    "ssh_pre_commands",
}


class ConnectionService:
    @staticmethod
    def _sanitize_strings(kwargs: dict) -> dict:
        """Strip whitespace/tabs from string fields that go into SSH."""
        for field in ("ssh_host", "ssh_user", "db_host", "db_user", "db_name", "name"):
            if field in kwargs and isinstance(kwargs[field], str):
                kwargs[field] = kwargs[field].strip()
        return kwargs

    async def create(self, session: AsyncSession, **kwargs) -> Connection:
        kwargs = self._sanitize_strings(kwargs)
        if "db_password" in kwargs and kwargs["db_password"]:
            kwargs["db_password_encrypted"] = encrypt(kwargs.pop("db_password"))
        if "connection_string" in kwargs and kwargs["connection_string"]:
            kwargs["connection_string_encrypted"] = encrypt(kwargs.pop("connection_string"))
        kwargs.pop("db_password", None)
        kwargs.pop("connection_string", None)

        if "ssh_pre_commands" in kwargs and isinstance(kwargs["ssh_pre_commands"], list):
            kwargs["ssh_pre_commands"] = json.dumps(kwargs["ssh_pre_commands"])

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

        kwargs = self._sanitize_strings(kwargs)
        if "db_password" in kwargs:
            pw = kwargs.pop("db_password")
            conn.db_password_encrypted = encrypt(pw) if pw else None
        if "connection_string" in kwargs:
            cs = kwargs.pop("connection_string")
            conn.connection_string_encrypted = encrypt(cs) if cs else None

        if "ssh_pre_commands" in kwargs and isinstance(kwargs["ssh_pre_commands"], list):
            kwargs["ssh_pre_commands"] = json.dumps(kwargs["ssh_pre_commands"])

        for key, value in kwargs.items():
            if key in _UPDATABLE_FIELDS:
                setattr(conn, key, value)

        conn.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(conn)
        return conn

    async def get(self, session: AsyncSession, connection_id: str) -> Connection | None:
        result = await session.execute(select(Connection).where(Connection.id == connection_id))
        return result.scalar_one_or_none()

    async def list_by_project(self, session: AsyncSession, project_id: str) -> list[Connection]:
        result = await session.execute(
            select(Connection)
            .where(Connection.project_id == project_id)
            .order_by(Connection.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete(self, session: AsyncSession, connection_id: str) -> bool:
        conn = await self.get(session, connection_id)
        if not conn:
            return False
        await session.delete(conn)
        await session.commit()
        return True

    async def test_connection(self, session: AsyncSession, connection_id: str) -> dict:
        conn = await self.get(session, connection_id)
        if not conn:
            return {"success": False, "error": "Connection not found"}

        config = await self.to_config(session, conn)
        connector = get_connector(conn.db_type, ssh_exec_mode=config.ssh_exec_mode)
        try:
            await connector.connect(config)
            try:
                alive = await connector.test_connection()
            finally:
                await connector.disconnect()
            if not alive:
                logger.warning(
                    "Connection test query failed for '%s' (id=%s, type=%s)",
                    conn.name, connection_id, conn.db_type,
                )
                return {"success": False, "error": "Database responded but test query failed"}
            logger.info("Connection test OK for '%s' (id=%s)", conn.name, connection_id)
            return {"success": True}
        except Exception as e:
            logger.warning(
                "Connection test error for '%s' (id=%s, type=%s): %s",
                conn.name, connection_id, conn.db_type, e,
            )
            return {"success": False, "error": str(e)}

    async def test_ssh(
        self, session: AsyncSession, connection_id: str, user_id: str | None = None,
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
            "known_hosts": None,
            "login_timeout": 15,
        }
        if ssh_key_content:
            key = asyncssh.import_private_key(ssh_key_content.strip(), ssh_key_passphrase)
            connect_kwargs["client_keys"] = [key]

        _marker = "__SSH_TEST_OK__"
        try:
            async with asyncssh.connect(**connect_kwargs) as ssh_conn:
                result = await ssh_conn.run(
                    f"echo {_marker} && hostname", timeout=10, check=False,
                )
                stdout = (result.stdout or "").strip()
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
                        "SSH test: marker not found for '%s' "
                        "(exit=%s, stdout=%r)",
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
                        else {"error": "SSH connected but test command returned unexpected output",
                              "stdout": stdout[:200]}
                    ),
                }
        except Exception as e:
            logger.warning("SSH test error for '%s' (host=%s): %s", conn.name, conn.ssh_host, e)
            return {"success": False, "error": str(e)}

    async def to_config(
        self, session: AsyncSession, conn: Connection, user_id: str | None = None,
    ) -> ConnectionConfig:
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
                    conn.name, conn.ssh_pre_commands[:100],
                )
                pre_commands = None

        return ConnectionConfig(
            db_type=conn.db_type,
            db_host=conn.db_host,
            db_port=conn.db_port,
            db_name=conn.db_name,
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
        )
