"""add analytics sources: vendor credentials, import journal, GA4 fact tables

Revision ID: a7b8c9d0e1f2
Revises: eff7aad70326
Create Date: 2026-08-01

(The plan named this revision ``a1b2c3d4e5f6``; that id was already taken by
``a1b2c3d4e5f6_add_tool_calls_json_to_chat_messages`` and alembic refuses to
resolve a head when an id appears twice, so a free id is used instead.)

m0 analytics spine (spec 2026-08-01-m0-ga4-spine-design §1.1-§1.4).

New tables: ``vendor_credentials`` (owner-scoped encrypted vendor secrets),
``analytics_imports`` (the per-period collection journal) and the five
``ga4_*_daily`` fact tables the agent answers from.

``connections`` gains ``vendor_credential_id`` (FK **RESTRICT** — deleting a
credential a connection still uses must fail loudly, never orphan the
connection), ``source_config_json``, ``collection_enabled`` and
``collection_hour``; and ``db_type`` / ``db_port`` / ``db_name`` become
**nullable** because an analytics source has no engine, port or database.

The ``connections`` changes go through ``op.batch_alter_table``: SQLite (the dev
DB) cannot ``ALTER COLUMN``, so alembic recreates the table and copies the rows.
Existing rows are untouched — dropping NOT NULL never rewrites data.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "eff7aad70326"
branch_labels: str | None = None
depends_on: str | None = None

# Shared column factories keep the five fact tables identical where they should be.
_MONEY = sa.Numeric(18, 4)


def _fact_head() -> list[sa.Column]:
    """id + connection FK (CASCADE) + property + date — the head of every fact table."""
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("property_id", sa.String(64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
    ]


def _counts(*names: str) -> list[sa.Column]:
    """BigInteger, NOT NULL, default 0 — never float, never NULL for a count."""
    return [sa.Column(n, sa.BigInteger(), nullable=False, server_default="0") for n in names]


def _fetched_at() -> sa.Column:
    # nullable=False mirrors the ORM: Mapped[dt.datetime] (non-Optional) implies
    # NOT NULL, and a drifting schema breaks autogenerate for the next migration.
    return sa.Column(
        "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    # --- vendor_credentials -------------------------------------------------
    # Created first: connections.vendor_credential_id references it below.
    op.create_table(
        "vendor_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_vendor_credentials_user_id", "vendor_credentials", ["user_id"])
    op.create_index(
        "ix_vendor_credentials_user_provider", "vendor_credentials", ["user_id", "provider"]
    )

    # --- connections --------------------------------------------------------
    with op.batch_alter_table("connections") as batch_op:
        batch_op.add_column(sa.Column("vendor_credential_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("source_config_json", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "collection_enabled",
                sa.Boolean(),
                nullable=False,
                # sa.true() compiles to `true` on PostgreSQL and `1` on SQLite;
                # a literal "1" is rejected by Postgres on a boolean column.
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column("collection_hour", sa.Integer(), nullable=False, server_default="3")
        )
        # Drop NOT NULL — an analytics connection has no host/port/database.
        batch_op.alter_column("db_type", existing_type=sa.String(50), nullable=True)
        batch_op.alter_column("db_port", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("db_name", existing_type=sa.String(255), nullable=True)
        batch_op.create_foreign_key(
            "fk_connections_vendor_credential_id",
            "vendor_credentials",
            ["vendor_credential_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_connections_vendor_credential_id", "connections", ["vendor_credential_id"])

    # --- analytics_imports (the journal) ------------------------------------
    op.create_table(
        "analytics_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connection_id",
            sa.String(36),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report", sa.String(64), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        _fetched_at(),
        # Upsert conflict target: one verdict per (connection, report, period).
        sa.UniqueConstraint("connection_id", "report", "period", name="uq_analytics_imports_key"),
    )
    op.create_index("ix_analytics_imports_connection_id", "analytics_imports", ["connection_id"])

    # --- GA4 fact tables ----------------------------------------------------
    op.create_table(
        "ga4_overview_daily",
        *_fact_head(),
        *_counts("sessions", "active_users", "new_users", "screen_page_views", "event_count"),
        sa.Column("total_revenue", _MONEY, nullable=False, server_default="0"),
        _fetched_at(),
        sa.UniqueConstraint(
            "connection_id", "property_id", "date", name="uq_ga4_overview_daily_key"
        ),
    )
    op.create_index(
        "ix_ga4_overview_daily_conn_date", "ga4_overview_daily", ["connection_id", "date"]
    )

    op.create_table(
        "ga4_geo_daily",
        *_fact_head(),
        sa.Column("country", sa.String(128), nullable=False),
        *_counts("sessions", "active_users"),
        _fetched_at(),
        sa.UniqueConstraint(
            "connection_id", "property_id", "date", "country", name="uq_ga4_geo_daily_key"
        ),
    )
    op.create_index("ix_ga4_geo_daily_conn_date", "ga4_geo_daily", ["connection_id", "date"])

    op.create_table(
        "ga4_platform_daily",
        *_fact_head(),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("device_category", sa.String(64), nullable=False),
        *_counts("sessions", "active_users"),
        _fetched_at(),
        sa.UniqueConstraint(
            "connection_id",
            "property_id",
            "date",
            "platform",
            "device_category",
            name="uq_ga4_platform_daily_key",
        ),
    )
    op.create_index(
        "ix_ga4_platform_daily_conn_date", "ga4_platform_daily", ["connection_id", "date"]
    )

    op.create_table(
        "ga4_trend_daily",
        *_fact_head(),
        sa.Column("channel_group", sa.String(128), nullable=False),
        *_counts("sessions", "active_users", "key_events"),
        _fetched_at(),
        sa.UniqueConstraint(
            "connection_id",
            "property_id",
            "date",
            "channel_group",
            name="uq_ga4_trend_daily_key",
        ),
    )
    op.create_index("ix_ga4_trend_daily_conn_date", "ga4_trend_daily", ["connection_id", "date"])

    op.create_table(
        "ga4_event_daily",
        *_fact_head(),
        sa.Column("event_name", sa.String(255), nullable=False),
        *_counts("event_count", "active_users"),
        _fetched_at(),
        sa.UniqueConstraint(
            "connection_id",
            "property_id",
            "date",
            "event_name",
            name="uq_ga4_event_daily_key",
        ),
    )
    op.create_index("ix_ga4_event_daily_conn_date", "ga4_event_daily", ["connection_id", "date"])


def downgrade() -> None:
    for table in (
        "ga4_event_daily",
        "ga4_trend_daily",
        "ga4_platform_daily",
        "ga4_geo_daily",
        "ga4_overview_daily",
    ):
        op.drop_index(f"ix_{table}_conn_date", table_name=table)
        op.drop_table(table)

    op.drop_index("ix_analytics_imports_connection_id", table_name="analytics_imports")
    op.drop_table("analytics_imports")

    # Restoring NOT NULL would fail on any analytics connection. Those rows are
    # meaningless once the analytics columns are gone, but deleting a user's row
    # during a rollback is worse than parking it: backfill placeholders so the
    # downgrade always completes and a re-upgrade finds the row still there.
    op.execute("UPDATE connections SET db_type = '' WHERE db_type IS NULL")
    op.execute("UPDATE connections SET db_port = 0 WHERE db_port IS NULL")
    op.execute("UPDATE connections SET db_name = '' WHERE db_name IS NULL")

    op.drop_index("ix_connections_vendor_credential_id", table_name="connections")
    with op.batch_alter_table("connections") as batch_op:
        batch_op.drop_constraint("fk_connections_vendor_credential_id", type_="foreignkey")
        batch_op.alter_column("db_name", existing_type=sa.String(255), nullable=False)
        batch_op.alter_column("db_port", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("db_type", existing_type=sa.String(50), nullable=False)
        batch_op.drop_column("collection_hour")
        batch_op.drop_column("collection_enabled")
        batch_op.drop_column("source_config_json")
        batch_op.drop_column("vendor_credential_id")

    op.drop_index("ix_vendor_credentials_user_provider", table_name="vendor_credentials")
    op.drop_index("ix_vendor_credentials_user_id", table_name="vendor_credentials")
    op.drop_table("vendor_credentials")
