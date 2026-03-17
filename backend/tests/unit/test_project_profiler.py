import os
import tempfile
from pathlib import Path

from app.knowledge.project_profiler import (
    ProjectProfile,
    detect_project_profile,
)


class TestProjectProfiler:
    def _create_repo(self, structure: dict[str, str]) -> Path:
        """Create a temporary directory tree from a dict of {path: content}."""
        tmp = Path(tempfile.mkdtemp())
        for rel_path, content in structure.items():
            fp = tmp / rel_path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
        return tmp

    def test_detect_django(self):
        repo = self._create_repo(
            {
                "manage.py": "#!/usr/bin/env python\nimport django",
                "settings.py": "INSTALLED_APPS = ['myapp']\nDATABASES = {'default': {}}",
                "myapp/models.py": "from django.db import models",
            }
        )
        profile = detect_project_profile(repo)
        assert "django" in profile.frameworks
        assert "django_orm" in profile.orms

    def test_detect_fastapi_sqlalchemy(self):
        repo = self._create_repo(
            {
                "main.py": "from fastapi import FastAPI\napp = FastAPI()",
                "requirements.txt": "fastapi\nsqlalchemy>=2.0",
            }
        )
        profile = detect_project_profile(repo)
        assert "fastapi" in profile.frameworks
        assert "sqlalchemy" in profile.orms

    def test_detect_express_typeorm(self):
        repo = self._create_repo(
            {
                "package.json": '{"dependencies": {"express": "^4.0", "typeorm": "^0.3"}}',
                "src/index.ts": "import express from 'express'",
            }
        )
        profile = detect_project_profile(repo)
        assert "express" in profile.frameworks
        assert "typeorm" in profile.orms

    def test_detect_prisma(self):
        repo = self._create_repo(
            {
                "prisma/schema.prisma": "model User {\n  id Int @id\n}",
                "package.json": '{"dependencies": {"next": "^14"}}',
            }
        )
        profile = detect_project_profile(repo)
        assert "prisma" in profile.orms
        assert "nextjs" in profile.frameworks

    def test_primary_language_python(self):
        repo = self._create_repo(
            {
                "a.py": "pass",
                "b.py": "pass",
                "c.py": "pass",
                "d.js": "console.log(1)",
            }
        )
        profile = detect_project_profile(repo)
        assert profile.primary_language == "python"

    def test_primary_language_typescript(self):
        repo = self._create_repo(
            {
                "a.ts": "const x = 1",
                "b.ts": "const y = 2",
                "c.tsx": "export default function App() {}",
                "d.py": "pass",
            }
        )
        profile = detect_project_profile(repo)
        assert profile.primary_language == "typescript"

    def test_model_dirs_detected(self):
        repo = self._create_repo(
            {
                "src/models/user.py": "class User: pass",
                "src/services/auth.py": "def login(): pass",
                "tests/test_user.py": "def test(): pass",
            }
        )
        profile = detect_project_profile(repo)
        model_dir_names = [os.path.basename(d) for d in profile.model_dirs]
        assert "models" in model_dir_names
        service_dir_names = [os.path.basename(d) for d in profile.service_dirs]
        assert "services" in service_dir_names
        test_dir_names = [os.path.basename(d) for d in profile.test_dirs]
        assert "tests" in test_dir_names

    def test_unknown_project(self):
        repo = self._create_repo(
            {
                "readme.md": "# My project",
            }
        )
        profile = detect_project_profile(repo)
        assert profile.summary == "Unknown project type"

    def test_summary_format(self):
        p = ProjectProfile(
            frameworks=["fastapi"],
            orms=["sqlalchemy"],
            primary_language="python",
        )
        assert "fastapi" in p.summary
        assert "sqlalchemy" in p.summary
        assert "python" in p.summary

    def test_skip_dirs_ignored(self):
        repo = self._create_repo(
            {
                "node_modules/express/index.js": "module.exports = {}",
                ".git/config": "[core]",
                "src/app.py": "pass",
            }
        )
        profile = detect_project_profile(repo)
        assert profile.primary_language == "python"
