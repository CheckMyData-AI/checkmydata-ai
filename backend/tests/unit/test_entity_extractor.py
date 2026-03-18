import tempfile
from pathlib import Path

from app.knowledge.entity_extractor import (
    ConfigRef,
    ProjectKnowledge,
    ValidationRule,
    _extract_columns,
    build_project_knowledge,
)
from app.knowledge.repo_analyzer import ExtractedSchema


class TestExtractColumns:
    def test_sqlalchemy_columns(self):
        content = (
            "class User(Base):\n"
            "    __tablename__ = 'users'\n"
            "    id: Mapped[int] = mapped_column(Integer, primary_key=True)\n"
            "    name: Mapped[str] = mapped_column(String(255))\n"
            "    email: Mapped[str] = mapped_column(String(255), unique=True)\n"
        )
        cols = _extract_columns(content, "models/user.py")
        names = [c.name for c in cols]
        assert "id" in names
        assert "name" in names
        assert "email" in names

    def test_django_fields(self):
        content = (
            "class Product(models.Model):\n"
            "    title = models.CharField(max_length=200)\n"
            "    price = models.DecimalField(max_digits=10)\n"
            "    is_active = models.BooleanField(default=True)\n"
        )
        cols = _extract_columns(content, "models.py")
        names = [c.name for c in cols]
        assert "title" in names
        assert "price" in names
        assert "is_active" in names

    def test_prisma_fields(self):
        content = (
            "model User {\n"
            "  id    Int     @id @default(autoincrement())\n"
            "  email String  @unique\n"
            "  name  String\n"
            "  posts Post[]  @relation\n"
            "}\n"
        )
        cols = _extract_columns(content, "schema.prisma")
        names = [c.name for c in cols]
        assert "id" in names
        assert "email" in names
        assert "name" in names
        assert "posts" in names

    def test_typeorm_columns(self):
        content = (
            "import { Entity, Column, PrimaryGeneratedColumn, ManyToOne } from 'typeorm';\n"
            "\n"
            "@Entity()\n"
            "export class User {\n"
            "  @PrimaryGeneratedColumn()\n"
            "  id: number;\n"
            "\n"
            "  @Column({ type: 'varchar' })\n"
            "  name: string;\n"
            "\n"
            "  @ManyToOne(() => Company)\n"
            "  company: Company;\n"
            "}\n"
        )
        cols = _extract_columns(content, "user.entity.ts")
        types = {c.name: c.col_type for c in cols if c.name}
        assert "varchar" in types.values() or any("varchar" in t for t in types.values())

    def test_sequelize_columns(self):
        content = (
            "const User = sequelize.define('User', {\n"
            "  name: {\n"
            "    type: DataTypes.STRING,\n"
            "    allowNull: false,\n"
            "  },\n"
            "  age: DataTypes.INTEGER,\n"
            "});\n"
        )
        cols = _extract_columns(content, "models/user.js")
        names = [c.name for c in cols]
        assert "name" in names
        assert "age" in names

    def test_mongoose_fields(self):
        content = (
            "const userSchema = new Schema({\n"
            "  name: { type: String, required: true },\n"
            "  email: String,\n"
            "  age: Number,\n"
            "});\n"
        )
        cols = _extract_columns(content, "models/user.js")
        names = [c.name for c in cols]
        assert "name" in names
        assert "email" in names
        assert "age" in names

    def test_drizzle_columns(self):
        content = (
            "export const users = pgTable('users', {\n"
            "  id: serial('id').primaryKey(),\n"
            "  name: varchar('name', { length: 255 }),\n"
            "  age: integer('age'),\n"
            "});\n"
        )
        cols = _extract_columns(content, "schema.ts")
        names = [c.name for c in cols]
        assert "id" in names
        assert "name" in names
        assert "age" in names

    def test_empty_python_file(self):
        cols = _extract_columns("# just a comment", "empty.py")
        assert cols == []

    def test_gorm_columns(self):
        content = (
            "type User struct {\n"
            '    ID   uint   `gorm:"primaryKey"`\n'
            '    Name string `gorm:"column:name;size:255"`\n'
            '    Age  int    `gorm:"column:age"`\n'
            "}\n"
        )
        cols = _extract_columns(content, "models/user.go")
        names = [c.name for c in cols]
        assert "name" in names
        assert "age" in names

    def test_activerecord_fields(self):
        content = (
            "class CreateUsers < ActiveRecord::Migration[7.0]\n"
            "  def change\n"
            "    create_table :users do |t|\n"
            "      t.string :name\n"
            "      t.integer :age\n"
            "      t.references :company\n"
            "      t.timestamps\n"
            "    end\n"
            "  end\n"
            "end\n"
        )
        cols = _extract_columns(content, "db/migrate/001_create_users.rb")
        names = [c.name for c in cols]
        assert "name" in names
        assert "age" in names
        assert "company" in names

    def test_jpa_columns(self):
        content = (
            "import javax.persistence.*;\n"
            "\n"
            "@Entity\n"
            '@Table(name = "users")\n'
            "public class User {\n"
            '    @Column(name = "user_name")\n'
            "    private String userName;\n"
            "\n"
            "    @Column()\n"
            "    private Integer age;\n"
            "\n"
            "    @ManyToOne\n"
            "    private Company company;\n"
            "}\n"
        )
        cols = _extract_columns(content, "src/models/User.java")
        names = [c.name for c in cols]
        assert "user_name" in names
        assert "age" in names
        fk_cols = [c for c in cols if c.is_fk]
        assert len(fk_cols) >= 1

    def test_graphql_columns(self):
        content = "type User {\n  id: ID!\n  name: String!\n  email: String\n  posts: [Post!]!\n}\n"
        cols = _extract_columns(content, "schema.graphql")
        names = [c.name for c in cols]
        assert "id" in names
        assert "name" in names
        fk_cols = [c for c in cols if c.is_fk]
        assert len(fk_cols) >= 1

    def test_orm_scoped_extraction(self):
        """When detected_orms is provided, only matching patterns should run."""
        content = (
            "const User = sequelize.define('User', {\n"
            "  name: {\n"
            "    type: DataTypes.STRING,\n"
            "  },\n"
            "});\n"
        )
        cols_all = _extract_columns(content, "models/user.js", detected_orms=None)
        cols_seq = _extract_columns(content, "models/user.js", detected_orms=["sequelize"])
        cols_typeorm = _extract_columns(content, "models/user.js", detected_orms=["typeorm"])
        assert len(cols_seq) >= 1
        assert len(cols_all) >= 1
        assert len(cols_typeorm) == 0


class TestBuildProjectKnowledge:
    def _make_repo(self, files: dict[str, str]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        for rel_path, content in files.items():
            fp = tmp / rel_path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
        return tmp

    def test_entity_extraction(self):
        repo = self._make_repo(
            {
                "models/user.py": (
                    "from sqlalchemy.orm import Mapped, mapped_column\n"
                    "class User(Base):\n"
                    "    __tablename__ = 'users'\n"
                    "    id: Mapped[int] = mapped_column(Integer, primary_key=True)\n"
                ),
            }
        )
        schemas = [
            ExtractedSchema(
                file_path="models/user.py",
                doc_type="orm_model",
                content=repo.joinpath("models/user.py").read_text(),
                models=["User"],
            ),
        ]
        knowledge = build_project_knowledge(repo, schemas)
        assert "User" in knowledge.entities
        assert knowledge.entities["User"].table_name == "users"

    def test_dead_table_detection(self):
        repo = self._make_repo(
            {
                "migrations/001.sql": "CREATE TABLE legacy_users (id INT);",
            }
        )
        schemas = [
            ExtractedSchema(
                file_path="migrations/001.sql",
                doc_type="raw_sql",
                content="CREATE TABLE legacy_users (id INT);",
                tables=["legacy_users"],
            ),
        ]
        knowledge = build_project_knowledge(repo, schemas)
        assert "legacy_users" in knowledge.dead_tables

    def test_enum_extraction(self):
        repo = self._make_repo(
            {
                "enums.py": (
                    "from enum import Enum\n"
                    "class UserStatus(Enum):\n"
                    "    ACTIVE = 'active'\n"
                    "    INACTIVE = 'inactive'\n"
                ),
            }
        )
        knowledge = build_project_knowledge(
            repo,
            [],
            all_files=["enums.py"],
        )
        assert len(knowledge.enums) >= 1
        names = [e.name for e in knowledge.enums]
        assert "UserStatus" in names

    def test_table_usage_readers_writers(self):
        repo = self._make_repo(
            {
                "queries.py": (
                    "def get_users(db):\n"
                    "    return db.execute(text('SELECT * FROM users WHERE active = 1'))\n"
                    "\n"
                    "def add_user(db):\n"
                    "    db.execute(text('INSERT INTO users (name) VALUES (:n)'))\n"
                ),
            }
        )
        knowledge = build_project_knowledge(
            repo,
            [],
            all_files=["queries.py"],
        )
        assert "users" in knowledge.table_usage
        usage = knowledge.table_usage["users"]
        assert "queries.py" in usage.readers
        assert "queries.py" in usage.writers

    def test_service_function_extraction(self):
        repo = self._make_repo(
            {
                "models/user.py": "class User: pass\n",
                "services/user_svc.py": (
                    "def create_user(name):\n    u = User(name=name)\n    return u\n"
                ),
            }
        )
        schemas = [
            ExtractedSchema(
                file_path="models/user.py",
                doc_type="orm_model",
                content="class User: pass",
                models=["User"],
            ),
        ]
        knowledge = build_project_knowledge(
            repo,
            schemas,
            all_files=["models/user.py", "services/user_svc.py"],
        )
        func_names = [sf["name"] for sf in knowledge.service_functions]
        assert "create_user" in func_names

    def test_word_boundary_entity_detection(self):
        """Entity name 'User' should not match 'UserManager' or 'userCount'."""
        repo = self._make_repo(
            {
                "models/user.py": "class User: pass\n",
                "utils/helpers.py": ("from sqlalchemy.orm import relationship\nuserCount = 42\n"),
            }
        )
        schemas = [
            ExtractedSchema(
                file_path="models/user.py",
                doc_type="orm_model",
                content="class User: pass",
                models=["User"],
            ),
        ]
        knowledge = build_project_knowledge(
            repo,
            schemas,
            all_files=["models/user.py", "utils/helpers.py"],
        )
        entity = knowledge.entities["User"]
        assert "utils/helpers.py" not in entity.used_in_files

    def test_config_refs_extraction(self):
        repo = self._make_repo(
            {
                "config.py": (
                    "import os\n"
                    "DATABASE_URL = os.environ['DATABASE_URL']\n"
                    "DB_HOST = os.getenv('DB_HOST', 'localhost')\n"
                ),
            }
        )
        knowledge = build_project_knowledge(
            repo,
            [],
            all_files=["config.py"],
        )
        var_names = [cr.var_name for cr in knowledge.config_refs]
        assert "DATABASE_URL" in var_names
        assert "DB_HOST" in var_names

    def test_validation_rules_extraction_django(self):
        repo = self._make_repo(
            {
                "models.py": (
                    "from django.db import models\n"
                    "from django.core.validators import MinValueValidator\n"
                    "class Product(models.Model):\n"
                    "    price = models.DecimalField(validators=[MinValueValidator(0)])\n"
                ),
            }
        )
        knowledge = build_project_knowledge(
            repo,
            [],
            all_files=["models.py"],
        )
        assert len(knowledge.validation_rules) >= 1
        assert knowledge.validation_rules[0].rule_type == "validator"

    def test_validation_rules_extraction_typeorm(self):
        repo = self._make_repo(
            {
                "user.entity.ts": (
                    "@Entity()\n"
                    '@Check("age >= 0")\n'
                    "export class User {\n"
                    "  @Column()\n"
                    "  age: number;\n"
                    "}\n"
                ),
            }
        )
        knowledge = build_project_knowledge(
            repo,
            [],
            all_files=["user.entity.ts"],
        )
        checks = [vr for vr in knowledge.validation_rules if vr.rule_type == "check"]
        assert len(checks) >= 1
        assert "age >= 0" in checks[0].expression

    def test_knowledge_serialization_with_new_fields(self):
        """Round-trip serialization of config_refs and validation_rules."""
        knowledge = ProjectKnowledge()
        knowledge.config_refs.append(
            ConfigRef(var_name="DATABASE_URL", file_path="config.py", context="os.environ")
        )
        knowledge.validation_rules.append(
            ValidationRule(
                rule_type="check",
                expression="age >= 0",
                file_path="user.ts",
                model_name="User",
            )
        )
        json_str = knowledge.to_json()
        restored = ProjectKnowledge.from_json(json_str)
        assert len(restored.config_refs) == 1
        assert restored.config_refs[0].var_name == "DATABASE_URL"
        assert len(restored.validation_rules) == 1
        assert restored.validation_rules[0].expression == "age >= 0"

    def test_incremental_update_preserves_cached(self):
        repo = self._make_repo(
            {
                "models/user.py": "class User: pass\n",
                "services/auth.py": "def create_user(): pass\n",
            }
        )
        cached = ProjectKnowledge()
        cached.service_functions.append(
            {
                "name": "old_func",
                "file_path": "services/old.py",
                "tables": ["users"],
                "snippet": "...",
            }
        )
        schemas = [
            ExtractedSchema(
                file_path="models/user.py",
                doc_type="orm_model",
                content="class User: pass",
                models=["User"],
            ),
        ]
        knowledge = build_project_knowledge(
            repo,
            schemas,
            changed_files=["models/user.py"],
            cached_knowledge=cached,
        )
        func_names = [sf["name"] for sf in knowledge.service_functions]
        assert "old_func" in func_names
