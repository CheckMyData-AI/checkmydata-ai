"""Auto-detect project framework, language, and structure.

Pass 1 of the multi-pass indexing pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FRAMEWORK_MARKERS: list[tuple[str, str, list[str]]] = [
    # (framework_name, marker_file_glob, content_patterns)
    ("django", "manage.py", []),
    ("django", "settings.py", ["INSTALLED_APPS"]),
    ("flask", "app.py", ["Flask(__name__)"]),
    ("fastapi", "main.py", ["FastAPI()"]),
    ("rails", "Gemfile", ["rails"]),
    ("rails", "config/routes.rb", []),
    ("spring", "pom.xml", ["spring-boot"]),
    ("spring", "build.gradle", ["spring-boot"]),
    ("express", "package.json", ['"express"']),
    ("nestjs", "package.json", ['"@nestjs/core"']),
    ("nextjs", "package.json", ['"next"']),
    ("laravel", "composer.json", ['"laravel/framework"']),
    ("phoenix", "mix.exs", [":phoenix"]),
    ("go-fiber", "go.mod", ["gofiber/fiber"]),
    ("go-gin", "go.mod", ["gin-gonic/gin"]),
]

ORM_MARKERS: list[tuple[str, str, list[str]]] = [
    ("sqlalchemy", "requirements.txt", ["sqlalchemy"]),
    ("sqlalchemy", "pyproject.toml", ["sqlalchemy"]),
    ("django_orm", "settings.py", ["DATABASES"]),
    ("prisma", "prisma/schema.prisma", []),
    ("drizzle", "package.json", ['"drizzle-orm"']),
    ("typeorm", "package.json", ['"typeorm"']),
    ("sequelize", "package.json", ['"sequelize"']),
    ("mongoose", "package.json", ['"mongoose"']),
    ("gorm", "go.mod", ["gorm.io/gorm"]),
    ("activerecord", "Gemfile", ["activerecord"]),
    ("peewee", "requirements.txt", ["peewee"]),
    ("tortoise", "requirements.txt", ["tortoise-orm"]),
]


@dataclass
class ProjectProfile:
    """Detected project characteristics."""

    frameworks: list[str] = field(default_factory=list)
    orms: list[str] = field(default_factory=list)
    primary_language: str = ""
    model_dirs: list[str] = field(default_factory=list)
    migration_dirs: list[str] = field(default_factory=list)
    service_dirs: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = []
        if self.frameworks:
            parts.append(f"Frameworks: {', '.join(self.frameworks)}")
        if self.orms:
            parts.append(f"ORMs: {', '.join(self.orms)}")
        if self.primary_language:
            parts.append(f"Language: {self.primary_language}")
        return " | ".join(parts) if parts else "Unknown project type"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> ProjectProfile:
        return cls(**json.loads(raw))

    @property
    def marker_files(self) -> set[str]:
        """Files whose change should invalidate the cached profile."""
        markers = {
            "package.json",
            "requirements.txt",
            "pyproject.toml",
            "Gemfile",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "composer.json",
            "mix.exs",
            "manage.py",
            "settings.py",
            "prisma/schema.prisma",
        }
        return markers


LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".rb": "ruby",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".kt": "kotlin",
    ".php": "php",
    ".ex": "elixir",
    ".exs": "elixir",
}

SERVICE_DIR_PATTERNS = re.compile(
    r"(?:services?|handlers?|controllers?|views?|api|endpoints?|use_?cases?|interactors?)",
    re.IGNORECASE,
)

MODEL_DIR_PATTERNS = re.compile(
    r"(?:models?|entities|schemas?|domain)",
    re.IGNORECASE,
)

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "vendor",
    "target",
}


def detect_project_profile(repo_dir: Path) -> ProjectProfile:
    """Scan repository root to detect framework, ORM, language, and directory roles."""
    profile = ProjectProfile()

    _detect_markers(repo_dir, profile)
    _detect_language(repo_dir, profile)
    _detect_directories(repo_dir, profile)

    logger.info("Project profile: %s", profile.summary)
    return profile


def _detect_markers(repo_dir: Path, profile: ProjectProfile) -> None:
    for fw_name, marker, content_pats in FRAMEWORK_MARKERS:
        marker_path = repo_dir / marker
        if marker_path.exists():
            if not content_pats:
                profile.frameworks.append(fw_name)
                continue
            try:
                text = marker_path.read_text(errors="ignore")[:20_000]
                if all(p.lower() in text.lower() for p in content_pats):
                    profile.frameworks.append(fw_name)
            except Exception:
                logger.debug(
                    "Failed to read %s for framework detection", marker_path, exc_info=True
                )

    for orm_name, marker, content_pats in ORM_MARKERS:
        marker_path = repo_dir / marker
        if marker_path.exists():
            if not content_pats:
                profile.orms.append(orm_name)
                continue
            try:
                text = marker_path.read_text(errors="ignore")[:20_000]
                if all(p.lower() in text.lower() for p in content_pats):
                    profile.orms.append(orm_name)
            except Exception:
                logger.debug("Failed to read %s for ORM detection", marker_path, exc_info=True)

    profile.frameworks = list(dict.fromkeys(profile.frameworks))
    profile.orms = list(dict.fromkeys(profile.orms))


def _detect_language(repo_dir: Path, profile: ProjectProfile) -> None:
    counts: dict[str, int] = {}
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            ext = Path(f).suffix
            lang = LANGUAGE_EXTENSIONS.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    if counts:
        profile.primary_language = max(counts, key=counts.get)  # type: ignore[arg-type]


def _detect_directories(repo_dir: Path, profile: ProjectProfile) -> None:
    for root, dirs, _files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for d in dirs:
            rel = str(Path(root, d).relative_to(repo_dir))
            name = d.lower()
            if MODEL_DIR_PATTERNS.match(name):
                profile.model_dirs.append(rel)
            if SERVICE_DIR_PATTERNS.match(name):
                profile.service_dirs.append(rel)
            if name in {"migrations", "alembic", "migrate", "db", "prisma"}:
                profile.migration_dirs.append(rel)
            if name in {"tests", "test", "__tests__", "spec", "specs"}:
                profile.test_dirs.append(rel)
            if name in {"config", "settings", "conf"}:
                profile.config_files.append(rel)
