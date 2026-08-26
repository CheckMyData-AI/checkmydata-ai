"""A migration states its table. That is a fact, not an inference.

The code↔DB link infers a table from a class name, because Laravel, Rails and Django all
name tables implicitly — `class User` means `users`. Inference is the right default and it
is also where the noise came from: pluralising short or generated class names produced
twelve invented tables in production.

Migrations do not need inferring. `Schema::create('users', …)`,
`create_table :users`, `CREATE TABLE users` — every framework's migrations name the table
in the source. For the one real customer repository (Laravel) that turns a guess into a
reading, for every table the application has ever created.

Measured before this existed: **`ORM_PATTERNS` had no Laravel entry at all.** A PHP file
reached the ORM branch only by accident — the `sqlalchemy` pattern matches the bare word
`Column` or `ForeignKey` anywhere in a file — and then every `class \\w+` in it became a
"model". `_extract_model_names` for non-Python files is `re.compile(r"class\\s+(\\w+)")`,
which in a generated file such as Laravel's `_ide_helper.php` is hundreds of classes.

`project_profiler` has been finding `migration_dirs` since it was written
(`project_profiler.py:201`); nothing read them for table names.
"""

from __future__ import annotations

import pytest

from app.knowledge.repo_analyzer import (
    ELOQUENT_TABLE_PROPERTY,
    MIGRATION_TABLE_PATTERNS,
    tables_declared_in_migration,
)


class TestLaravel:
    def test_schema_create_names_the_table(self) -> None:
        src = """
        <?php
        use Illuminate\\Database\\Migrations\\Migration;
        return new class extends Migration {
            public function up(): void {
                Schema::create('catalog_phone_numbers', function (Blueprint $table) {
                    $table->id();
                });
            }
        };
        """
        assert tables_declared_in_migration(src) == ["catalog_phone_numbers"]

    def test_schema_table_alters_a_known_table(self) -> None:
        src = "Schema::table('purchases', function (Blueprint $table) { $table->string('sku'); });"
        assert tables_declared_in_migration(src) == ["purchases"]

    def test_double_quotes_and_whitespace(self) -> None:
        src = 'Schema::create(  "unlimit_wallets" , function ($t) {} );'
        assert tables_declared_in_migration(src) == ["unlimit_wallets"]

    def test_several_tables_in_one_migration_keep_source_order(self) -> None:
        src = """
        Schema::create('orders', fn($t) => null);
        Schema::create('order_items', fn($t) => null);
        Schema::table('orders', fn($t) => null);
        """
        assert tables_declared_in_migration(src) == ["orders", "order_items"]

    def test_a_connection_qualified_call_still_yields_the_table(self) -> None:
        src = "Schema::connection('mysql')->create('sentry_samplers', fn($t) => null);"
        assert tables_declared_in_migration(src) == ["sentry_samplers"]


class TestOtherFrameworks:
    def test_rails(self) -> None:
        assert tables_declared_in_migration("create_table :users do |t|") == ["users"]
        assert tables_declared_in_migration('create_table "posts" do |t|') == ["posts"]

    def test_django(self) -> None:
        src = 'migrations.CreateModel(name="UserProfile", fields=[])'
        assert tables_declared_in_migration(src) == ["user_profiles"]

    def test_raw_sql(self) -> None:
        for src, want in (
            ("CREATE TABLE users (id INT);", ["users"]),
            ("create table if not exists `audit_logs` (id int);", ["audit_logs"]),
            ('CREATE TABLE IF NOT EXISTS "kv_store" (k text);', ["kv_store"]),
        ):
            assert tables_declared_in_migration(src) == want, src

    def test_alembic(self) -> None:
        src = 'op.create_table("indexing_runs", sa.Column("id", sa.String()))'
        assert tables_declared_in_migration(src) == ["indexing_runs"]


class TestItRefusesTheNoiseTheInferenceProduced:
    """A declaration is authoritative, which makes a false one worse than a false guess.
    The shape test applies here too."""

    @pytest.mark.parametrize(
        "src",
        [
            "Schema::create('the', fn($t) => null);",
            "CREATE TABLE if (x int);",
            "create_table :a do |t|",
            "op.create_table('zes')",
        ],
    )
    def test_an_implausible_declaration_is_dropped(self, src: str) -> None:
        assert tables_declared_in_migration(src) == []

    def test_a_file_with_no_migration_yields_nothing(self) -> None:
        assert tables_declared_in_migration("class User extends Model {}") == []
        assert tables_declared_in_migration("") == []


class TestEloquentDeclaresItsTableExplicitly:
    """`protected $table` is the one place a Laravel model states the name. It outranks
    the pluralised class name, and nothing read it before."""

    def test_the_property_is_found(self) -> None:
        src = "class Wallet extends Model { protected $table = 'unlimit_wallets'; }"
        assert ELOQUENT_TABLE_PROPERTY.findall(src) == ["unlimit_wallets"]

    def test_double_quotes(self) -> None:
        src = 'class X extends Model { protected $table = "catalog_phone_numbers"; }'
        assert ELOQUENT_TABLE_PROPERTY.findall(src) == ["catalog_phone_numbers"]

    def test_absent_when_the_model_relies_on_convention(self) -> None:
        assert ELOQUENT_TABLE_PROPERTY.findall("class User extends Model {}") == []


def test_every_pattern_is_anchored_on_a_declaration_keyword() -> None:
    """A pattern loose enough to match prose would make migrations a second noise source
    — and this one carries more authority than the inference it replaces."""
    assert MIGRATION_TABLE_PATTERNS
    for pattern in MIGRATION_TABLE_PATTERNS:
        # Token-wise, not phrase-wise: the raw-DDL pattern separates the words with
        # `\\s+`, so `"create table"` as a substring is absent from a pattern that is
        # anchored on exactly those two keywords.
        lowered = pattern.pattern.lower()
        assert any(kw in lowered for kw in ("schema", "create_table", "createmodel")) or (
            "create" in lowered and "table" in lowered
        ), pattern.pattern
