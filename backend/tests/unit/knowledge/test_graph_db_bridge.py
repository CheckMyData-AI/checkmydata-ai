# backend/tests/unit/knowledge/test_graph_db_bridge.py
from app.knowledge.graph_db_bridge import classify_op_kind


class _Sym:
    name = "process_report"
    decorators = ()


def test_ambiguous_verbs_classified_unknown():
    assert classify_op_kind(_Sym()) == "unknown"


def test_handle_verb_classified_unknown():
    class S:
        name = "handle_payment"
        decorators = ()

    assert classify_op_kind(S()) == "unknown"


def test_sync_verb_classified_unknown():
    class S:
        name = "sync_data"
        decorators = ()

    assert classify_op_kind(S()) == "unknown"


def test_create_still_write():
    class S:
        name = "create_user"
        decorators = ()

    assert classify_op_kind(S()) == "write"


def test_get_still_read():
    class S:
        name = "get_users"
        decorators = ()

    assert classify_op_kind(S()) == "read"
