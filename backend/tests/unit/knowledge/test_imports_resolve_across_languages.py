"""IMPORTS edges were structurally impossible for PHP and Ruby.

`_candidate_module_paths` knew three shapes: a Python dotted module, a relative JS/TS
path, and a slash-separated path tried against `.ts/.tsx/.js/.jsx/.py`. A PHP `use`
statement carries neither a dot nor a slash, so `App\\Models\\User` fell through to the
Python branch and produced the candidate ``App\\Models\\User.py`` — a filename containing
backslashes, which exists nowhere. Ruby's `require 'foo/bar'` took the slash branch and
was tried against every extension except `.rb`.

Production recorded 28 033 imports and built **0 IMPORTS edges**. The count came from a
log line, so nothing contradicted it: the parser was finding the imports correctly and
the resolver could not turn a single one into a path.

Resolution is by path SUFFIX rather than by convention. "App\\ means app/" is PSR-4, and
PSR-4 is a claim about someone else's composer.json — the repository already knows where
its files are, so it is asked instead. Ambiguity is refused rather than fanned out; that
lesson was paid for in `_resolve_call`, where 4 361 identically-named `__construct`
symbols turned an unbounded fan-out into a `graph_build` that ran for forty minutes.
"""

from __future__ import annotations

import pytest

from app.knowledge.code_graph import _build_path_suffix_index, _resolve_module_to_file

REPO = [
    "app/Models/User.php",
    "app/Models/Purchase.php",
    "app/Http/Controllers/UserController.php",
    "vendor/laravel/framework/src/Illuminate/Support/Facades/DB.php",
    "app/Services/Billing/User.php",
    "lib/foo/bar.rb",
    "app/models/order.rb",
    "app/models/user.rb",
    "src/api/auth.ts",
    "src/api/index.ts",
    "backend/app/config.py",
    "backend/app/main.py",
]


@pytest.fixture
def index():
    return _build_path_suffix_index(REPO)


class TestPhpNamespacesResolve:
    def test_a_use_statement_reaches_the_class_file(self, index) -> None:
        got = _resolve_module_to_file(
            "App\\Models\\Purchase", "app/Http/Controllers/UserController.php", index
        )
        assert got == "app/Models/Purchase.php"

    def test_a_vendor_namespace_resolves_through_its_real_depth(self, index) -> None:
        """`Illuminate\\Support\\Facades\\DB` lives under
        vendor/laravel/framework/src/… — no convention predicts that prefix, and the
        suffix does not need to."""
        got = _resolve_module_to_file(
            "Illuminate\\Support\\Facades\\DB", "app/Models/Purchase.php", index
        )
        assert got == "vendor/laravel/framework/src/Illuminate/Support/Facades/DB.php"


class TestRubyRequiresResolve:
    def test_a_slash_require_finds_the_rb_file(self, index) -> None:
        assert _resolve_module_to_file("foo/bar", "app/models/order.rb", index) == "lib/foo/bar.rb"

    def test_a_quoted_require_is_unquoted_first(self, index) -> None:
        assert (
            _resolve_module_to_file("'foo/bar'", "app/models/order.rb", index) == "lib/foo/bar.rb"
        )


class TestTheLanguageOfTheImporterDisambiguates:
    """A polyglot repository holds `app/Models/User.php` and `app/models/user.rb`, whose
    lowercased suffixes are identical. The importing file's own extension separates
    them: a `use` statement in a .php file does not reach a .rb file."""

    def test_php_importer_gets_the_php_file(self, index) -> None:
        got = _resolve_module_to_file(
            "App\\Models\\User", "app/Http/Controllers/UserController.php", index
        )
        assert got == "app/Models/User.php"

    def test_ruby_importer_gets_the_rb_file(self, index) -> None:
        got = _resolve_module_to_file("app/models/user", "app/models/order.rb", index)
        assert got == "app/models/user.rb"


class TestAmbiguityIsRefusedRatherThanFannedOut:
    def test_a_bare_class_name_matching_two_files_resolves_to_nothing(self, index) -> None:
        """`User` matches app/Models/User.php and app/Services/Billing/User.php. Emitting
        both would put a wrong edge in the graph, and a wrong edge is worse than a
        missing one: it is believed."""
        assert _resolve_module_to_file("User", "app/Http/Controllers/X.php", index) is None

    def test_an_unknown_module_resolves_to_nothing(self, index) -> None:
        assert _resolve_module_to_file("Nonexistent\\Thing", "app/Models/User.php", index) is None


class TestTheLanguagesThatAlreadyWorkedStillWork:
    """The fix must not move Python or TypeScript, which resolved correctly before."""

    def test_python_dotted_module(self, index) -> None:
        got = _resolve_module_to_file("app.config", "backend/app/main.py", index)
        assert got == "backend/app/config.py"

    def test_relative_typescript_path(self, index) -> None:
        assert _resolve_module_to_file("./auth", "src/api/index.ts", index) == "src/api/auth.ts"


def test_the_suffix_index_holds_every_suffix_of_every_path() -> None:
    idx = _build_path_suffix_index(["a/b/c.py"])
    assert set(idx) == {"a/b/c", "b/c", "c"}
    assert idx["b/c"] == ["a/b/c.py"]


# ---------------------------------------------------------------------------
# End to end: the resolver is only worth anything if edges reach the graph
# ---------------------------------------------------------------------------


def _sym(path: str, name: str, kind: str = "class", lang: str = "php"):
    from app.knowledge.ast_parser import Symbol

    return Symbol(
        uid=f"{lang}:{path}:{kind}:{name}",
        kind=kind,
        name=name,
        file_path=path,
        start_line=1,
        end_line=10,
        language=lang,
    )


def _parsed(path: str, lang: str, symbols, imports):
    from app.knowledge.ast_parser import ParsedFile

    return ParsedFile(file_path=path, language=lang, symbols=list(symbols), imports=list(imports))


class TestTheGraphActuallyGetsImportsEdges:
    """Production recorded 28 033 imports and 0 IMPORTS edges. The unit above proves a
    module resolves to a path; this proves the path becomes an edge."""

    def test_a_php_use_statement_becomes_an_edge(self) -> None:
        from app.knowledge.ast_parser import ImportRef
        from app.knowledge.code_graph import EDGE_IMPORTS, CodeGraphBuilder

        files = {
            "app/Models/User.php": _parsed(
                "app/Models/User.php", "php", [_sym("app/Models/User.php", "User")], []
            ),
            "app/Http/Controllers/UserController.php": _parsed(
                "app/Http/Controllers/UserController.php",
                "php",
                [_sym("app/Http/Controllers/UserController.php", "UserController")],
                [ImportRef(source_module="App\\Models\\User", imported_names=("User",), line=3)],
            ),
        }
        graph = CodeGraphBuilder().build(files)
        imports = [e for e in graph.edges if e.edge_type == EDGE_IMPORTS]
        assert len(imports) == 1, f"expected one IMPORTS edge, got {imports}"
        assert imports[0].dst_uid == "php:app/Models/User.php:class:User"
        assert imports[0].src_uid == "file:app/Http/Controllers/UserController.php"

    def test_a_ruby_require_reaches_the_files_top_level_symbols(self) -> None:
        from app.knowledge.ast_parser import ImportRef
        from app.knowledge.code_graph import EDGE_IMPORTS, CodeGraphBuilder

        files = {
            "lib/foo/bar.rb": _parsed(
                "lib/foo/bar.rb", "ruby", [_sym("lib/foo/bar.rb", "Bar", lang="ruby")], []
            ),
            "app/models/order.rb": _parsed(
                "app/models/order.rb",
                "ruby",
                [_sym("app/models/order.rb", "Order", lang="ruby")],
                [ImportRef(source_module="foo/bar", line=1)],
            ),
        }
        graph = CodeGraphBuilder().build(files)
        imports = [e for e in graph.edges if e.edge_type == EDGE_IMPORTS]
        assert len(imports) == 1, f"a nameless require must still depend on something: {imports}"
        assert imports[0].dst_uid == "ruby:lib/foo/bar.rb:class:Bar"

    def test_python_imports_are_unchanged(self) -> None:
        from app.knowledge.ast_parser import ImportRef
        from app.knowledge.code_graph import EDGE_IMPORTS, CodeGraphBuilder

        files = {
            "app/config.py": _parsed(
                "app/config.py", "python", [_sym("app/config.py", "Settings", lang="python")], []
            ),
            "app/main.py": _parsed(
                "app/main.py",
                "python",
                [_sym("app/main.py", "App", lang="python")],
                [ImportRef(source_module="app.config", imported_names=("Settings",), line=1)],
            ),
        }
        graph = CodeGraphBuilder().build(files)
        imports = [e for e in graph.edges if e.edge_type == EDGE_IMPORTS]
        assert len(imports) == 1
        assert imports[0].dst_uid == "python:app/config.py:class:Settings"

    def test_a_nameless_import_cannot_fan_out_without_bound(self) -> None:
        """`graph_build` once ran for forty minutes on an unbounded fan-out. A file
        exposing thirty classes must not contribute thirty edges per importer."""
        from app.knowledge.ast_parser import ImportRef
        from app.knowledge.code_graph import _MAX_IMPORT_FANOUT, EDGE_IMPORTS, CodeGraphBuilder

        wide = [_sym("lib/wide.rb", f"C{i}", lang="ruby") for i in range(30)]
        files = {
            "lib/wide.rb": _parsed("lib/wide.rb", "ruby", wide, []),
            "app/x.rb": _parsed(
                "app/x.rb",
                "ruby",
                [_sym("app/x.rb", "X", lang="ruby")],
                [ImportRef(source_module="wide", line=1)],
            ),
        }
        graph = CodeGraphBuilder().build(files)
        imports = [e for e in graph.edges if e.edge_type == EDGE_IMPORTS]
        assert len(imports) <= _MAX_IMPORT_FANOUT, f"unbounded fan-out: {len(imports)} edges"
