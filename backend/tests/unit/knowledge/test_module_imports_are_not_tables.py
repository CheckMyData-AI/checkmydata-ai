"""A name nothing reads and nothing writes is not a table.

Measured on production 2026-09-08: the code↔DB map for the one real customer carried
`axios`, `vue`, `library`, `change`, `const`, `export` and `import` as tables. All of
them reached it the same way — `TABLE_REF_SQL` is

    \\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\\s+[`"\\[]?(\\w+)[`"\\]]?      (IGNORECASE)

and an ES-module statement contains the word `from` followed by a double-quoted
specifier. Confirmed against the shipped regex, not inferred:

    import axios from "axios";        -> hits ['axios']   plausible ['axios']
    import { ref } from "vue";        -> hits ['vue']     plausible ['vue']
    export { x } from "library";      -> hits ['library'] plausible ['library']

`is_plausible_table_name` cannot help here and should not be asked to: `axios`, `vue`
and `library` are perfectly plausible table names. They are wrong because of *where they
came from*, which is a question about the statement, not about the word.

**The first hypothesis was wrong, and the record is kept because the correction is the
point.** Gating on ES-module statements looked right against the raw regex — and would
have changed nothing, because `_strip_sql_noise` already blanks string literals that do
not look like SQL, so `"axios"` never reaches `TABLE_REF_SQL` in the pipeline. The tests
below for import statements pass on the code as it was; they are characterisation, not
regression.

What the production rows actually showed: every phantom had `entity_name=NULL`,
`entity_file_path=NULL`, `read_count=0`, `write_count=0` and `used_in_files_json='[]'`.
No evidence from either side. `_scan_table_usage` called `setdefault` to create the usage
row and only afterwards decided whether the segment was a read or a write, so a match in
a segment that was neither registered a table nothing does anything to.

So the gate is on **evidence**: no read and no write, no entry. That rule survives being
wrong about which regex, which language and which quote style produced the name — which,
given the above, is the property that mattered.
"""

from __future__ import annotations

import pytest

from app.knowledge.entity_extractor import ProjectKnowledge, _scan_table_usage


def _tables(content: str, rel_path: str = "resources/js/app.ts") -> set[str]:
    k = ProjectKnowledge()
    _scan_table_usage(rel_path, content, k)
    return set(k.table_usage)


class TestModuleSpecifiersAreNotTables:
    @pytest.mark.parametrize(
        "line,ghost",
        [
            ('import axios from "axios";', "axios"),
            ('import { ref, computed } from "vue";', "vue"),
            ('export { helper } from "library";', "library"),
            ('import type { Change } from "change";', "change"),
            ('import defaultExport, { named } from "sessions";', "sessions"),
            ('export * from "workspaces";', "workspaces"),
        ],
    )
    def test_an_es_module_statement_yields_no_table(self, line: str, ghost: str) -> None:
        assert ghost not in _tables(line), (
            f"`{ghost}` was read as a database table out of a module import; this is how "
            "the customer's code↔DB map came to contain `axios` and `vue`"
        )

    def test_single_quoted_specifiers_too(self) -> None:
        """The shipped regex happens not to match a single-quoted specifier today —
        its optional-quote class covers backtick, double quote and bracket but not the
        apostrophe. That is an accident of the character class, not a decision, so the
        gate covers both and stops the next quote style from reopening this."""
        assert "lodash" not in _tables("import _ from 'lodash';")


class TestRealSqlStillReadsAsSql:
    """The gate must be narrow. Everything here worked before and must keep working —
    otherwise the fix trades false tables for missing ones, which is worse: a missing
    table is a silent hole in the map, and the map is what the agent reasons over."""

    def test_select_from(self) -> None:
        assert "users" in _tables('await db.query("SELECT * FROM users WHERE id = 1")')

    def test_insert_into(self) -> None:
        assert "sessions" in _tables('db.exec("INSERT INTO sessions (id) VALUES (1)")')

    def test_join(self) -> None:
        found = _tables('$sql = "SELECT * FROM orders JOIN customers ON x = y";', "app/Repo.php")
        assert {"orders", "customers"} <= found

    def test_update(self) -> None:
        assert "accounts" in _tables('run("UPDATE accounts SET balance = 0")')

    def test_sql_in_a_file_that_also_imports(self) -> None:
        """The realistic case, and the reason the gate is per-statement: a TypeScript
        module that imports a driver and then writes SQL. The import must be ignored and
        the SQL must not be."""
        src = "\n".join(
            [
                'import { Pool } from "pg";',
                'import axios from "axios";',
                'const rows = await pool.query("SELECT id FROM invoices");',
            ]
        )
        found = _tables(src)
        assert "invoices" in found, "real SQL in the same file was lost"
        assert "pg" not in found and "axios" not in found


class TestEvidenceIsRequired:
    """The rule that actually shipped."""

    def test_a_reference_with_neither_read_nor_write_is_dropped(self) -> None:
        # `CREATE TABLE` is neither a read nor a write of rows, so a bare DDL-ish
        # fragment leaves no usage behind. Before the gate this registered a table with
        # empty readers and writers.
        assert _tables("TABLE library") == set()

    def test_a_read_is_evidence(self) -> None:
        assert "invoices" in _tables('q("SELECT id FROM invoices")')

    def test_a_write_is_evidence(self) -> None:
        assert "invoices" in _tables('q("INSERT INTO invoices (id) VALUES (1)")')

    def test_the_dropped_name_leaves_no_partial_row(self) -> None:
        """Not merely absent from the count — absent from the structure. A usage row
        with empty readers and writers is what became a `db_only` claim downstream."""
        k = ProjectKnowledge()
        _scan_table_usage("resources/js/app.ts", "TABLE vue", k)
        assert k.table_usage == {}
