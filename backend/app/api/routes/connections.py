from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService

router = APIRouter()
_svc = ConnectionService()
_membership_svc = MembershipService()


class ConnectionCreate(BaseModel):
    project_id: str
    name: str
    db_type: Literal["postgres", "mysql", "mongodb", "clickhouse"]
    ssh_host: str | None = None
    ssh_port: int = 22
    ssh_user: str | None = None
    ssh_key_id: str | None = None
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = ""
    db_user: str | None = None
    db_password: str | None = None
    connection_string: str | None = None
    is_read_only: bool = True
    ssh_exec_mode: bool = False
    ssh_command_template: str | None = None
    ssh_pre_commands: list[str] | None = None

    @field_validator("name", "connection_string", mode="before")
    @classmethod
    def strip_strings(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def require_conn_string_or_host(self):
        if not self.connection_string and not (self.db_host and self.db_name):
            raise ValueError("Provide either a connection string or db_host + db_name")
        return self


class ConnectionUpdate(BaseModel):
    name: str | None = None
    db_type: str | None = None
    ssh_host: str | None = None
    ssh_port: int | None = None
    ssh_user: str | None = None
    ssh_key_id: str | None = None
    db_host: str | None = None
    db_port: int | None = None
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    connection_string: str | None = None
    is_read_only: bool | None = None
    ssh_exec_mode: bool | None = None
    ssh_command_template: str | None = None
    ssh_pre_commands: list[str] | None = None


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    db_type: str
    ssh_host: str | None
    ssh_port: int
    ssh_user: str | None
    ssh_key_id: str | None
    db_host: str
    db_port: int
    db_name: str
    db_user: str | None
    is_read_only: bool
    is_active: bool
    ssh_exec_mode: bool
    ssh_command_template: str | None
    ssh_pre_commands: str | None


@router.post("", response_model=ConnectionResponse)
async def create_connection(
    body: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "owner")
    conn = await _svc.create(db, **body.model_dump())
    return conn


@router.get("/project/{project_id}", response_model=list[ConnectionResponse])
async def list_connections(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")
    return await _svc.list_by_project(db, project_id)


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")
    return conn


@router.patch("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: str,
    body: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")
    updates = body.model_dump(exclude_unset=True)

    merged_conn_string = updates.get("connection_string", conn.connection_string if hasattr(conn, "connection_string") else None)
    merged_db_host = updates.get("db_host", conn.db_host)
    merged_db_name = updates.get("db_name", conn.db_name)
    if not merged_conn_string and not (merged_db_host and merged_db_name):
        raise HTTPException(
            status_code=422,
            detail="Provide either a connection string or db_host + db_name",
        )

    conn = await _svc.update(db, connection_id, **updates)
    return conn


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")
    await _svc.delete(db, connection_id)
    return {"ok": True}


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")
    result = await _svc.test_connection(db, connection_id)
    return result


@router.post("/{connection_id}/test-ssh")
async def test_ssh(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Test SSH connectivity independently from the database."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "viewer")
    result = await _svc.test_ssh(db, connection_id)
    return result


@router.post("/{connection_id}/refresh-schema")
async def refresh_schema(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Invalidate the cached schema for this connection and re-introspect."""
    conn = await _svc.get(db, connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await _membership_svc.require_role(db, conn.project_id, user["user_id"], "owner")

    config = await _svc.to_config(db, conn)
    try:
        from app.core.orchestrator import Orchestrator
        orch = Orchestrator()
        schema = await orch.refresh_schema(config)
        return {
            "ok": True,
            "tables": len(schema.tables),
            "db_type": schema.db_type,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schema refresh failed: {e}")
