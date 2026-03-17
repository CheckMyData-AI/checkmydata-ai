import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import ConnectionConfig
from app.connectors.registry import get_connector
from app.models.connection import Connection
from app.services.encryption import decrypt, encrypt
from app.services.ssh_key_service import SshKeyService

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
    async def create(self, session: AsyncSession, **kwargs) -> Connection:
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
            alive = await connector.test_connection()
            await connector.disconnect()
            return {"success": alive}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def test_ssh(self, session: AsyncSession, connection_id: str) -> dict:
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
            decrypted = await _ssh_key_svc.get_decrypted(session, conn.ssh_key_id)
            if decrypted:
                ssh_key_content, ssh_key_passphrase = decrypted

        connect_kwargs: dict = {
            "host": conn.ssh_host,
            "port": conn.ssh_port,
            "username": conn.ssh_user,
            "known_hosts": None,
            "login_timeout": 15,
        }
        if ssh_key_content:
            key = asyncssh.import_private_key(ssh_key_content, ssh_key_passphrase)
            connect_kwargs["client_keys"] = [key]

        try:
            async with asyncssh.connect(**connect_kwargs) as ssh_conn:
                result = await ssh_conn.run("echo ok && hostname", timeout=10, check=False)
                stdout = (result.stdout or "").strip()
                lines = stdout.splitlines()
                ok = len(lines) >= 1 and lines[0].strip() == "ok"
                hostname = lines[1].strip() if len(lines) > 1 else "unknown"
                return {"success": ok, "hostname": hostname}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def to_config(self, session: AsyncSession, conn: Connection) -> ConnectionConfig:
        db_password = None
        if conn.db_password_encrypted:
            db_password = decrypt(conn.db_password_encrypted)

        connection_string = None
        if conn.connection_string_encrypted:
            connection_string = decrypt(conn.connection_string_encrypted)

        ssh_key_content = None
        ssh_key_passphrase = None
        if conn.ssh_key_id:
            decrypted = await _ssh_key_svc.get_decrypted(session, conn.ssh_key_id)
            if decrypted:
                ssh_key_content, ssh_key_passphrase = decrypted

        pre_commands: list[str] | None = None
        if conn.ssh_pre_commands:
            try:
                pre_commands = json.loads(conn.ssh_pre_commands)
            except (json.JSONDecodeError, TypeError):
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
