"""Nothing calls a class, so anchoring on one walks an empty set.

`graph_db_bridge` answers "who uses this model" by walking CALLS edges backwards from
the entity's symbol. It resolved that symbol by `(entity.name, entity.file_path)`,
which for `class CatalogPhoneNumber` finds the **class** — and a call resolves to the
METHOD being called, never to the class that owns it.

Measured in production on 2026-08-30, after call extraction was repaired and the graph
had grown from 2 134 edges to 50 379:

    CALLS edges pointing at a class symbol       0
    CALLS edges pointing at a method/function   45 832
    model classes 26, with any inbound edge      0

    graph_db_bridge: "Attached 0 caller refs across 179 entities"

The zero was not caused by a thin call graph and would have survived a perfect one.
That is worth stating because the thin graph was the obvious suspect and was fixed
first: `code_graph_edges` went 2 134 -> 50 379 and `caller_refs` stayed at 0, which is
what proved the two were unrelated.

"Who uses this model" means who calls any of its methods, so the class's members belong
in the anchor set.
"""

from __future__ import annotations

import pytest

from app.knowledge import code_graph as cg
from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge
from app.knowledge.graph_db_bridge import GraphDBBridge


def _sym(uid, name, kind, file_path, parent_uid=None):
    return cg.Symbol(
        uid=uid,
        name=name,
        kind=kind,
        file_path=file_path,
        start_line=1,
        end_line=2,
        parent_uid=parent_uid,
    )


@pytest.fixture
def graph_with_a_model_and_a_caller():
    """`OrderService::refund` calls `CatalogPhoneNumber::findForUser`.

    The edge lands on the METHOD, which is the whole point of this file.
    """
    model = _sym("m:cls", "CatalogPhoneNumber", "class", "app/Models/CatalogPhoneNumber.php")
    model_method = _sym(
        "m:findForUser",
        "findForUser",
        "method",
        "app/Models/CatalogPhoneNumber.php",
        parent_uid="m:cls",
    )
    caller_cls = _sym("s:cls", "OrderService", "class", "app/Services/OrderService.php")
    caller = _sym(
        "s:refund", "refund", "method", "app/Services/OrderService.php", parent_uid="s:cls"
    )
    return cg.CodeGraph(
        symbols=[model, model_method, caller_cls, caller],
        edges=[
            cg.GraphEdge(
                src_uid="s:refund",
                dst_uid="m:findForUser",
                edge_type=cg.EDGE_CALLS,
                confidence=1.0,
            )
        ],
    )


def _knowledge() -> ProjectKnowledge:
    k = ProjectKnowledge()
    k.entities["CatalogPhoneNumber"] = EntityInfo(
        name="CatalogPhoneNumber",
        file_path="app/Models/CatalogPhoneNumber.php",
        table_name="catalog_phone_numbers",
    )
    return k


def test_a_caller_of_a_model_method_is_attached(graph_with_a_model_and_a_caller) -> None:
    """The regression, stated as the thing the product sells: the model is used by
    something, and the map must say by what."""
    knowledge = _knowledge()
    attached = GraphDBBridge().enrich(knowledge, graph_with_a_model_and_a_caller)
    assert attached > 0, (
        "no caller attached — the anchor set is the class again, and nothing calls a class"
    )
    callers = knowledge.entities["CatalogPhoneNumber"].graph_callers
    assert any("refund" in str(c) for c in callers), callers


def test_the_class_itself_is_still_an_anchor(graph_with_a_model_and_a_caller) -> None:
    """Adding methods must not remove the class: some graphs do connect to a class,
    through EXTENDS, and that path still has to resolve."""
    bridge = GraphDBBridge()
    entity = _knowledge().entities["CatalogPhoneNumber"]
    index: dict = {}
    for sym in graph_with_a_model_and_a_caller.symbols.values():
        index.setdefault((sym.name, sym.file_path), []).append(sym)
    anchors = bridge._resolve_entity_symbols(entity, graph_with_a_model_and_a_caller, index)
    kinds = {a.uid for a in anchors}
    assert "m:cls" in kinds, "the class dropped out of the anchor set"
    assert "m:findForUser" in kinds, "the class's method is not in the anchor set"


def test_a_method_of_a_different_class_is_not_swept_in(graph_with_a_model_and_a_caller) -> None:
    """The anchor set widens by parent_uid, not by file — two classes can share a file,
    and attributing one's callers to the other is a wrong answer rather than a gap."""
    bridge = GraphDBBridge()
    entity = _knowledge().entities["CatalogPhoneNumber"]
    index: dict = {}
    for sym in graph_with_a_model_and_a_caller.symbols.values():
        index.setdefault((sym.name, sym.file_path), []).append(sym)
    anchors = bridge._resolve_entity_symbols(entity, graph_with_a_model_and_a_caller, index)
    assert "s:refund" not in {a.uid for a in anchors}
