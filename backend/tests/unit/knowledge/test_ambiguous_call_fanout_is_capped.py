"""A name that matches everything resolves nothing, and must not say otherwise.

`_resolve_call` fell back to a global name match and emitted **one edge per candidate**
with no bound. That was harmless for as long as PHP calls were not extracted at all —
there was nothing to resolve. The moment #245 made them extractable, `graph_build` went
from **22 seconds to over 40 minutes without finishing**, and wrote no edges.

The distribution explains it exactly. Measured on the one real customer repository,
25 496 symbols across 12 433 distinct names:

    unique (1 symbol)   10 700   86 %
    2-8                  1 603   13 %
    9-50                   113
    >50                     17

    __construct x4361   execute x1117   up x513   down x506   handle x438

One `new Foo()` would emit 4 361 edges at confidence 0.3, and a Laravel codebase has
thousands of such call sites.

Eight is taken from that table rather than chosen: it leaves 99 % of names fully
resolvable and cuts exactly the 130 that cannot be resolved by name at all. Past the
cap the resolver returns **nothing** — an edge is read downstream as a signal, and
4 361 of them saying "it might be any of these" is worse than one honest silence.
"""

from __future__ import annotations

import pytest

from app.knowledge import code_graph as cg


def _symbol(uid: str, name: str, file_path: str = "a.php"):
    return cg.Symbol(
        uid=uid,
        name=name,
        kind="method",
        file_path=file_path,
        start_line=1,
        end_line=2,
    )


def _resolve(builder, callee: str, *, file_local=None, global_index=None):
    return builder._resolve_call(
        call_callee=callee,
        call_target=None,
        caller_uid="caller",
        file_local=file_local or {},
        import_map={},
        global_index=global_index or {},
        symbols_by_uid={},
    )


@pytest.fixture
def builder():
    return cg.CodeGraphBuilder()


class TestTheCapIsTakenFromTheDistribution:
    def test_the_bound_is_eight(self) -> None:
        """Not a round number for its own sake: 86 % of names in the measured repository
        are unique and 13 % have 2-8 candidates, so eight is where name matching stops
        being a resolution and becomes a listing."""
        assert cg._MAX_AMBIGUOUS_TARGETS == 8

    def test_a_unique_name_still_resolves_exactly(self, builder) -> None:
        """The cap must not touch the 86 % that were never the problem."""
        out = _resolve(
            builder,
            "veryUniqueName",
            global_index={"veryUniqueName": [_symbol("u1", "veryUniqueName")]},
        )
        assert [uid for uid, _ in out] == ["u1"]

    def test_a_small_ambiguity_is_still_reported(self, builder) -> None:
        """Two or three candidates is a real answer with a caveat, which is what the
        confidence score is for."""
        syms = [_symbol(f"s{i}", "handleThing") for i in range(3)]
        out = _resolve(builder, "handleThing", global_index={"handleThing": syms})
        assert len(out) == 3
        assert all(conf == cg._CONF_NAME_ONLY for _, conf in out)

    def test_exactly_at_the_cap_is_kept(self, builder) -> None:
        syms = [_symbol(f"s{i}", "atCap") for i in range(cg._MAX_AMBIGUOUS_TARGETS)]
        out = _resolve(builder, "atCap", global_index={"atCap": syms})
        assert len(out) == cg._MAX_AMBIGUOUS_TARGETS

    def test_one_past_the_cap_yields_nothing(self, builder) -> None:
        syms = [_symbol(f"s{i}", "overCap") for i in range(cg._MAX_AMBIGUOUS_TARGETS + 1)]
        out = _resolve(builder, "overCap", global_index={"overCap": syms})
        assert out == [], "past the cap the resolver must be silent, not verbose"

    def test_the_real_worst_case_yields_nothing(self, builder) -> None:
        """`__construct` is defined 4 361 times in the measured repository. Uncapped,
        one call site emitted 4 361 edges."""
        syms = [_symbol(f"c{i}", "__construct") for i in range(4361)]
        out = _resolve(builder, "__construct", global_index={"__construct": syms})
        assert out == []

    def test_the_local_scope_fan_out_is_capped_too(self, builder) -> None:
        """Same shape, same failure, one branch earlier — and it returns before the
        global branch is reached, so capping only the global one would leave it open."""
        syms = [_symbol(f"l{i}", "dup") for i in range(cg._MAX_AMBIGUOUS_TARGETS + 1)]
        out = _resolve(builder, "dup", file_local={"dup": syms})
        assert out == []
