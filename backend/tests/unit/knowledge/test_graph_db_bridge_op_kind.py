"""New op-kind unit tests for graph_db_bridge (W5 T9).

Tests for:
 1. Word-boundary HTTP method match — ``@budget_gettable`` must NOT be classified as GET.
 2. ``@app.get(...)`` MUST be classified as a GET (read).
 3. Name-prefix-only inference is tagged ``op_kind_confidence="low"`` via
    ``classify_op_kind_ex``.
 4. Back-compat: ``classify_op_kind`` still returns a plain ``str``.
"""

from __future__ import annotations

from app.knowledge.graph_db_bridge import (
    classify_op_kind,
    classify_op_kind_ex,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _S:
    """Minimal Symbol-like stub."""

    def __init__(self, name: str, decorators: tuple[str, ...] = ()) -> None:
        self.name = name
        self.decorators = decorators


# ---------------------------------------------------------------------------
# Word-boundary HTTP method matching
# ---------------------------------------------------------------------------


class TestWordBoundaryHTTPMatch:
    def test_budget_gettable_decorator_not_classified_as_read(self):
        """@budget_gettable contains 'get' as a substring, NOT a whole token."""
        s = _S("handle_budget", ("budget_gettable",))
        assert classify_op_kind(s) != "read"

    def test_target_decorator_not_classified_as_read(self):
        """@target contains 'get' at position 3 as a substring."""
        s = _S("run_pipeline", ("target",))
        assert classify_op_kind(s) != "read"

    def test_get_target_substring_not_read(self):
        """'get' inside a longer word like 'forget' must not trigger read."""
        s = _S("run", ("forget_cache",))
        assert classify_op_kind(s) != "read"

    def test_postmark_decorator_not_classified_as_write(self):
        """@postmark contains 'post' as substring — must NOT be classified write."""
        s = _S("send_email", ("postmark_send",))
        # Without name prefix verb this should be unknown, NOT write from
        # substring-matching 'post' in 'postmark_send'.
        result = classify_op_kind(s)
        assert result != "write"

    def test_app_get_classified_as_read(self):
        """@app.get(...) — 'get' IS a whole word token → read."""
        s = _S("get_users", ("app.get('/users')",))
        assert classify_op_kind(s) == "read"

    def test_router_get_classified_as_read(self):
        """@router.get('/users') → read."""
        s = _S("handle", ("router.get('/users')",))
        assert classify_op_kind(s) == "read"

    def test_router_post_classified_as_write(self):
        """@router.post('/users') → write (existing behaviour, not regressed)."""
        s = _S("handle", ("router.post('/users')",))
        assert classify_op_kind(s) == "write"

    def test_get_method_standalone_decorator(self):
        """A standalone decorator literally equal to 'get' → read."""
        s = _S("endpoint", ("get",))
        assert classify_op_kind(s) == "read"

    def test_list_method_standalone_decorator(self):
        """A standalone decorator literally equal to 'list' → read."""
        s = _S("endpoint", ("list",))
        assert classify_op_kind(s) == "read"

    def test_listable_substring_not_read(self):
        """'listable' contains 'list' as prefix but is not a whole token."""
        s = _S("run", ("listable_resource",))
        # name 'run' has no verb prefix → falls through to decorator check.
        # 'listable' must NOT match as 'list' word-boundary.
        result = classify_op_kind(s)
        assert result != "read"


# ---------------------------------------------------------------------------
# classify_op_kind_ex — extended interface
# ---------------------------------------------------------------------------


class TestClassifyOpKindEx:
    def test_returns_tuple_of_two(self):
        s = _S("get_user")
        result = classify_op_kind_ex(s)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_verb_prefix_returns_low_confidence(self):
        """Name-only (verb prefix) inference carries 'low' confidence — it's a guess."""
        s = _S("get_user")
        op, confidence = classify_op_kind_ex(s)
        assert op == "read"
        assert confidence == "low"

    def test_http_decorator_returns_high_confidence(self):
        """HTTP method via decorator is a stronger signal → 'high' confidence."""
        s = _S("handle", ("router.get('/x')",))
        op, confidence = classify_op_kind_ex(s)
        assert op == "read"
        assert confidence == "high"

    def test_write_verb_prefix_low_confidence(self):
        s = _S("create_user")
        op, confidence = classify_op_kind_ex(s)
        assert op == "write"
        assert confidence == "low"

    def test_http_post_decorator_high_confidence(self):
        s = _S("handle", ("router.post('/x')",))
        op, confidence = classify_op_kind_ex(s)
        assert op == "write"
        assert confidence == "high"

    def test_unknown_is_low_confidence(self):
        """No verb, no HTTP decorator → unknown with low confidence."""
        s = _S("noop")
        op, confidence = classify_op_kind_ex(s)
        assert op == "unknown"
        assert confidence == "low"

    def test_ambiguous_verb_is_low_confidence(self):
        s = _S("process_batch")
        op, confidence = classify_op_kind_ex(s)
        assert op == "unknown"
        assert confidence == "low"

    def test_budget_gettable_not_high_confidence_read(self):
        """@budget_gettable: substring match must not produce high-confidence read."""
        s = _S("handle", ("budget_gettable",))
        op, confidence = classify_op_kind_ex(s)
        # If it IS classified as read, it must NOT be high confidence.
        if op == "read":
            assert confidence != "high"


# ---------------------------------------------------------------------------
# Back-compat: classify_op_kind returns plain str
# ---------------------------------------------------------------------------


class TestClassifyOpKindBackCompat:
    def test_returns_str(self):
        s = _S("process_report")
        result = classify_op_kind(s)
        assert isinstance(result, str)

    def test_write_verb_returns_str(self):
        s = _S("create_order")
        assert classify_op_kind(s) == "write"

    def test_read_verb_returns_str(self):
        s = _S("get_order")
        assert classify_op_kind(s) == "read"

    def test_unknown_returns_str(self):
        s = _S("noop")
        assert classify_op_kind(s) == "unknown"
