"""Default business metrics rule template.

Auto-created for every new project so the AI agent understands
how to calculate common business metrics from the user's database.

The :func:`generate_default_rule_content` helper (T10) opportunistically
produces a schema-aware version of the rule when an LLM router and a
connection id are available. The hard-coded :data:`_TEMPLATE` below is
the offline / cold-start fallback — it must always render.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.router import LLMRouter

DEFAULT_RULE_NAME = "Business Metrics & Guidelines"

logger = logging.getLogger(__name__)


_SCHEMA_AWARE_PROMPT = """You are a senior data analyst writing a
living "Business Metrics & Query Guidelines" document that an AI agent
will reference while answering questions about this database.

Inputs:
  - ``tables``: each with ``table``, ``relevance``, ``columns`` sample

Produce markdown (not JSON) using this outline:
  1. Revenue Metrics (GMV, Net Revenue, AOV, ARPU, MRR, LTV) — cite real
     columns/tables where applicable.
  2. Profitability (ROAS, CAC, margin, payback).
  3. Traffic Sources (channel split, top referrers, attribution).
  4. Payment Methods (breakdown, success rate, AOV by method).
  5. User Engagement (DAU/MAU, session metrics).
  6. Conversion Funnel (signup → purchase, cart abandonment).
  7. Churn & Retention (monthly churn, cohort retention).
  8. Date & Time conventions (default UTC; timezone notes).
  9. General Query Guidelines (filters, LIMITs, NULL handling).

Rules:
  - When a metric maps onto real tables, call them by name in code blocks.
  - When a metric can't be implemented from the schema, keep the
    generic formula but add a short "Requires: …" note.
  - Keep it under ~1500 words.
  - Return ONLY the markdown document. No preface.
"""


def get_default_rule_content() -> str:
    """Return the offline default rule markdown."""
    return _TEMPLATE


async def generate_default_rule_content(
    db: AsyncSession,
    connection_id: str | None,
    llm_router: LLMRouter | None,
) -> str:
    """Schema-aware rule generator (T10).

    Returns :data:`_TEMPLATE` when the LLM isn't available, the connection
    has no indexed tables, or the call fails. Callers must never depend on
    this succeeding.
    """
    if llm_router is None or not connection_id:
        return _TEMPLATE

    try:
        from sqlalchemy import select

        from app.llm.base import Message
        from app.models.db_index import DbIndex

        rows = (
            await db.execute(
                select(DbIndex)
                .where(
                    DbIndex.connection_id == connection_id,
                    DbIndex.is_active.is_(True),
                )
                .order_by(DbIndex.relevance_score.desc())
                .limit(25)
            )
        ).scalars().all()

        if not rows:
            return _TEMPLATE

        tables_payload = []
        for r in rows:
            cols: list[str] = []
            if r.column_notes_json:
                try:
                    cols = list(json.loads(r.column_notes_json).keys())[:20]
                except Exception:
                    cols = []
            tables_payload.append(
                {
                    "table": r.table_name,
                    "relevance": r.relevance_score,
                    "columns": cols,
                }
            )

        resp = await llm_router.complete(
            messages=[
                Message(role="system", content=_SCHEMA_AWARE_PROMPT),
                Message(
                    role="user",
                    content=json.dumps({"tables": tables_payload}, default=str),
                ),
            ],
            temperature=0.2,
            max_tokens=4000,
        )

        content = (resp.content or "").strip() if resp else ""
        if len(content) < 400 or "##" not in content:
            logger.debug(
                "Schema-aware rule content too short or malformed; using template"
            )
            return _TEMPLATE
        return content
    except Exception:
        logger.debug("Schema-aware default rule generation failed", exc_info=True)
        return _TEMPLATE


_TEMPLATE = """\
# Business Metrics & Query Guidelines

Use this guide when the user asks about business metrics.
Adapt the formulas below to the actual tables and columns discovered via `get_schema_info`.
If the schema uses different names, map them intelligently
(e.g. `orders` -> `transactions`, `amount` -> `total_price`).

---

## 1. Revenue Metrics

### Gross Merchandise Value (GMV)
Total value of all orders/transactions before deductions.
```
SUM(order_total)  -- or SUM(quantity * unit_price)
```
Filter: only completed/successful orders (exclude cancelled, refunded, pending).

### Net Revenue
Revenue after refunds and discounts.
```
GMV - SUM(refund_amount) - SUM(discount_amount)
```

### Average Order Value (AOV)
```
SUM(order_total) / COUNT(DISTINCT order_id)
```
Filter: same as GMV (completed orders only).

### Average Revenue Per User (ARPU)
```
Net Revenue / COUNT(DISTINCT user_id)
```
Over a specific period (day, week, month).

### Monthly Recurring Revenue (MRR)
For subscription-based models:
```
SUM(subscription_price) for all active subscriptions at month-end
```

### Customer Lifetime Value (LTV / CLV)
```
ARPU × Average Customer Lifespan (in months)
```
Or historically: `SUM(all payments by user) / COUNT(DISTINCT users)`.

---

## 2. Profitability & ROI

### Return on Ad Spend (ROAS)
```
Revenue attributed to ads / Ad spend
```
Attribution typically via UTM parameters or referral source.

### Customer Acquisition Cost (CAC)
```
Total marketing spend / Number of new customers acquired
```
Over a specific period.

### Profit Margin
```
(Revenue - Costs) / Revenue × 100
```

### Payback Period
```
CAC / Monthly ARPU
```
Number of months to recoup acquisition cost.

---

## 3. Traffic Sources

### Traffic by Source / Medium
Group visitors/sessions by their acquisition source.
```
GROUP BY source, medium  -- or utm_source, utm_medium
COUNT(DISTINCT session_id) or COUNT(DISTINCT user_id)
```

### Organic vs Paid Split
```
WHERE source IN ('google', 'bing', 'yandex') AND medium = 'organic'  -- organic
WHERE medium IN ('cpc', 'ppc', 'paid', 'display', 'social_paid')     -- paid
```

### Top Referrers
```
GROUP BY referrer_domain ORDER BY COUNT(*) DESC
```

### Channel Attribution
When UTM tags are available:
```
GROUP BY utm_source, utm_medium, utm_campaign
```
Calculate revenue per channel to find the most profitable sources.

---

## 4. Payment Methods

### Breakdown by Payment Method
```
GROUP BY payment_method  -- e.g. 'card', 'apple_pay', 'google_pay', 'paypal', 'crypto'
COUNT(*) as transaction_count,
SUM(amount) as total_volume
```

### Payment Success / Failure Rate
```
COUNT(CASE WHEN status = 'success' THEN 1 END) / COUNT(*) × 100
```
Group by payment method to find problematic providers.

### Average Transaction Value by Method
```
AVG(amount) GROUP BY payment_method
```

### Refund Rate by Payment Method
```
COUNT(refunds) / COUNT(successful_payments) × 100 GROUP BY payment_method
```

---

## 5. User Engagement

### Daily / Monthly Active Users (DAU / MAU)
```
COUNT(DISTINCT user_id) WHERE activity_date = <date>        -- DAU
COUNT(DISTINCT user_id) WHERE activity_date >= <month_start> -- MAU
```

### DAU/MAU Ratio (Stickiness)
```
AVG(daily_active_users) / monthly_active_users
```
Higher is better; >20% is generally good.

### Session Duration
```
AVG(session_end - session_start)
```
Or `AVG(session_duration_seconds)` if pre-calculated.

### Pages / Actions per Session
```
COUNT(events) / COUNT(DISTINCT session_id)
```

---

## 6. Conversion Funnel

### Registration-to-Purchase Rate
```
COUNT(DISTINCT users who purchased) / COUNT(DISTINCT registered users) × 100
```
Over a cohort or time period.

### Step-by-Step Funnel
Calculate drop-off between stages:
```
Stage 1: Visit           → COUNT(DISTINCT visitors)
Stage 2: Registration    → COUNT(DISTINCT new_users)
Stage 3: First Action    → COUNT(DISTINCT users with first action)
Stage 4: Purchase        → COUNT(DISTINCT purchasers)
```
Drop-off rate = `1 - (next_stage / current_stage)`.

### Cart Abandonment Rate
```
1 - (completed_checkouts / carts_created) × 100
```

---

## 7. Churn & Retention

### Churn Rate (Monthly)
```
Users active last month but NOT active this month / Users active last month × 100
```

### Retention Rate
```
100 - Churn Rate
```
Or cohort-based: for users who joined in month M, what % are still active in month M+1, M+2, etc.

### Day-1 / Day-7 / Day-30 Retention
```
COUNT(users active on day N after signup) / COUNT(users who signed up on day 0) × 100
```

### Reactivation Rate
```
Previously churned users who became active again / Total churned users × 100
```

---

## 8. Date & Time Conventions

- Assume all timestamps are stored in **UTC** unless the schema or user specifies otherwise.
- When the user asks for "today", "this month", "last week" — use the current UTC date.
- For time-zone-sensitive reports, ask the user which timezone to display.
- Use `DATE_TRUNC` (PostgreSQL/ClickHouse) or equivalent for period grouping.
- For MySQL use `DATE()`, `YEAR()`, `MONTH()` functions for date grouping.

---

## 9. General Query Guidelines

- **Default filters**: Exclude soft-deleted records
  (`is_active = true`, `deleted_at IS NULL`, `status != 'deleted'`).
- **Row limits**: Use `LIMIT 100` by default for large result sets
  unless the user asks for all data.
- **NULL handling**: Use `COALESCE(column, 0)` for numeric
  aggregations to avoid NULL results.
- **Percentage formatting**: Return percentages as decimal numbers
  (e.g. 42.5, not 0.425).
- **Currency**: Do not assume currency; if multiple currencies exist,
  group by currency or ask the user.
- **Deduplication**: Use `COUNT(DISTINCT ...)` for user counts
  to avoid double-counting.
- **Period comparison**: When asked "compared to last month",
  calculate both periods and show absolute + percentage change.
"""
