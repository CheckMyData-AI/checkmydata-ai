"""L5: WebSocket chat pipeline-control plumbing.

The WS transport previously could not drive checkpoint Continue / Modify /
Retry actions because ``WsChatMessage`` carried no pipeline fields and the WS
``extra`` only held ``session_id``. These tests pin the parsed fields and the
``_ws_pipeline_extra`` threading (parity with the HTTP/SSE ChatRequest path).
"""

from __future__ import annotations

import pytest

from app.api.routes.chat import WsChatMessage, _ws_pipeline_extra


class TestWsPipelineExtra:
    def test_plain_message_threads_only_session(self):
        msg = WsChatMessage(message="hello")
        assert _ws_pipeline_extra("s1", msg) == {"session_id": "s1"}

    def test_pipeline_action_threaded(self):
        msg = WsChatMessage(
            message="continue",
            pipeline_action="continue",
            pipeline_run_id="run-1",
            modification="add a filter",
        )
        extra = _ws_pipeline_extra("s1", msg)
        assert extra["session_id"] == "s1"
        assert extra["pipeline_action"] == "continue"
        assert extra["pipeline_run_id"] == "run-1"
        assert extra["modification"] == "add a filter"

    def test_continuation_context_threaded(self):
        msg = WsChatMessage(
            message="x",
            pipeline_action="continue_analysis",
            continuation_context="prior ctx",
        )
        extra = _ws_pipeline_extra("s2", msg)
        assert extra["pipeline_action"] == "continue_analysis"
        assert extra["continuation_context"] == "prior ctx"

    def test_no_action_omits_pipeline_keys(self):
        # pipeline_run_id without an action is not threaded (mirrors REST).
        msg = WsChatMessage(message="x", pipeline_run_id="run-2")
        extra = _ws_pipeline_extra("s3", msg)
        assert extra == {"session_id": "s3"}

    def test_invalid_pipeline_action_rejected(self):
        with pytest.raises(Exception):
            WsChatMessage(message="x", pipeline_action="bogus")
