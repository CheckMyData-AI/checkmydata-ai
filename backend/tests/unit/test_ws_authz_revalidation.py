"""F-CHAT-01: revoking access must take effect before the next message, not on disconnect.

The chat WebSocket checks access **once**, immediately before `websocket.accept()`, and
never again. A socket lives as long as the tab is open, so removing somebody from a
project leaves them able to keep asking questions of its database for as long as they do
not reload — hours, or until the idle timeout.

Authorization belongs to the action, not to the connection. A user message is a new
action, so the check moves there: one indexed query per message, and messages are
seconds-to-minutes apart.

Found alongside it: the gate inlined `owner_id OR member` as raw SQL — a **fourth** copy
of a rule whose own helper says "Single source of truth for the access rule used by the
HTTP API (chat WebSocket gate) and the MCP tools so they cannot drift". The docstring
named this very call site as a user while the call site did not use it. Iteration 5
aligned three readers; this was the one hiding in a route.
"""

from __future__ import annotations

import inspect

from app.api.routes import chat as chat_route


class TestTheRuleIsNotCopied:
    def test_the_ws_gate_uses_the_shared_predicate(self):
        src = inspect.getsource(chat_route.chat_websocket)
        assert "can_access" in src or "_accessible_filter" in src, (
            "the WS gate must ask the membership service, not re-implement the rule"
        )

    def test_no_inline_owner_or_member_sql_remains(self):
        src = inspect.getsource(chat_route.chat_websocket)
        # The shape of the copy: an owner_id comparison beside a ProjectMember subquery.
        assert not ("Project.owner_id == user_id" in src and "ProjectMember.project_id" in src), (
            "the access rule is inlined again — that is the drift `_accessible_filter` exists "
            "to prevent, and its docstring already claims this call site as a user"
        )


class TestAccessIsRecheckedPerMessage:
    def test_the_receive_loop_revalidates(self):
        src = inspect.getsource(chat_route.chat_websocket)
        loop = src.split("while True:", 1)[-1]
        assert "can_access" in loop, (
            "access is checked only at connect, so a revoked member keeps querying until "
            "they disconnect"
        )

    def test_a_denial_closes_the_socket_rather_than_silently_ignoring(self):
        src = inspect.getsource(chat_route.chat_websocket)
        loop = src.split("while True:", 1)[-1]
        # Dropping the message without saying anything would look like the product
        # hanging; the reader is owed the reason.
        assert "4003" in loop, "a revoked member must be told, and closed, not ignored"
