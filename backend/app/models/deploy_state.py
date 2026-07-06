from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DeployState(Base):
    """Generic single-value key/value store for deploy-time reconciliation markers.

    Rows are tiny and few (one per marker kind). Currently only the
    ``embedding_fingerprint`` key is written, by the embedding reconcile flow.
    """

    __tablename__ = "deploy_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
