"""The account's LLM credit: two pockets over one OpenRouter counter.

OpenRouter has a spend CEILING and a running total — `limit`, `usage`, and
`limit_remaining = limit - usage`. That is one counter. The billing model has two pockets
with different lifetimes:

- the **included** allowance, granted monthly with the tier and expiring at renewal;
- **purchased** credit, bought pay-as-you-go and never expiring, because the customer paid
  for it separately.

Spend always depletes the included pocket first. That is not an optimisation — with the
order reversed, a customer who under-used their allowance would lose purchased money every
month, which is the one arithmetic error here that is indistinguishable from theft.

`usage_at_period_start` is the hinge. OpenRouter's `usage` never resets (`limit_reset` is
null by design), so "spent this period" is a subtraction against a stored watermark rather
than a value anyone can read.

The key itself is Fernet-encrypted at rest, exactly as `VendorCredential.secret_encrypted`
and `SshKey` are, and appears in no response model. It is a spending instrument: whoever
holds it can burn the account's balance.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LlmCredit(Base):
    """One row per account. Created on the first paid subscription, never deleted."""

    __tablename__ = "llm_credit"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    #: OpenRouter's own identifier for the key, used for GET / PATCH / DELETE. Not secret.
    key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: The key itself, Fernet-encrypted. Never rendered, never logged.
    key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: `usage` as read from OpenRouter at the start of the current period. Everything spent
    #: since is `usage - usage_at_period_start`; OpenRouter's counter never resets.
    usage_at_period_start: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default="0"
    )
    #: This period's included allowance, in USD. Expires at renewal.
    included_grant_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default="0"
    )
    #: Credit the customer bought. Does not expire; survives every renewal.
    purchased_balance_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default="0"
    )
    #: Money, so `Numeric` rather than float — the same reason revenue is Numeric(18,4) in
    #: the analytics fact tables; `0.1 + 0.2 != 0.3` in binary float and a balance drifts
    #: by cents over a year. Typed `Mapped[Decimal]` to match, because `Mapped[float]` over
    #: a `Numeric` column is a lie the driver corrects at runtime and mypy catches at the
    #: assignment.

    #: How many times the key has been provisioned. A rotation is visible in this number
    #: even after the old hash is gone.
    provision_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
