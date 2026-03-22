"""Cross-file entity extraction and relationship mapping.

Pass 2-3 of the multi-pass indexing pipeline.
Builds an Entity Relationship Map by correlating ORM models,
foreign keys, imports, and usage across all project files.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.knowledge.repo_analyzer import (
    DB_RELEVANT_EXTENSIONS,
    ORM_PATTERNS,
    ORM_QUERY_CHAIN,
    RAW_SQL_IN_CODE,
    ExtractedSchema,
)

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    name: str
    col_type: str = ""
    is_pk: bool = False
    is_fk: bool = False
    fk_target: str = ""
    nullable: bool = True
    default: str = ""
    enum_values: list[str] = field(default_factory=list)


@dataclass
class EntityInfo:
    name: str
    table_name: str = ""
    file_path: str = ""
    columns: list[ColumnInfo] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    used_in_files: list[str] = field(default_factory=list)
    read_queries: int = 0
    write_queries: int = 0


@dataclass
class TableUsage:
    table_name: str
    readers: list[str] = field(default_factory=list)
    writers: list[str] = field(default_factory=list)
    orm_refs: list[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return bool(self.readers or self.writers or self.orm_refs)


@dataclass
class EnumDefinition:
    name: str
    values: list[str]
    file_path: str


@dataclass
class ValidationRule:
    """A data validation or constraint rule extracted from code."""

    rule_type: str  # "check", "unique", "validator", "constraint"
    expression: str
    file_path: str
    model_name: str = ""


@dataclass
class ConfigRef:
    """A database-related config/env variable reference."""

    var_name: str
    file_path: str
    context: str = ""


@dataclass
class QueryPattern:
    """A WHERE/filter condition found in code for a specific table."""

    table: str
    column: str
    operator: str
    value: str
    file_path: str
    snippet: str = ""


@dataclass
class ConstantMapping:
    """A constant definition that maps to a column value."""

    name: str
    value: str
    context: str
    file_path: str


@dataclass
class ScopeFilter:
    """A named scope/manager that defines default filters."""

    name: str
    table: str
    filter_expression: str
    file_path: str


@dataclass
class ProjectKnowledge:
    """Aggregate cross-file knowledge about the project's data layer."""

    entities: dict[str, EntityInfo] = field(default_factory=dict)
    table_usage: dict[str, TableUsage] = field(default_factory=dict)
    enums: list[EnumDefinition] = field(default_factory=list)
    service_functions: list[dict] = field(default_factory=list)
    config_refs: list[ConfigRef] = field(default_factory=list)
    validation_rules: list[ValidationRule] = field(default_factory=list)
    query_patterns: list[QueryPattern] = field(default_factory=list)
    constant_mappings: list[ConstantMapping] = field(default_factory=list)
    scope_filters: list[ScopeFilter] = field(default_factory=list)

    @property
    def dead_tables(self) -> list[str]:
        return [name for name, usage in self.table_usage.items() if not usage.is_active]

    def to_json(self) -> str:
        """Serialize to JSON for DB persistence."""
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, raw: str) -> ProjectKnowledge:
        """Deserialize from JSON stored in DB."""
        data = json.loads(raw)
        knowledge = cls()
        for name, edata in data.get("entities", {}).items():
            cols = [ColumnInfo(**c) for c in edata.pop("columns", [])]
            knowledge.entities[name] = EntityInfo(**edata, columns=cols)
        for tbl, udata in data.get("table_usage", {}).items():
            knowledge.table_usage[tbl] = TableUsage(**udata)
        for edef in data.get("enums", []):
            knowledge.enums.append(EnumDefinition(**edef))
        knowledge.service_functions = data.get("service_functions", [])
        for cref in data.get("config_refs", []):
            knowledge.config_refs.append(ConfigRef(**cref))
        for vr in data.get("validation_rules", []):
            knowledge.validation_rules.append(ValidationRule(**vr))
        for qp in data.get("query_patterns", []):
            knowledge.query_patterns.append(QueryPattern(**qp))
        for cm in data.get("constant_mappings", []):
            knowledge.constant_mappings.append(ConstantMapping(**cm))
        for sf in data.get("scope_filters", []):
            knowledge.scope_filters.append(ScopeFilter(**sf))
        return knowledge


WRITE_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|UPSERT)\b",
    re.IGNORECASE,
)
READ_SQL = re.compile(
    r"\b(?:SELECT|WITH)\b",
    re.IGNORECASE,
)
TABLE_REF_SQL = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+[`\"\[]?(\w+)[`\"\]]?",
    re.IGNORECASE,
)

PY_ENUM_CLASS = re.compile(
    r"class\s+(\w+)\(.*(?:Enum|StrEnum|IntEnum|TextChoices|IntegerChoices).*\):",
    re.MULTILINE,
)
PY_ENUM_MEMBER = re.compile(
    r"""^\s+(\w+)\s*=\s*['"](.*?)['"]""",
    re.MULTILINE,
)
TS_ENUM = re.compile(
    r"enum\s+(\w+)\s*\{([^}]+)\}",
    re.MULTILINE,
)
CONSTANT_DICT = re.compile(
    r"(\w+(?:_STATUS|_TYPE|_ROLE|_STATE|_KIND|_CHOICES|_OPTIONS))\s*[=:]\s*[\[{(]",
    re.IGNORECASE,
)

SERVICE_FUNC = re.compile(
    r"(?:async\s+)?(?:def|function)\s+(create_|update_|delete_|process_|handle_|get_|find_|fetch_|save_|remove_|add_|set_)(\w+)",
    re.MULTILINE,
)

DJANGO_VALIDATOR = re.compile(
    r"""validators\s*=\s*\[([^\]]+)\]""",
    re.MULTILINE,
)
DJANGO_CONSTRAINT = re.compile(
    r"""(?:models\.)?(?:CheckConstraint|UniqueConstraint)\s*\([^)]*(?:check|condition)\s*=[^)]*\)""",
    re.MULTILINE | re.DOTALL,
)
PRISMA_CONSTRAINT = re.compile(
    r"""@@(?:unique|index|check)\s*\(([^)]+)\)""",
    re.MULTILINE,
)
TYPEORM_CHECK = re.compile(
    r"""@Check\s*\(\s*['"`]([^'"`]+)['"`]\s*\)""",
    re.MULTILINE,
)
TYPEORM_UNIQUE = re.compile(
    r"""@Unique\s*\(\s*\[([^\]]+)\]\s*\)""",
    re.MULTILINE,
)

DB_ENV_VAR = re.compile(
    r"""(?:process\.env\.|os\.(?:environ|getenv)\s*[\[(]\s*|ENV\[)['"]?(DATABASE_URL|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD|DB_DATABASE|POSTGRES_\w+|MYSQL_\w+|MONGO_URI|MONGODB_URI|REDIS_URL|DATABASE_\w+)['"]?""",
    re.IGNORECASE,
)
DB_CONFIG_BLOCK = re.compile(
    r"""(?:DATABASES|database|db)\s*[=:]\s*\{[^}]*(?:host|port|user|password|name|engine|adapter)[^}]*\}""",
    re.IGNORECASE | re.DOTALL,
)

SQLALCHEMY_COL = re.compile(
    r"""(?:mapped_column|Column)\s*\(\s*(\w+(?:\([^)]*\))?)""",
    re.MULTILINE,
)
SQLALCHEMY_FK = re.compile(
    r"""ForeignKey\s*\(\s*['"]([\w.]+)['"]""",
    re.MULTILINE,
)
SQLALCHEMY_TABLE = re.compile(
    r"""__tablename__\s*=\s*['"]([\w]+)['"]""",
    re.MULTILINE,
)
DJANGO_FIELD = re.compile(
    r"""(\w+)\s*=\s*models\.(\w+Field)\s*\(""",
    re.MULTILINE,
)
DJANGO_FK = re.compile(
    r"""models\.ForeignKey\s*\(\s*['"]([\w.]+)['"]""",
    re.MULTILINE,
)

TYPEORM_COL = re.compile(
    r"""@Column\s*\(\s*\{?\s*(?:type:\s*)?['""]?(\w+)""",
    re.MULTILINE,
)
TYPEORM_FIELD = re.compile(
    r"""(\w+)\s*:\s*(\w+)(?:\s*\||\s*;)""",
    re.MULTILINE,
)
TYPEORM_FK = re.compile(
    r"""@(?:ManyToOne|OneToOne|ManyToMany|OneToMany)\s*\(\s*\(\)\s*=>\s*(\w+)""",
    re.MULTILINE,
)

PRISMA_FIELD = re.compile(
    r"""^\s+(\w+)\s+(String|Int|Float|Boolean|DateTime|BigInt|Decimal|Bytes|Json|Enum)\b""",
    re.MULTILINE,
)
PRISMA_RELATION = re.compile(
    r"""^\s+(\w+)\s+(\w+)(\[\])?\s+@relation""",
    re.MULTILINE,
)

SEQUELIZE_COL = re.compile(
    r"""(\w+)\s*:\s*\{?\s*type:\s*DataTypes\.(\w+)""",
    re.MULTILINE,
)
SEQUELIZE_COL_SHORT = re.compile(
    r"""(\w+)\s*:\s*DataTypes\.(\w+)""",
    re.MULTILINE,
)

MONGOOSE_FIELD = re.compile(
    r"""(\w+)\s*:\s*\{?\s*type:\s*(String|Number|Date|Boolean|ObjectId|Buffer|Map|Schema\.Types\.\w+)""",
    re.MULTILINE,
)
MONGOOSE_FIELD_SHORT = re.compile(
    r"""(\w+)\s*:\s*(String|Number|Date|Boolean|ObjectId)\b""",
    re.MULTILINE,
)

DRIZZLE_COL = re.compile(
    r"""(\w+)\s*:\s*(serial|varchar|integer|text|boolean|timestamp|bigint|real|doublePrecision|smallint|numeric|date|json|jsonb|uuid|char)\s*\(""",
    re.MULTILINE,
)

GORM_TAG = re.compile(
    r"""(\w+)\s+(\w+(?:\.\w+)?)\s+`[^`]*gorm:"([^"]*)"[^`]*`""",
    re.MULTILINE,
)
GORM_FK_TAG = re.compile(r"foreignKey:(\w+)", re.IGNORECASE)
GORM_COL_TAG = re.compile(r"column:(\w+)", re.IGNORECASE)

ACTIVERECORD_FIELD = re.compile(
    r"""t\.(string|integer|text|boolean|datetime|date|float|decimal|binary|bigint|timestamp|references|json|jsonb|uuid)\s+[:"'](\w+)""",
    re.MULTILINE,
)
ACTIVERECORD_BELONGS = re.compile(
    r"""belongs_to\s+:(\w+)""",
    re.MULTILINE,
)
ACTIVERECORD_HAS = re.compile(
    r"""has_(?:many|one)\s+:(\w+)""",
    re.MULTILINE,
)

JPA_COLUMN = re.compile(
    r"""@Column\s*(?:\(([^)]*)\))?\s*.*?(?:private|protected|public)\s+(\w+(?:<[^>]+>)?)\s+(\w+)\s*[;=]""",
    re.DOTALL,
)
JPA_COLUMN_NAME = re.compile(r"""name\s*=\s*"(\w+)""")
JPA_FK = re.compile(
    r"""@(?:ManyToOne|OneToOne|ManyToMany|OneToMany)[^@]*?(?:private|protected|public)\s+(?:List<)?(\w+)>?\s+(\w+)\s*[;=]""",
    re.DOTALL,
)


def build_project_knowledge(
    repo_dir: Path,
    schemas: list[ExtractedSchema],
    all_files: list[str] | None = None,
    changed_files: list[str] | None = None,
    deleted_files: list[str] | None = None,
    cached_knowledge: ProjectKnowledge | None = None,
    detected_orms: list[str] | None = None,
) -> ProjectKnowledge:
    """Build cross-file knowledge from extracted schemas and full file scan.

    When *cached_knowledge* and *changed_files* are both provided, only
    changed files are re-scanned; entities/enums/service_functions from
    unchanged files are preserved from the cache.  This avoids re-reading
    the entire repository on incremental indexing.
    """
    if cached_knowledge and changed_files is not None:
        knowledge = _incremental_update(
            repo_dir,
            schemas,
            cached_knowledge,
            changed_files,
            deleted_files=deleted_files or [],
            detected_orms=detected_orms,
        )
    else:
        knowledge = _full_scan(repo_dir, schemas, all_files, detected_orms=detected_orms)

    _resolve_enum_to_columns(knowledge)

    logger.info(
        "Project knowledge: %d entities, %d tables tracked, %d enums, %d dead tables",
        len(knowledge.entities),
        len(knowledge.table_usage),
        len(knowledge.enums),
        len(knowledge.dead_tables),
    )
    return knowledge


def _full_scan(
    repo_dir: Path,
    schemas: list[ExtractedSchema],
    all_files: list[str] | None,
    detected_orms: list[str] | None = None,
) -> ProjectKnowledge:
    knowledge = ProjectKnowledge()
    _extract_entities_from_schemas(schemas, knowledge, detected_orms)

    from app.knowledge.repo_analyzer import is_binary_file

    scan_files = all_files or _list_all_source_files(repo_dir)
    for rel_path in scan_files:
        fp = repo_dir / rel_path
        if not fp.exists() or not fp.is_file():
            continue
        if is_binary_file(fp):
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            logger.debug("Could not read %s", fp, exc_info=True)
            continue

        _scan_table_usage(rel_path, content, knowledge)
        _extract_enums(rel_path, content, knowledge)
        _extract_service_functions(rel_path, content, knowledge)
        _extract_config_refs(rel_path, content, knowledge)
        _extract_validation_rules(rel_path, content, knowledge)
        _extract_query_patterns(rel_path, content, knowledge)
        _extract_constant_mappings(rel_path, content, knowledge)
        _extract_scope_filters(rel_path, content, knowledge)

    return knowledge


def _incremental_update(
    repo_dir: Path,
    schemas: list[ExtractedSchema],
    cached: ProjectKnowledge,
    changed_files: list[str],
    deleted_files: list[str] | None = None,
    detected_orms: list[str] | None = None,
) -> ProjectKnowledge:
    """Re-scan only changed files, merging results with cached knowledge."""
    knowledge = ProjectKnowledge()

    _extract_entities_from_schemas(schemas, knowledge, detected_orms)
    for name, entity in cached.entities.items():
        if name not in knowledge.entities:
            knowledge.entities[name] = entity

    stale_set = set(changed_files) | set(deleted_files or [])

    for tbl, usage in cached.table_usage.items():
        new_usage = knowledge.table_usage.setdefault(
            tbl,
            TableUsage(table_name=tbl),
        )
        for r in usage.readers:
            if r not in stale_set and r not in new_usage.readers:
                new_usage.readers.append(r)
        for w in usage.writers:
            if w not in stale_set and w not in new_usage.writers:
                new_usage.writers.append(w)
        for o in usage.orm_refs:
            if o not in stale_set and o not in new_usage.orm_refs:
                new_usage.orm_refs.append(o)

    for enum_def in cached.enums:
        if enum_def.file_path not in stale_set:
            knowledge.enums.append(enum_def)

    for sf in cached.service_functions:
        if sf["file_path"] not in stale_set:
            knowledge.service_functions.append(sf)

    for cref in cached.config_refs:
        if cref.file_path not in stale_set:
            knowledge.config_refs.append(cref)

    for vr in cached.validation_rules:
        if vr.file_path not in stale_set:
            knowledge.validation_rules.append(vr)

    for qp in cached.query_patterns:
        if qp.file_path not in stale_set:
            knowledge.query_patterns.append(qp)

    for cm in cached.constant_mappings:
        if cm.file_path not in stale_set:
            knowledge.constant_mappings.append(cm)

    for scope in cached.scope_filters:
        if scope.file_path not in stale_set:
            knowledge.scope_filters.append(scope)

    deleted_set = set(deleted_files or [])
    for name in list(knowledge.entities.keys()):
        if knowledge.entities[name].file_path in deleted_set:
            del knowledge.entities[name]

    for entity in knowledge.entities.values():
        entity.used_in_files = [f for f in entity.used_in_files if f not in stale_set]

    from app.knowledge.repo_analyzer import is_binary_file

    for rel_path in changed_files:
        fp = repo_dir / rel_path
        if not fp.exists() or not fp.is_file():
            continue
        if is_binary_file(fp):
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            logger.debug("Could not read %s", fp, exc_info=True)
            continue

        _scan_table_usage(rel_path, content, knowledge)
        _extract_enums(rel_path, content, knowledge)
        _extract_service_functions(rel_path, content, knowledge)
        _extract_config_refs(rel_path, content, knowledge)
        _extract_validation_rules(rel_path, content, knowledge)
        _extract_query_patterns(rel_path, content, knowledge)
        _extract_constant_mappings(rel_path, content, knowledge)
        _extract_scope_filters(rel_path, content, knowledge)

    return knowledge


def _list_all_source_files(repo_dir: Path) -> list[str]:
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
    files = []
    for root, dirs, filenames in __import__("os").walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in filenames:
            p = Path(root) / f
            if p.suffix in DB_RELEVANT_EXTENSIONS:
                files.append(str(p.relative_to(repo_dir)))
    return files


def _extract_entities_from_schemas(
    schemas: list[ExtractedSchema],
    knowledge: ProjectKnowledge,
    detected_orms: list[str] | None = None,
) -> None:
    for schema in schemas:
        if schema.doc_type != "orm_model":
            for tbl in schema.tables:
                knowledge.table_usage.setdefault(tbl, TableUsage(table_name=tbl))
            continue

        content = schema.content
        file_path = schema.file_path

        table_matches = SQLALCHEMY_TABLE.findall(content)
        django_fks = DJANGO_FK.findall(content)
        sa_fks = SQLALCHEMY_FK.findall(content)

        for model_name in schema.models:
            entity = EntityInfo(
                name=model_name,
                file_path=file_path,
            )

            if table_matches:
                entity.table_name = table_matches[0]
            else:
                entity.table_name = _model_name_to_table(model_name)

            entity.columns = _extract_columns(content, file_path, detected_orms)

            for fk_target in sa_fks + django_fks:
                entity.relationships.append(fk_target)

            knowledge.entities[model_name] = entity
            knowledge.table_usage.setdefault(
                entity.table_name,
                TableUsage(table_name=entity.table_name),
            ).orm_refs.append(file_path)


def _extract_columns(
    content: str,
    file_path: str,
    detected_orms: list[str] | None = None,
) -> list[ColumnInfo]:
    columns: list[ColumnInfo] = []
    seen: set[str] = set()
    orms = set(detected_orms) if detected_orms else set()

    def _add(name: str, col_type: str, is_fk: bool = False, fk_target: str = "") -> None:
        if not name or name.startswith("_") or name in seen:
            return
        seen.add(name)
        columns.append(
            ColumnInfo(
                name=name,
                col_type=col_type,
                is_fk=is_fk,
                fk_target=fk_target,
            )
        )

    def _orm_match(*orm_names: str) -> bool:
        """Return True if no ORMs detected (run all) or any listed ORM matches."""
        if not orms:
            return True
        return bool(orms & set(orm_names))

    if file_path.endswith(".py"):
        if _orm_match("sqlalchemy", "tortoise"):
            for m in SQLALCHEMY_COL.finditer(content):
                col_type = m.group(1)
                line_start = content.rfind("\n", 0, m.start()) + 1
                line = content[line_start : m.start()].strip()
                parts = line.split(":")
                col_name = parts[0].strip().split()[-1] if parts else ""
                _add(
                    col_name,
                    col_type,
                    is_fk="ForeignKey" in content[m.start() : m.start() + 200],
                )

        if _orm_match("django_orm", "django"):
            for m in DJANGO_FIELD.finditer(content):
                _add(m.group(1), m.group(2), is_fk="ForeignKey" in m.group(2))

    elif file_path.endswith(".prisma"):
        for m in PRISMA_FIELD.finditer(content):
            _add(m.group(1), m.group(2))
        for m in PRISMA_RELATION.finditer(content):
            _add(m.group(1), m.group(2), is_fk=True, fk_target=m.group(2))

    elif file_path.endswith((".ts", ".tsx", ".js", ".jsx")):
        if _orm_match("typeorm"):
            for m in TYPEORM_COL.finditer(content):
                line_start = content.rfind("\n", 0, m.start()) + 1
                prev_line = content[max(0, line_start - 200) : line_start]
                name_match = re.search(r"(\w+)\s*[:;]\s*$", prev_line)
                col_name = name_match.group(1) if name_match else ""
                _add(col_name, m.group(1))
            for m in TYPEORM_FK.finditer(content):
                line_end = content.find("\n", m.end())
                after = content[m.end() : line_end + 200] if line_end != -1 else ""
                field_m = re.search(r"(\w+)\s*:", after)
                fname = field_m.group(1) if field_m else m.group(1).lower()
                _add(fname, m.group(1), is_fk=True, fk_target=m.group(1))

        if _orm_match("sequelize"):
            for m in SEQUELIZE_COL.finditer(content):
                _add(m.group(1), m.group(2))
            for m in SEQUELIZE_COL_SHORT.finditer(content):
                _add(m.group(1), m.group(2))

        if _orm_match("mongoose"):
            for m in MONGOOSE_FIELD.finditer(content):
                _add(m.group(1), m.group(2))
            for m in MONGOOSE_FIELD_SHORT.finditer(content):
                _add(m.group(1), m.group(2))

        if _orm_match("drizzle"):
            for m in DRIZZLE_COL.finditer(content):
                _add(m.group(1), m.group(2))

    elif file_path.endswith(".go"):
        for m in GORM_TAG.finditer(content):
            field_name = m.group(1)
            field_type = m.group(2)
            tag = m.group(3)
            col_name_m = GORM_COL_TAG.search(tag)
            col_name = col_name_m.group(1) if col_name_m else field_name
            is_fk = "foreignKey" in tag or "references" in tag.lower()
            fk_target = ""
            fk_m = GORM_FK_TAG.search(tag)
            if fk_m:
                fk_target = fk_m.group(1)
            _add(col_name, field_type, is_fk=is_fk, fk_target=fk_target)

    elif file_path.endswith(".rb"):
        for m in ACTIVERECORD_FIELD.finditer(content):
            col_type = m.group(1)
            col_name = m.group(2)
            is_fk = col_type == "references"
            _add(col_name, col_type, is_fk=is_fk, fk_target=col_name if is_fk else "")
        for m in ACTIVERECORD_BELONGS.finditer(content):
            _add(f"{m.group(1)}_id", "integer", is_fk=True, fk_target=m.group(1))

    elif file_path.endswith(".java") or file_path.endswith(".kt"):
        for m in JPA_COLUMN.finditer(content):
            anno_args = m.group(1) or ""
            field_type = m.group(2)
            field_name = m.group(3)
            name_m = JPA_COLUMN_NAME.search(anno_args)
            col_name = name_m.group(1) if name_m else field_name
            _add(col_name, field_type)
        for m in JPA_FK.finditer(content):
            target_type = m.group(1)
            field_name = m.group(2)
            _add(field_name, target_type, is_fk=True, fk_target=target_type)

    elif file_path.endswith(".graphql"):
        from app.knowledge.repo_analyzer import GRAPHQL_FIELD, GRAPHQL_TYPE

        for type_m in GRAPHQL_TYPE.finditer(content):
            body = type_m.group(2)
            for field_m in GRAPHQL_FIELD.finditer(body):
                fname = field_m.group(1)
                ftype = field_m.group(2).strip("[]!")
                is_fk = ftype[0].isupper() if ftype else False
                _add(fname, ftype, is_fk=is_fk, fk_target=ftype if is_fk else "")

    return columns


def _scan_table_usage(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    sql_kw = {"select", "from", "where", "set", "values", "into"}
    for m in TABLE_REF_SQL.finditer(content):
        tbl = m.group(1)
        if tbl.lower() in sql_kw:
            continue
        usage = knowledge.table_usage.setdefault(tbl, TableUsage(table_name=tbl))
        start = max(0, m.start() - 100)
        end = min(len(content), m.end() + 100)
        snippet = content[start:end]
        if WRITE_SQL.search(snippet):
            if rel_path not in usage.writers:
                usage.writers.append(rel_path)
        if READ_SQL.search(snippet):
            if rel_path not in usage.readers:
                usage.readers.append(rel_path)

    has_orm = any(p.search(content) for p in ORM_PATTERNS.values())
    has_query = ORM_QUERY_CHAIN.search(content) or RAW_SQL_IN_CODE.search(content)
    if has_orm or has_query:
        for entity in knowledge.entities.values():
            if rel_path == entity.file_path:
                continue
            pat = re.compile(r"\b" + re.escape(entity.name) + r"\b")
            if pat.search(content):
                if rel_path not in entity.used_in_files:
                    entity.used_in_files.append(rel_path)


def _extract_enums(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    for m in PY_ENUM_CLASS.finditer(content):
        enum_name = m.group(1)
        block_start = m.end()
        block_end = content.find("\nclass ", block_start)
        if block_end == -1:
            block_end = len(content)
        block = content[block_start:block_end]
        values = [v.group(2) for v in PY_ENUM_MEMBER.finditer(block)]
        if values:
            knowledge.enums.append(
                EnumDefinition(
                    name=enum_name,
                    values=values,
                    file_path=rel_path,
                )
            )

    for m in TS_ENUM.finditer(content):
        enum_name = m.group(1)
        body = m.group(2)
        values = [
            v.strip().strip("'\"").split("=")[-1].strip().strip("'\"")
            for v in body.split(",")
            if v.strip()
        ]
        if values:
            knowledge.enums.append(
                EnumDefinition(
                    name=enum_name,
                    values=values,
                    file_path=rel_path,
                )
            )

    for m in CONSTANT_DICT.finditer(content):
        const_name = m.group(1)
        block_start = m.end() - 1
        values = re.findall(r"""['"]([\w\-]+)['"]""", content[block_start : block_start + 500])
        if values:
            knowledge.enums.append(
                EnumDefinition(
                    name=const_name,
                    values=values[:20],
                    file_path=rel_path,
                )
            )


def _extract_service_functions(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    for m in SERVICE_FUNC.finditer(content):
        prefix = m.group(1)
        name = m.group(2)
        func_name = prefix + name

        func_start = m.start()
        func_end = min(len(content), func_start + 2000)
        func_body = content[func_start:func_end]

        tables_mentioned = []
        for entity in knowledge.entities.values():
            if entity.name in func_body:
                tables_mentioned.append(entity.table_name or entity.name)

        if tables_mentioned:
            knowledge.service_functions.append(
                {
                    "name": func_name,
                    "file_path": rel_path,
                    "tables": tables_mentioned,
                    "snippet": func_body[:500],
                }
            )


def _extract_validation_rules(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    """Extract data validation constraints from Django, Prisma, TypeORM code."""
    if rel_path.endswith(".py"):
        for m in DJANGO_VALIDATOR.finditer(content):
            knowledge.validation_rules.append(
                ValidationRule(
                    rule_type="validator",
                    expression=m.group(1).strip(),
                    file_path=rel_path,
                )
            )
        for m in DJANGO_CONSTRAINT.finditer(content):
            knowledge.validation_rules.append(
                ValidationRule(
                    rule_type="constraint",
                    expression=m.group(0).strip()[:200],
                    file_path=rel_path,
                )
            )

    elif rel_path.endswith(".prisma"):
        for m in PRISMA_CONSTRAINT.finditer(content):
            rule_type = "unique" if "unique" in m.group(0).lower() else "constraint"
            knowledge.validation_rules.append(
                ValidationRule(
                    rule_type=rule_type,
                    expression=m.group(1).strip(),
                    file_path=rel_path,
                )
            )

    elif rel_path.endswith((".ts", ".tsx", ".js", ".jsx")):
        for m in TYPEORM_CHECK.finditer(content):
            knowledge.validation_rules.append(
                ValidationRule(
                    rule_type="check",
                    expression=m.group(1).strip(),
                    file_path=rel_path,
                )
            )
        for m in TYPEORM_UNIQUE.finditer(content):
            knowledge.validation_rules.append(
                ValidationRule(
                    rule_type="unique",
                    expression=m.group(1).strip(),
                    file_path=rel_path,
                )
            )


def _extract_config_refs(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    """Detect database-related environment variables and config blocks."""
    seen_vars: set[str] = set()
    for m in DB_ENV_VAR.finditer(content):
        var_name = m.group(1)
        if var_name in seen_vars:
            continue
        seen_vars.add(var_name)
        ctx_start = max(0, m.start() - 80)
        ctx_end = min(len(content), m.end() + 80)
        knowledge.config_refs.append(
            ConfigRef(
                var_name=var_name,
                file_path=rel_path,
                context=content[ctx_start:ctx_end].strip(),
            )
        )

    if DB_CONFIG_BLOCK.search(content):
        knowledge.config_refs.append(
            ConfigRef(
                var_name="__db_config_block__",
                file_path=rel_path,
                context="Database configuration block detected",
            )
        )


SQL_WHERE_FILTER = re.compile(
    r"""(?:FROM|JOIN)\s+[`"\[]?(\w+)[`"\]]?\s+(?:\w+\s+)?WHERE\s+[`"\[]?(\w+)[`"\]]?\s*(=|!=|<>|>=|<=|>|<|IS(?:\s+NOT)?|IN|LIKE)\s*['"]?([^'")\s,;]+)""",
    re.IGNORECASE,
)
ORM_FILTER_CHAIN = re.compile(
    r"""\.(?:where|filter|find|filter_by|find_by)\s*\(\s*\{?\s*[`"']?(\w+)[`"']?\s*[:=]\s*['"]?([^'")\s,}]+)""",
    re.IGNORECASE,
)
ORM_EQ_FILTER = re.compile(
    r"""\.(?:where|filter)\s*\(\s*(\w+)\.(\w+)\s*==\s*['"]?([^'")\s,]+)""",
    re.IGNORECASE,
)
_CONST_SUFFIX = (
    r"(?:_STATUS|_STATE|_TYPE|_ROLE|_FLAG|_MODE"
    r"|_ACTIVE|_PROCESSED|_DELETED|_PENDING|_COMPLETED|_FAILED)"
)
CONST_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:const|let|var|export\s+(?:const|let))?\s*"
    r"([A-Z][A-Z0-9_]*" + _CONST_SUFFIX + r")"
    r"""\s*[=:]\s*['"]?(\d+|true|false|['"][^'"]+['"])""",
    re.MULTILINE | re.IGNORECASE,
)
CONST_PY_ASSIGNMENT = re.compile(
    r"^([A-Z][A-Z0-9_]*" + _CONST_SUFFIX + r")"
    r"""\s*=\s*['"]?(\d+|True|False|['"][^'"]+['"])""",
    re.MULTILINE,
)
CONST_DICT_MAP = re.compile(
    r"""([A-Z_]+(?:MAP|MAPPING|STATUSES|TYPES|ROLES|STATES|FLAGS))\s*[=:]\s*\{([^}]{5,500})\}""",
    re.IGNORECASE,
)
CONST_DICT_ENTRY = re.compile(
    r"""['"]?(\w+)['"]?\s*[:=]\s*['"]([^'"]+)['"]""",
)

DJANGO_SCOPE_MANAGER = re.compile(
    r"""class\s+(\w+Manager)\b[^{]*?def\s+get_queryset\s*\([^)]*\)[^:]*:([^}]{20,500})""",
    re.DOTALL,
)
DJANGO_SCOPE_FILTER = re.compile(
    r"""\.filter\s*\(([^)]+)\)""",
)
RAILS_SCOPE = re.compile(
    r"""scope\s+:(\w+)\s*,\s*->\s*(?:\([^)]*\))?\s*\{\s*(.*?)\}""",
    re.DOTALL,
)
LARAVEL_SCOPE = re.compile(
    r"""public\s+function\s+scope(\w+)\s*\(\s*\$query[^)]*\)[^{]*\{([^}]+)\}""",
    re.DOTALL,
)


def _extract_query_patterns(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    """Extract WHERE/filter conditions from SQL and ORM code."""
    for m in SQL_WHERE_FILTER.finditer(content):
        knowledge.query_patterns.append(
            QueryPattern(
                table=m.group(1),
                column=m.group(2),
                operator=m.group(3).strip(),
                value=m.group(4).strip("'\""),
                file_path=rel_path,
                snippet=content[max(0, m.start() - 20) : m.end() + 20].strip(),
            )
        )

    for m in ORM_FILTER_CHAIN.finditer(content):
        table = _infer_table_from_context(content, m.start(), knowledge)
        knowledge.query_patterns.append(
            QueryPattern(
                table=table,
                column=m.group(1),
                operator="=",
                value=m.group(2).strip("'\""),
                file_path=rel_path,
                snippet=content[max(0, m.start() - 20) : m.end() + 20].strip(),
            )
        )

    for m in ORM_EQ_FILTER.finditer(content):
        model_name = m.group(1)
        table = _model_to_table(model_name, knowledge)
        knowledge.query_patterns.append(
            QueryPattern(
                table=table,
                column=m.group(2),
                operator="=",
                value=m.group(3).strip("'\""),
                file_path=rel_path,
                snippet=content[max(0, m.start() - 20) : m.end() + 20].strip(),
            )
        )


def _extract_constant_mappings(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    """Extract constant definitions that map to column status/flag values."""
    for m in CONST_ASSIGNMENT.finditer(content):
        knowledge.constant_mappings.append(
            ConstantMapping(
                name=m.group(1),
                value=m.group(2).strip("'\""),
                context=content[max(0, m.start() - 10) : m.end() + 30].strip(),
                file_path=rel_path,
            )
        )
    for m in CONST_PY_ASSIGNMENT.finditer(content):
        knowledge.constant_mappings.append(
            ConstantMapping(
                name=m.group(1),
                value=m.group(2).strip("'\""),
                context=content[max(0, m.start() - 10) : m.end() + 30].strip(),
                file_path=rel_path,
            )
        )

    for m in CONST_DICT_MAP.finditer(content):
        dict_name = m.group(1)
        body = m.group(2)
        for entry in CONST_DICT_ENTRY.finditer(body):
            knowledge.constant_mappings.append(
                ConstantMapping(
                    name=f"{dict_name}[{entry.group(1)}]",
                    value=entry.group(2),
                    context=f"{dict_name}: {entry.group(1)} = {entry.group(2)}",
                    file_path=rel_path,
                )
            )


def _extract_scope_filters(
    rel_path: str,
    content: str,
    knowledge: ProjectKnowledge,
) -> None:
    """Extract ORM scopes and named query builders that define default filters."""
    for m in DJANGO_SCOPE_MANAGER.finditer(content):
        manager_name = m.group(1)
        body = m.group(2)
        filters = DJANGO_SCOPE_FILTER.findall(body)
        if filters:
            table = _infer_table_from_context(content, m.start(), knowledge)
            knowledge.scope_filters.append(
                ScopeFilter(
                    name=manager_name,
                    table=table,
                    filter_expression="; ".join(f.strip() for f in filters),
                    file_path=rel_path,
                )
            )

    for m in RAILS_SCOPE.finditer(content):
        scope_name = m.group(1)
        body = m.group(2).strip()
        table = _infer_table_from_context(content, m.start(), knowledge)
        knowledge.scope_filters.append(
            ScopeFilter(
                name=scope_name,
                table=table,
                filter_expression=body[:300],
                file_path=rel_path,
            )
        )

    for m in LARAVEL_SCOPE.finditer(content):
        scope_name = m.group(1)
        body = m.group(2).strip()
        table = _infer_table_from_context(content, m.start(), knowledge)
        knowledge.scope_filters.append(
            ScopeFilter(
                name=scope_name,
                table=table,
                filter_expression=body[:300],
                file_path=rel_path,
            )
        )


def _infer_table_from_context(
    content: str,
    position: int,
    knowledge: ProjectKnowledge,
) -> str:
    """Best-effort: look backwards for a model/table name near the match position."""
    window = content[max(0, position - 500) : position]
    for entity in knowledge.entities.values():
        if entity.name in window:
            return entity.table_name or entity.name
    table_m = SQLALCHEMY_TABLE.search(window)
    if table_m:
        return table_m.group(1)
    return "unknown"


def _model_to_table(model_name: str, knowledge: ProjectKnowledge) -> str:
    """Convert model name to table name using knowledge or heuristic."""
    entity = knowledge.entities.get(model_name)
    if entity and entity.table_name:
        return entity.table_name
    return _model_name_to_table(model_name)


def _resolve_enum_to_columns(knowledge: ProjectKnowledge) -> None:
    """Try to match enum definitions to entity columns by naming convention."""
    for enum_def in knowledge.enums:
        normalized = enum_def.name.lower().replace("_", "")
        for entity in knowledge.entities.values():
            for col in entity.columns:
                col_norm = col.name.lower().replace("_", "")
                entity_norm = entity.name.lower().replace("_", "")
                if (
                    col_norm in normalized
                    or normalized.startswith(entity_norm + col_norm)
                    or normalized.endswith(col_norm + "s")
                ):
                    col.enum_values = enum_def.values


def _model_name_to_table(model_name: str) -> str:
    """Convert CamelCase model name to snake_case table name (heuristic)."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", model_name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower() + "s"
