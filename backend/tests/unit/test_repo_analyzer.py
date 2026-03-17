import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.knowledge.repo_analyzer import RepoAnalyzer


class TestListRemoteRefs:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = RepoAnalyzer(clone_base_dir=self.tmpdir)

    @patch("subprocess.run")
    def test_success_with_branches(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "abc123\trefs/heads/develop\n"
                "def456\trefs/heads/main\n"
                "ghi789\trefs/heads/feature/x\n"
            ),
            stderr="",
        )
        result = self.analyzer.list_remote_refs("git@github.com:org/repo.git")
        assert result["accessible"] is True
        assert "main" in result["branches"]
        assert "develop" in result["branches"]
        assert "feature/x" in result["branches"]
        assert result["default_branch"] == "main"
        assert result["error"] is None

    @patch("subprocess.run")
    def test_prefers_main_over_master(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="a\trefs/heads/main\nb\trefs/heads/master\n",
            stderr="",
        )
        result = self.analyzer.list_remote_refs("https://github.com/org/repo.git")
        assert result["default_branch"] == "main"

    @patch("subprocess.run")
    def test_falls_back_to_master(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="a\trefs/heads/master\nb\trefs/heads/develop\n",
            stderr="",
        )
        result = self.analyzer.list_remote_refs("https://github.com/org/repo.git")
        assert result["default_branch"] == "master"

    @patch("subprocess.run")
    def test_falls_back_to_first_branch(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="a\trefs/heads/production\nb\trefs/heads/staging\n",
            stderr="",
        )
        result = self.analyzer.list_remote_refs("https://github.com/org/repo.git")
        assert result["default_branch"] == "production"

    @patch("subprocess.run")
    def test_access_denied(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="Permission denied (publickey).",
        )
        result = self.analyzer.list_remote_refs("git@github.com:org/repo.git")
        assert result["accessible"] is False
        assert result["branches"] == []
        assert result["default_branch"] is None
        assert "Permission denied" in result["error"]

    @patch("subprocess.run")
    def test_repo_not_found(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: repository 'https://github.com/org/nope.git/' not found",
        )
        result = self.analyzer.list_remote_refs("https://github.com/org/nope.git")
        assert result["accessible"] is False
        assert "not found" in result["error"]

    @patch("subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=15)
        result = self.analyzer.list_remote_refs("git@slow.host:repo.git", timeout=15)
        assert result["accessible"] is False
        assert "timed out" in result["error"]

    @patch("subprocess.run")
    def test_empty_repo(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        result = self.analyzer.list_remote_refs("https://github.com/org/empty.git")
        assert result["accessible"] is True
        assert result["branches"] == []
        assert result["default_branch"] is None


class TestRepoAnalyzer:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = RepoAnalyzer(clone_base_dir=self.tmpdir)

    def test_analyze_sql_file(self):
        repo_dir = Path(self.tmpdir) / "test_repo"
        repo_dir.mkdir()
        sql_file = repo_dir / "schema.sql"
        sql_file.write_text(
            "CREATE TABLE users (id SERIAL PRIMARY KEY, name VARCHAR(255));\n"
            "CREATE TABLE orders (id SERIAL PRIMARY KEY, user_id INT);\n"
        )

        results = self.analyzer.analyze(repo_dir)
        assert len(results) == 1
        assert results[0].doc_type == "raw_sql"
        assert "users" in results[0].tables
        assert "orders" in results[0].tables

    def test_analyze_python_orm_model(self):
        repo_dir = Path(self.tmpdir) / "test_repo2"
        repo_dir.mkdir()
        model_file = repo_dir / "models.py"
        model_file.write_text(
            "from sqlalchemy import Column, Integer, String\n"
            "from sqlalchemy.orm import DeclarativeBase\n\n"
            "class Base(DeclarativeBase):\n"
            "    pass\n\n"
            "class User(Base):\n"
            "    __tablename__ = 'users'\n"
            "    id = Column(Integer, primary_key=True)\n"
            "    name = Column(String(255))\n"
        )

        results = self.analyzer.analyze(repo_dir)
        assert len(results) == 1
        assert results[0].doc_type == "orm_model"
        assert "User" in results[0].models

    def test_analyze_migration_file(self):
        repo_dir = Path(self.tmpdir) / "test_repo3"
        (repo_dir / "migrations").mkdir(parents=True)
        mig_file = repo_dir / "migrations" / "001_create_users.py"
        mig_file.write_text("def upgrade():\n    op.create_table('users', ...)\n")

        results = self.analyzer.analyze(repo_dir)
        assert len(results) == 1
        assert results[0].doc_type == "migration"

    def test_analyze_no_relevant_files(self):
        repo_dir = Path(self.tmpdir) / "test_repo4"
        repo_dir.mkdir()
        (repo_dir / "readme.txt").write_text("Hello world")

        results = self.analyzer.analyze(repo_dir)
        assert len(results) == 0

    def test_analyze_specific_files(self):
        repo_dir = Path(self.tmpdir) / "test_repo5"
        repo_dir.mkdir()
        (repo_dir / "a.sql").write_text("CREATE TABLE t1 (id INT);")
        (repo_dir / "b.sql").write_text("CREATE TABLE t2 (id INT);")

        results = self.analyzer.analyze(repo_dir, files=["a.sql"])
        assert len(results) == 1
        assert "t1" in results[0].tables

    def test_extract_query_patterns_raw_sql(self):
        repo_dir = Path(self.tmpdir) / "test_repo6"
        repo_dir.mkdir()
        (repo_dir / "service.py").write_text(
            "def get_users(db):\n"
            '    result = db.execute("SELECT id, name FROM users WHERE active = 1")\n'
            "    return result\n"
        )

        results = self.analyzer.analyze(repo_dir)
        qp = [r for r in results if r.doc_type == "query_pattern"]
        assert len(qp) == 1
        assert "users" in qp[0].tables

    def test_extract_query_patterns_orm_chain(self):
        repo_dir = Path(self.tmpdir) / "test_repo7"
        repo_dir.mkdir()
        (repo_dir / "repo.py").write_text(
            "def find_active(session):\n"
            "    return session.query(User).filter(User.active == True).all()\n"
        )

        results = self.analyzer.analyze(repo_dir)
        qp = [r for r in results if r.doc_type == "query_pattern"]
        assert len(qp) == 1
        assert "filter" in qp[0].content

    def test_analyze_filters_extensionless_binary_from_changed_files(self):
        """Binary files without extensions (e.g. ELF executables) passed via
        the ``files`` argument from git diff should be excluded by extension
        filtering before even reaching is_binary_file().
        """
        repo_dir = Path(self.tmpdir) / "test_binary_filter"
        repo_dir.mkdir()
        (repo_dir / "docker").mkdir()
        binary_file = repo_dir / "docker" / "myBinary"
        binary_file.write_bytes(b"\x7fELF\x00\x00\x00\x00" + b"\x00" * 8000)
        (repo_dir / "models.py").write_text(
            "from sqlalchemy import Column, Integer\n"
            "class User:\n    id = Column(Integer)\n"
        )

        results = self.analyzer.analyze(
            repo_dir, files=["docker/myBinary", "models.py"]
        )
        paths = [r.file_path for r in results]
        assert "docker/myBinary" not in paths
        assert "models.py" in paths

    def test_analyze_skips_content_with_null_bytes(self):
        """Even if a file has a valid extension, null bytes in its content
        should cause it to be skipped (defense-in-depth after read_text).
        """
        repo_dir = Path(self.tmpdir) / "test_null_bytes"
        repo_dir.mkdir()
        trick_file = repo_dir / "sneaky.py"
        trick_file.write_bytes(
            b"from sqlalchemy import Column\x00\x00\x00class Foo: pass\n"
        )

        results = self.analyzer.analyze(repo_dir, files=["sneaky.py"])
        assert len(results) == 0

    def test_analyze_allows_extra_dirs_from_profile(self):
        """Files in model_dirs with valid text content should still be analyzed
        even if their extension isn't in DB_RELEVANT_EXTENSIONS.
        """
        from app.knowledge.project_profiler import ProjectProfile

        repo_dir = Path(self.tmpdir) / "test_extra_dirs"
        repo_dir.mkdir()
        (repo_dir / "custom_models").mkdir()
        model_file = repo_dir / "custom_models" / "schema.txt"
        model_file.write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);\n"
        )

        profile = ProjectProfile(model_dirs=["custom_models"])
        results = self.analyzer.analyze(
            repo_dir,
            files=["custom_models/schema.txt"],
            profile=profile,
        )
        assert len(results) == 0
