import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    db_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # SSH tunnel settings
    ssh_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssh_key_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("ssh_keys.id", ondelete="SET NULL"), nullable=True
    )

    # DB connection (encrypted at rest)
    db_host: Mapped[str] = mapped_column(String(255), default="127.0.0.1")
    db_port: Mapped[int] = mapped_column(Integer, nullable=False)
    db_name: Mapped[str] = mapped_column(String(255), nullable=False)
    db_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    db_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Custom connection string override (encrypted)
    connection_string_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # SSH exec mode (run queries via CLI command over SSH instead of port forwarding)
    ssh_exec_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    ssh_command_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_pre_commands: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="connections")  # noqa: F821
