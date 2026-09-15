"""A generated non-answer is a decision not to store, not a thing to store.

Measured on production 2026-09-15 (B-10), over 782 knowledge documents:

- **25** said in prose that the file had nothing to do with the database — including
  **all three** `query_pattern` documents, one of which described a translation bundle;
- **16 more** described build output, vendor code and minified assets;
- two `.gitkeep` files under `database/migrations/` were stored as **migration
  documents**, because the migration branch tested the PATH and never the content.

Each one cost an LLM call to produce, a row to hold, an embedding to index, and a
retrieval slot it could win from a document that has an answer. The last part is the
harm: a corpus is not improved by documents that say nothing, it is diluted by them.

Two defences, in this order, because the cheapest way to not store a non-answer is to
never buy it:

1. `can_carry_schema` refuses the file before extraction — by SHAPE, not by a list of
   names seen in one repository.
2. `is_non_answer` refuses the document after generation, for the file that looked
   plausible and turned out not to be.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.knowledge.doc_generator import is_non_answer
from app.knowledge.repo_analyzer import RepoAnalyzer, can_carry_schema

PIPELINE = pathlib.Path(__file__).resolve().parents[3] / "app" / "knowledge" / "pipeline_runner.py"

_A_REAL_MIGRATION = (
    'Schema::create("users", function (Blueprint $table) {\n'
    "    $table->id();\n"
    "    $table->string('email')->unique();\n"
    "});\n"
)


@pytest.mark.parametrize(
    ("path", "content"),
    [
        # The two that were stored as migration documents on production.
        ("api/database/migrations/.gitkeep", ""),
        ("sendmail/database/migrations/.gitkeep", "\n"),
        # Code the repository did not write.
        ("vendor/laravel/framework/src/Model.php", _A_REAL_MIGRATION),
        ("node_modules/pg/lib/index.js", _A_REAL_MIGRATION),
        ("frontend/dist/main.js", _A_REAL_MIGRATION),
        # Machine output by suffix…
        ("public/assets/app.min.js", _A_REAL_MIGRATION),
        ("public/assets/app.bundle.js", _A_REAL_MIGRATION),
        # …and by shape, which is how the production case was actually caught:
        # `panel/public/assets/js/vendor.js` is not named like a bundle.
        ("panel/public/assets/js/vendor.js", "!function(e){var Column=1}(" + "x" * 2500 + ");"),
    ],
)
def test_a_file_that_cannot_carry_a_schema_is_refused(path: str, content: str) -> None:
    assert can_carry_schema(path, content) is False


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("api/database/migrations/2024_10_04_create_users_table.php", _A_REAL_MIGRATION),
        ("app/Models/User.php", 'class User extends Model { protected $table = "users"; }'),
        ("backend/app/models/user.py", 'class User(Base):\n    __tablename__ = "users"\n'),
    ],
)
def test_a_file_that_can_is_not_refused(path: str, content: str) -> None:
    """The refusal must not reach the documents the corpus exists for."""
    assert can_carry_schema(path, content) is True


def test_the_extractor_asks_before_it_extracts() -> None:
    """The migration branch produces a document from the path alone, so a check that
    runs only in the other branches would leave the `.gitkeep` case exactly as it was."""
    analyzer = RepoAnalyzer(clone_base_dir="/tmp")
    assert analyzer._analyze_file("api/database/migrations/.gitkeep", "", None) == []


class TestTheDocumentSide:
    @pytest.mark.parametrize(
        "document",
        [
            "# Database Schema Analysis\n\n**No database schema found.** "
            "The analyzed file `SentrySampler.php` is not a model.",
            "# Database Schema Analysis\n\n## Overview\nThe provided source file "
            "**does not contain any database** schema definitions.",
            "## File: `auth/database/migrations/.gitkeep`\n\n**Status:** "
            "No schema or migration definitions.",
            "",
        ],
    )
    def test_a_non_answer_is_recognised(self, document: str) -> None:
        assert is_non_answer(document) is True

    def test_a_long_document_is_never_a_non_answer(self) -> None:
        """"This model does not define a table itself, it extends…" is the OPENING of a
        real answer. The length bound is what separates the two, and without it the
        phrase match would discard the documents the corpus is made of."""
        real = "# Schema\n" + (
            "This model does not define any database table itself; it extends Base "
            "and contributes the soft-delete scope used by every model below it. "
        ) * 30
        assert len(real) > 1200
        assert is_non_answer(real) is False

    def test_a_document_with_an_answer_is_kept(self) -> None:
        assert (
            is_non_answer(
                "# Schema: `users`\n\n| column | type |\n|---|---|\n| id | bigint |\n"
            )
            is False
        )


def test_every_place_that_stores_a_generated_document_asks_first() -> None:
    """Two call sites store a generated document — the batch and the retry after a
    failure — and the second was found by walking rather than by a failure. A guard on
    one of two writers is the shape this repository has been caught by before.
    """
    tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))
    storing_functions: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        body = ast.unparse(fn)
        if "_doc_store.upsert" not in body:
            continue
        storing_functions.append(fn.name)
        assert "is_non_answer" in body, (
            f"{fn.name} stores a generated document without asking whether the model "
            "answered anything"
        )
    assert storing_functions, "no function stores a document — the walker has stopped measuring"
