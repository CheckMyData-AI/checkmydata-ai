"""Every node name in the grammar table must exist in the grammar it names.

`GRAMMARS` in `ast_parser.py` is a list of tree-sitter node type names, written by
hand. A name that does not exist matches nothing — tree-sitter does not complain, the
parse succeeds, and the file yields fewer symbols or no calls at all. There is no error
anywhere; the graph is simply thinner than it should be, which looks like a property of
the codebase rather than a typo.

Measured in production on 2026-08-30, on the one real customer repository (Laravel PHP,
9 981 files):

    symbols          25 496
    edges             2 134   (EXTENDS 1 110, CALLS 1 024, IMPORTS 0)
    symbols with any outgoing edge   1 161  =  4.6%

    php   25 244 symbols → 1 103 with an edge   (4.4%)
    js       252 symbols →    58 with an edge   (23%)

The language the resolver was actually written for got a graph five times denser, on a
repository that is 99 % PHP. Three causes, and this file covers the first:

1. `method_call_expression` **does not exist** in tree-sitter-php. The real name is
   `member_call_expression`. And `scoped_call_expression` — `Model::method()`, which is
   most of Laravel — was never declared. A four-call sample file yielded `call_sites: []`.
2. PHP imports parse to `source_module='use App\\Models\\Purchase;'` — the whole
   statement, `use` and semicolon included — with `imported_names=()`. `_resolve_imports`
   needs a non-empty name list, so no PHP import can produce an edge, which is why
   production holds 28 033 parsed imports and 0 IMPORTS edges.
3. `_candidate_module_paths` handles Python dotted modules and relative JS paths and
   nothing else, so even a clean `App\\Models\\Purchase` maps to no candidate file.

**2 and 3 are NOT fixed here.** They are a second change: this one restores call
extraction, which is measurable on its own, and mixing the two would make neither
attributable. Recorded on the board rather than left in a comment.

`ruby` is here for the same reason and was found by the same check: its `call_nodes` is
empty, so a Ruby repository yields zero call edges and always has.
"""

from __future__ import annotations

import pytest

import app.knowledge.ast_parser as ap

try:
    from tree_sitter_language_pack import get_language
except Exception:  # pragma: no cover - the pack is a hard dependency of ast_parser
    get_language = None  # type: ignore[assignment]

#: Every attribute on `LanguageGrammar` that names tree-sitter node types.
NODE_ATTRS = (
    "function_nodes",
    "method_nodes",
    "class_nodes",
    "interface_nodes",
    "enum_nodes",
    "import_nodes",
    "call_nodes",
)


def _table() -> list:
    for value in vars(ap).values():
        if isinstance(value, (list, tuple)) and value and hasattr(value[0], "slug"):
            return list(value)
    raise AssertionError("no grammar table found in ast_parser")


def _real_node_types(slug: str) -> set[str] | None:
    """Every node kind the installed grammar actually defines, or None if absent."""
    if get_language is None:
        return None
    try:
        lang = get_language(slug)
    except Exception:
        return None
    return {lang.node_kind_for_id(i) for i in range(lang.node_kind_count)}


TABLE = _table()
SLUGS = [g.slug for g in TABLE]


@pytest.mark.parametrize("grammar", TABLE, ids=SLUGS)
def test_every_declared_node_type_exists(grammar) -> None:
    """A misspelled node name is silent. This is the only thing that makes it loud."""
    real = _real_node_types(grammar.slug)
    if real is None:
        pytest.skip(f"grammar {grammar.slug!r} not installed")
    declared: set[str] = set()
    for attr in NODE_ATTRS:
        declared |= set(getattr(grammar, attr, ()) or ())
    missing = sorted(n for n in declared if n not in real)
    assert not missing, (
        f"{grammar.slug}: declared node types that do not exist in the grammar and "
        f"therefore match nothing: {missing}"
    )


class TestCallNodesCoverTheFormsTheLanguageActuallyUses:
    """The wrong-name check above cannot see an OMISSION, and the omission was the
    larger half: `scoped_call_expression` was not misspelled, it was absent, and it is
    three calls in four in Laravel."""

    #: What each language's call sites actually look like, asserted by name because a
    #: heuristic over node names ("anything ending in _call") also matches C#'s calling
    #: conventions (`Fastcall`, `Stdcall`), which are keywords rather than call sites.
    REQUIRED: dict[str, tuple[str, ...]] = {
        "php": (
            "function_call_expression",  # foo()
            "member_call_expression",  # $obj->method()
            "scoped_call_expression",  # Model::method()  — most of Laravel
            "nullsafe_member_call_expression",  # $obj?->method()
        ),
        "python": ("call",),
        "javascript": ("call_expression",),
        "typescript": ("call_expression",),
        "ruby": ("call",),
        "go": ("call_expression",),
        "java": ("method_invocation",),
    }

    @pytest.mark.parametrize("slug", sorted(REQUIRED))
    def test_the_forms_are_declared(self, slug: str) -> None:
        grammar = next((g for g in TABLE if g.slug == slug), None)
        if grammar is None:
            pytest.skip(f"{slug} is not in the grammar table")
        real = _real_node_types(slug)
        if real is None:
            pytest.skip(f"grammar {slug!r} not installed")
        declared = set(grammar.call_nodes or ())
        # Only require forms this installed grammar actually has — a grammar version
        # bump that renames one should fail the check above, not silently here.
        expected = {n for n in self.REQUIRED[slug] if n in real}
        missing = sorted(expected - declared)
        assert not missing, (
            f"{slug}: these call forms exist in the grammar and are not declared, so "
            f"every call written that way is invisible to the graph: {missing}"
        )

    def test_no_language_has_an_empty_call_node_list(self) -> None:
        """`ruby` had one. A language in the table with no call nodes yields symbols and
        no call edges at all, which reads as "that repository has few calls"."""
        empty = sorted(g.slug for g in TABLE if not (g.call_nodes or ()))
        assert not empty, (
            f"these languages extract no call sites at all: {empty} — a repository in "
            "one of them gets symbols and an empty call graph"
        )


def test_the_php_sample_that_produced_nothing_now_produces_calls(tmp_path) -> None:
    """The regression, as a file rather than a description.

    Four calls, three of them the forms Laravel is written in. Before the fix this
    returned `call_sites: []`, and that emptiness was indistinguishable from a file
    with no calls in it.
    """
    src = """<?php
namespace App\\Services;

use App\\Models\\Purchase;

class OrderService extends BaseService
{
    public function refund(int $userId): bool
    {
        $purchase = Purchase::findForUser($userId);
        $this->audit($purchase);
        return RefundRequest::create(['id' => $purchase->id]) !== null;
    }

    private function audit($purchase): void
    {
        Logger::write('refund', $purchase);
    }
}
"""
    (tmp_path / "Order.php").write_text(src, encoding="utf-8")
    parsed = ap.ASTParser().parse_file(tmp_path, "Order.php")
    assert parsed is not None and parsed.language == "php"
    callees = {c.callee_name for c in parsed.call_sites}
    assert {"findForUser", "audit", "create", "write"} <= callees, (
        f"expected the four calls, got {sorted(callees)}"
    )
