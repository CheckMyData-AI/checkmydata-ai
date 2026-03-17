import logging

from app.connectors.base import BaseConnector, QueryResult, SchemaInfo, TableInfo

logger = logging.getLogger(__name__)


class SchemaIndexer:
    """Introspects a live database to extract schema documentation."""

    async def introspect(self, connector: BaseConnector) -> SchemaInfo:
        logger.debug("Introspecting schema via %s connector", connector.db_type)
        return await connector.introspect_schema()

    async def fetch_sample_data(
        self,
        connector: BaseConnector,
        schema: SchemaInfo,
        limit: int = 3,
    ) -> dict[str, QueryResult]:
        """Fetch sample rows per table (best-effort, swallows errors)."""
        samples: dict[str, QueryResult] = {}
        for table in schema.tables:
            try:
                result = await connector.sample_data(table.name, limit)
                if result.rows:
                    samples[table.name] = result
            except Exception:
                logger.debug("Sample data skipped for %s", table.name)
        return samples

    def append_sample_data_context(
        self,
        context: str,
        samples: dict[str, QueryResult],
    ) -> str:
        if not samples:
            return context
        parts = [context, "", "## Sample Data"]
        for table_name, result in samples.items():
            parts.append(f"\n### {table_name} (first {len(result.rows)} rows)")
            parts.append("| " + " | ".join(result.columns) + " |")
            parts.append("| " + " | ".join(["---"] * len(result.columns)) + " |")
            for row in result.rows:
                parts.append("| " + " | ".join(str(v) for v in row) + " |")
        return "\n".join(parts)

    def schema_to_markdown(self, schema: SchemaInfo) -> str:
        lines = [
            f"# Database Schema: {schema.db_name} ({schema.db_type})",
            "",
        ]

        for table in schema.tables:
            lines.extend(self._table_to_markdown(table))

        return "\n".join(lines)

    def schema_to_prompt_context(self, schema: SchemaInfo) -> str:
        """Rich representation for LLM context -- includes FKs, indexes, comments."""
        parts = [f"Database: {schema.db_name} (type: {schema.db_type})", ""]

        for table in schema.tables:
            parts.extend(self._table_to_prompt(table))
            parts.append("")

        all_fks = []
        for table in schema.tables:
            for fk in table.foreign_keys:
                all_fks.append(
                    f"  {table.name}.{fk.column} -> {fk.references_table}.{fk.references_column}"
                )

        if all_fks:
            parts.append("## All Relationships")
            parts.extend(all_fks)
            parts.append("")

        return "\n".join(parts)

    def _table_to_prompt(self, table: TableInfo) -> list[str]:
        lines = []
        prefix = (
            f"{table.schema}.{table.name}"
            if table.schema and table.schema != "public"
            else table.name
        )
        row_hint = f" (~{table.row_count:,} rows)" if table.row_count is not None else ""
        lines.append(f"## {prefix}{row_hint}")

        if table.comment:
            lines.append(f"  {table.comment}")

        lines.append("| Column | Type | PK | Nullable | Default | Comment |")
        lines.append("|--------|------|----|----------|---------|---------|")
        for col in table.columns:
            pk = "PK" if col.is_primary_key else ""
            nullable = "YES" if col.is_nullable else "NO"
            default = str(col.default) if col.default else ""
            comment = col.comment or ""
            lines.append(
                f"| {col.name} | {col.data_type} | {pk} | {nullable} | {default} | {comment} |"
            )

        if table.foreign_keys:
            fk_strs = [
                f"{fk.column} -> {fk.references_table}.{fk.references_column}"
                for fk in table.foreign_keys
            ]
            lines.append(f"  FK: {'; '.join(fk_strs)}")

        if table.indexes:
            idx_parts = []
            for idx in table.indexes:
                u = "UNIQUE " if idx.is_unique else ""
                idx_parts.append(f"{u}{idx.name}({', '.join(idx.columns)})")
            lines.append(f"  Indexes: {'; '.join(idx_parts)}")

        return lines

    def _table_to_markdown(self, table: TableInfo) -> list[str]:
        lines = []
        header = f"## Table: {table.schema}.{table.name}" if table.schema else f"## {table.name}"
        lines.append(header)
        if table.comment:
            lines.append(f"_{table.comment}_")
        if table.row_count is not None:
            lines.append(f"Rows: ~{table.row_count:,}")
        lines.append("")
        lines.append("| Column | Type | Nullable | PK | Default | Comment |")
        lines.append("|--------|------|----------|----|---------|---------|")
        for col in table.columns:
            pk = "YES" if col.is_primary_key else ""
            nullable = "YES" if col.is_nullable else "NO"
            default = col.default or ""
            comment = col.comment or ""
            lines.append(
                f"| {col.name} | {col.data_type} | {nullable} | {pk} | {default} | {comment} |"
            )
        lines.append("")

        if table.foreign_keys:
            lines.append("**Foreign Keys:**")
            for fk in table.foreign_keys:
                lines.append(f"- {fk.column} -> {fk.references_table}.{fk.references_column}")
            lines.append("")

        if table.indexes:
            lines.append("**Indexes:**")
            for idx in table.indexes:
                unique = " (UNIQUE)" if idx.is_unique else ""
                lines.append(f"- {idx.name}: ({', '.join(idx.columns)}){unique}")
            lines.append("")

        return lines
