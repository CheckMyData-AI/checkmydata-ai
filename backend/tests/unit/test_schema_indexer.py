from app.connectors.base import ColumnInfo, ForeignKeyInfo, IndexInfo, SchemaInfo, TableInfo
from app.knowledge.schema_indexer import SchemaIndexer


class TestSchemaIndexer:
    def setup_method(self):
        self.indexer = SchemaIndexer()

    def test_schema_to_markdown(self):
        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="users",
                    schema="public",
                    columns=[
                        ColumnInfo(name="id", data_type="integer", is_primary_key=True, is_nullable=False),
                        ColumnInfo(name="name", data_type="varchar", is_nullable=False),
                        ColumnInfo(name="email", data_type="varchar", is_nullable=True, comment="User email"),
                    ],
                    row_count=1000,
                    foreign_keys=[],
                    indexes=[IndexInfo(name="idx_email", columns=["email"], is_unique=True)],
                )
            ],
            db_type="postgres",
            db_name="mydb",
        )

        md = self.indexer.schema_to_markdown(schema)
        assert "# Database Schema: mydb (postgres)" in md
        assert "users" in md
        assert "| id |" in md
        assert "YES" in md
        assert "User email" in md
        assert "idx_email" in md

    def test_schema_to_prompt_context(self):
        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="orders",
                    schema="public",
                    columns=[
                        ColumnInfo(name="id", data_type="int", is_primary_key=True),
                        ColumnInfo(name="user_id", data_type="int"),
                        ColumnInfo(name="total", data_type="decimal"),
                    ],
                    foreign_keys=[
                        ForeignKeyInfo(column="user_id", references_table="users", references_column="id"),
                    ],
                    indexes=[IndexInfo(name="idx_user", columns=["user_id"], is_unique=False)],
                    row_count=500,
                )
            ],
            db_type="mysql",
            db_name="shop",
        )

        ctx = self.indexer.schema_to_prompt_context(schema)
        assert "shop" in ctx
        assert "orders" in ctx
        assert "PK" in ctx
        assert "user_id -> users.id" in ctx
        assert "idx_user" in ctx
        assert "500" in ctx

    def test_prompt_context_all_relationships(self):
        schema = SchemaInfo(
            tables=[
                TableInfo(
                    name="orders",
                    columns=[ColumnInfo(name="user_id", data_type="int")],
                    foreign_keys=[ForeignKeyInfo(column="user_id", references_table="users", references_column="id")],
                ),
                TableInfo(
                    name="items",
                    columns=[ColumnInfo(name="order_id", data_type="int")],
                    foreign_keys=[ForeignKeyInfo(column="order_id", references_table="orders", references_column="id")],
                ),
            ],
            db_type="postgres",
            db_name="shop",
        )
        ctx = self.indexer.schema_to_prompt_context(schema)
        assert "## All Relationships" in ctx
        assert "orders.user_id -> users.id" in ctx
        assert "items.order_id -> orders.id" in ctx

    def test_empty_schema(self):
        schema = SchemaInfo(db_type="postgres", db_name="empty")
        md = self.indexer.schema_to_markdown(schema)
        assert "empty" in md
