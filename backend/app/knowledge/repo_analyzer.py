from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from git import Repo

if TYPE_CHECKING:
    from app.knowledge.project_profiler import ProjectProfile

logger = logging.getLogger(__name__)

ORM_PATTERNS = {
    "sqlalchemy": re.compile(
        r"(?:Column|mapped_column|relationship|ForeignKey)", re.MULTILINE,
    ),
    "django": re.compile(
        r"class\s+\w+\(.*models\.Model\)", re.MULTILINE,
    ),
    "tortoise": re.compile(
        r"class\s+\w+\(.*Model\).*fields\.", re.DOTALL,
    ),
    "prisma": re.compile(r"model\s+\w+\s*\{", re.MULTILINE),
    "typeorm": re.compile(
        r"@(?:Entity|Column|PrimaryGeneratedColumn|ManyToOne|OneToMany|ManyToMany|JoinColumn|JoinTable)\s*\(",
        re.MULTILINE,
    ),
    "sequelize": re.compile(
        r"(?:sequelize\.define|Model\.init|DataTypes\.\w+|\.hasMany|\.belongsTo|\.belongsToMany)",
        re.MULTILINE,
    ),
    "drizzle": re.compile(
        r"(?:pgTable|mysqlTable|sqliteTable|serial|varchar|integer|text)\s*\(",
        re.MULTILINE,
    ),
    "mongoose": re.compile(
        r"(?:new\s+Schema\s*\(|mongoose\.model\s*\(|Schema\.Types\.)",
        re.MULTILINE,
    ),
    "peewee": re.compile(
        r"class\s+\w+\(.*(?:Model|BaseModel)\).*(?:CharField|IntegerField|ForeignKeyField|TextField)",
        re.DOTALL,
    ),
    "gorm": re.compile(
        r'`gorm:"[^"]*"`',
        re.MULTILINE,
    ),
    "activerecord": re.compile(
        r"class\s+\w+\s*<\s*(?:ApplicationRecord|ActiveRecord::Base)",
        re.MULTILINE,
    ),
}

SQL_FILE_EXTENSIONS = {".sql"}
MIGRATION_DIRS = {
    "migrations", "alembic", "migrate", "db/migrate",
    "prisma/migrations", "drizzle",
}

DB_RELEVANT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".rb", ".java", ".go", ".rs", ".kt",
    ".sql", ".prisma", ".graphql",
}

RAW_SQL_IN_CODE = re.compile(
    r"(?:execute|query|raw|text)\s*\(\s*"
    r"(?:f?['\"]{1,3}|`)"
    r"((?:SELECT|INSERT|UPDATE|DELETE|WITH)\b.+?)"
    r"(?:['\"]{1,3}|`)\s*\)",
    re.IGNORECASE | re.DOTALL,
)

TAGGED_TEMPLATE_SQL = re.compile(
    r"(?:sql|Prisma\.sql|knex\.raw)\s*`"
    r"((?:SELECT|INSERT|UPDATE|DELETE|WITH)\b[^`]+)"
    r"`",
    re.IGNORECASE | re.DOTALL,
)

ORM_QUERY_CHAIN = re.compile(
    r"""\.(?:filter|where|join|outerjoin|group_by|order_by|having|select_from|distinct|findAll|findOne|findMany|findFirst|aggregate|include|populate|preload|eager_load)\s*\(""",
    re.MULTILINE,
)


@dataclass
class ExtractedSchema:
    file_path: str
    doc_type: str  # orm_model | migration | raw_sql | config
    content: str
    models: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)


class RepoAnalyzer:
    """Clones a Git repo and extracts database-related schemas and patterns."""

    def __init__(self, clone_base_dir: str):
        self._clone_base_dir = Path(clone_base_dir)
        self._clone_base_dir.mkdir(parents=True, exist_ok=True)

    def get_repo_dir(self, project_id: str) -> Path:
        return self._clone_base_dir / project_id

    def clone_or_pull(
        self,
        repo_url: str,
        project_id: str,
        branch: str = "main",
        ssh_key_content: str | None = None,
        ssh_key_passphrase: str | None = None,
    ) -> Path:
        import subprocess
        import tempfile

        repo_dir = self._clone_base_dir / project_id
        env: dict[str, str] = {}
        temp_key_file: str | None = None
        agent_pid: str | None = None
        agent_sock: str | None = None
        try:
            if ssh_key_content:
                import asyncssh
                parsed = asyncssh.import_private_key(
                    ssh_key_content, ssh_key_passphrase,
                )
                unprotected_pem = parsed.export_private_key("openssh").decode()

                try:
                    agent_out = subprocess.check_output(
                        ["ssh-agent", "-s"], text=True,
                    )
                    for line in agent_out.splitlines():
                        if "SSH_AUTH_SOCK" in line:
                            agent_sock = line.split(";")[0].split("=")[1]
                        elif "SSH_AGENT_PID" in line:
                            agent_pid = line.split(";")[0].split("=")[1]

                    if agent_sock:
                        add_env = {
                            **os.environ,
                            "SSH_AUTH_SOCK": agent_sock,
                        }
                        proc = subprocess.Popen(
                            ["ssh-add", "-"],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env=add_env,
                        )
                        proc.communicate(input=unprotected_pem.encode())
                        env["SSH_AUTH_SOCK"] = agent_sock
                        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no"
                except Exception:
                    logger.debug(
                        "ssh-agent approach failed, falling back to temp file",
                        exc_info=True,
                    )
                    agent_pid = None
                    agent_sock = None

                if not agent_sock:
                    fd, temp_key_file = tempfile.mkstemp(prefix="dbagent_ssh_")
                    with os.fdopen(fd, "w") as f:
                        f.write(unprotected_pem)
                    os.chmod(temp_key_file, 0o600)
                    env["GIT_SSH_COMMAND"] = (
                        f"ssh -i {temp_key_file} -o StrictHostKeyChecking=no"
                    )

            if repo_dir.exists() and (repo_dir / ".git").exists():
                repo = Repo(str(repo_dir))
                with repo.git.custom_environment(**env):
                    repo.remotes.origin.fetch()
                    repo.git.checkout(branch)
                    repo.remotes.origin.pull()
                logger.info("Pulled latest for %s on branch %s", project_id, branch)
            else:
                repo_dir.mkdir(parents=True, exist_ok=True)
                Repo.clone_from(
                    repo_url,
                    str(repo_dir),
                    branch=branch,
                    env=env if env else None,
                )
                logger.info("Cloned %s to %s", repo_url, repo_dir)
        finally:
            if temp_key_file and os.path.exists(temp_key_file):
                os.unlink(temp_key_file)
            if agent_pid:
                try:
                    os.kill(int(agent_pid), 15)
                except (ProcessLookupError, ValueError):
                    pass

        return repo_dir

    def analyze(
        self,
        repo_dir: Path,
        files: list[str] | None = None,
        profile: ProjectProfile | None = None,
    ) -> list[ExtractedSchema]:
        """Analyze the repo (or specific files) for database-related code.

        When *profile* is given, files from model_dirs are analyzed first
        so their results appear earlier (useful if the pipeline applies
        short-circuit logic or ordering later).
        """
        results: list[ExtractedSchema] = []

        if files:
            file_paths = [repo_dir / f for f in files]
        else:
            file_paths = self._find_db_relevant_files(repo_dir, profile)

        if profile and profile.model_dirs:
            model_set = set(profile.model_dirs)
            file_paths = sorted(
                file_paths,
                key=lambda fp: not any(
                    str(fp.relative_to(repo_dir)).startswith(md)
                    for md in model_set
                ),
            )

        for fp in file_paths:
            if not fp.exists() or not fp.is_file():
                continue
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            rel_path = str(fp.relative_to(repo_dir))
            extracted = self._analyze_file(rel_path, content, profile)
            if extracted:
                results.extend(extracted)

        logger.info("Analyzed %d files, found %d schemas", len(file_paths), len(results))
        return results

    def _find_db_relevant_files(
        self,
        repo_dir: Path,
        profile: ProjectProfile | None = None,
    ) -> list[Path]:
        relevant = []
        skip = {".git", "node_modules", "__pycache__", ".venv", "venv"}

        extra_dirs: set[str] = set()
        if profile:
            extra_dirs.update(profile.model_dirs)
            extra_dirs.update(profile.migration_dirs)

        for root, dirs, filenames in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d not in skip]
            for name in filenames:
                fp = Path(root) / name
                if fp.suffix in DB_RELEVANT_EXTENSIONS:
                    relevant.append(fp)
                    continue
                if extra_dirs:
                    rel = str(fp.relative_to(repo_dir))
                    if any(rel.startswith(ed) for ed in extra_dirs):
                        relevant.append(fp)
        return relevant

    def _analyze_file(
        self,
        rel_path: str,
        content: str,
        profile: ProjectProfile | None = None,
    ) -> list[ExtractedSchema]:
        results = []

        if rel_path.endswith(".sql"):
            tables = re.findall(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?",
                content,
                re.IGNORECASE,
            )
            results.append(
                ExtractedSchema(
                    file_path=rel_path,
                    doc_type="raw_sql",
                    content=content,
                    tables=tables,
                )
            )
            return results

        migration_dirs_to_check = set(MIGRATION_DIRS)
        if profile and profile.migration_dirs:
            migration_dirs_to_check.update(profile.migration_dirs)
        is_migration = any(mdir in rel_path for mdir in migration_dirs_to_check)
        if is_migration:
            tables = re.findall(
                r"(?:create_table|CreateTable|CREATE TABLE)\s+['\"`]?(\w+)",
                content, re.IGNORECASE,
            )
            results.append(
                ExtractedSchema(
                    file_path=rel_path,
                    doc_type="migration",
                    content=content,
                    tables=tables,
                )
            )
            return results

        if profile and "django" in profile.frameworks:
            if rel_path.endswith("admin.py") and "ModelAdmin" in content:
                results.append(
                    ExtractedSchema(
                        file_path=rel_path,
                        doc_type="orm_model",
                        content=content,
                        models=re.findall(r"class\s+(\w+Admin)", content),
                    )
                )
            if "db/schema.rb" in rel_path:
                tables = re.findall(
                    r'create_table\s+["\'](\w+)',
                    content,
                )
                results.append(ExtractedSchema(
                    file_path=rel_path,
                    doc_type="raw_sql",
                    content=content,
                    tables=tables,
                ))
                return results

        if profile and "rails" in profile.frameworks:
            if "db/schema.rb" in rel_path:
                tables = re.findall(
                    r'create_table\s+["\'](\w+)',
                    content,
                )
                results.append(ExtractedSchema(
                    file_path=rel_path,
                    doc_type="raw_sql",
                    content=content,
                    tables=tables,
                ))
                return results

        for orm_name, pattern in ORM_PATTERNS.items():
            if pattern.search(content):
                models = self._extract_model_names(rel_path, content)
                results.append(
                    ExtractedSchema(
                        file_path=rel_path,
                        doc_type="orm_model",
                        content=content,
                        models=models,
                    )
                )
                break

        query_patterns = self._extract_query_patterns(rel_path, content)
        if query_patterns:
            results.append(query_patterns)

        return results

    def _extract_model_names(self, rel_path: str, content: str) -> list[str]:
        if rel_path.endswith(".py"):
            return self._extract_python_classes(content)
        class_pattern = re.compile(r"class\s+(\w+)")
        return class_pattern.findall(content)

    def _extract_python_classes(self, content: str) -> list[str]:
        try:
            tree = ast.parse(content)
            return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        except SyntaxError:
            return re.findall(r"class\s+(\w+)", content)

    def _extract_query_patterns(self, rel_path: str, content: str) -> ExtractedSchema | None:
        """Detect raw SQL queries and ORM query chains in application code."""
        snippets: list[str] = []

        for m in RAW_SQL_IN_CODE.finditer(content):
            sql = m.group(1).strip()
            if len(sql) > 20:
                ctx_start = max(0, m.start() - 200)
                ctx_end = min(len(content), m.end() + 100)
                snippets.append(content[ctx_start:ctx_end].strip())

        for m in TAGGED_TEMPLATE_SQL.finditer(content):
            sql = m.group(1).strip()
            if len(sql) > 20:
                ctx_start = max(0, m.start() - 200)
                ctx_end = min(len(content), m.end() + 100)
                snippets.append(content[ctx_start:ctx_end].strip())

        if ORM_QUERY_CHAIN.search(content):
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if ORM_QUERY_CHAIN.search(line):
                    start = max(0, i - 3)
                    end = min(len(lines), i + 4)
                    snippets.append("\n".join(lines[start:end]))

        if not snippets:
            return None

        tables = re.findall(
            r"\bFROM\s+[`\"]?(\w+)[`\"]?",
            "\n".join(snippets),
            re.IGNORECASE,
        )
        joined = "\n---\n".join(snippets)
        return ExtractedSchema(
            file_path=rel_path,
            doc_type="query_pattern",
            content=joined,
            tables=list(set(tables)),
        )
