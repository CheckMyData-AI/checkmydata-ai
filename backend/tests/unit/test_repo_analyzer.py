import tempfile
from pathlib import Path

from app.knowledge.repo_analyzer import RepoAnalyzer


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
        mig_file.write_text(
            "def upgrade():\n"
            "    op.create_table('users', ...)\n"
        )

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
            'def get_users(db):\n'
            '    result = db.execute("SELECT id, name FROM users WHERE active = 1")\n'
            '    return result\n'
        )

        results = self.analyzer.analyze(repo_dir)
        qp = [r for r in results if r.doc_type == "query_pattern"]
        assert len(qp) == 1
        assert "users" in qp[0].tables

    def test_extract_query_patterns_orm_chain(self):
        repo_dir = Path(self.tmpdir) / "test_repo7"
        repo_dir.mkdir()
        (repo_dir / "repo.py").write_text(
            'def find_active(session):\n'
            '    return session.query(User).filter(User.active == True).all()\n'
        )

        results = self.analyzer.analyze(repo_dir)
        qp = [r for r in results if r.doc_type == "query_pattern"]
        assert len(qp) == 1
        assert "filter" in qp[0].content
