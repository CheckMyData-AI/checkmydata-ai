"""The synthesis prompt told the model to present a truncated analysis as complete.

``build_synthesis_messages`` is reached from exactly one place — the ``else`` branch
of the orchestrator's tool loop, entered when the step budget is spent
(``orchestrator.py:1869-1883``). Every answer it produces is therefore, by
construction, an answer the agent stopped working on. The user message it built said,
verbatim:

    Do NOT mention step limits, partial results, or that anything was cut short —
    present this as a complete answer.

`vision.md` §7 lists honesty about partial data as an invariant, `SCN-055` promises
"an honest partial answer plus Continue analysis", and W0/W1 shipped a whole
truncation-caveat workstream. One sentence in the prompt inverted all of it. The honest
fallbacks (``build_partial_text``, ``build_timeout_text``) exist but only fire when
synthesis returns nothing at all — when it succeeds, the text denied its own state.

Sharpest detail: the orchestrator already tells the *next* turn the truth
(``orchestrator.py:1271-1274``: "The LAST assistant message was a partial result cut
short by the step limit"). Only the reader was kept from it.

The replacement is honest in both directions. Over-hedging is its own dishonesty: the
step budget can be spent on a question the collected data fully answers, and a caveat
invented for that answer teaches the reader to discount every caveat after it.
"""

from __future__ import annotations

import pytest

from app.agents.response_builder import ResponseBuilder
from app.llm.base import Message


def _synthesis_user_message(**kwargs) -> str:
    messages = [
        Message(role="system", content="You are a data assistant."),
        Message(role="user", content="Revenue by month"),
    ]
    result = ResponseBuilder.build_synthesis_messages(messages, None, [], 32000, **kwargs)
    return result[1].content


@pytest.mark.parametrize(
    "forbidden",
    [
        "present this as a complete answer",
        "Do NOT mention step limits",
        "do not mention partial results",
    ],
)
def test_the_prompt_no_longer_orders_the_model_to_hide_the_cut(forbidden: str) -> None:
    assert forbidden.lower() not in _synthesis_user_message().lower()


def test_the_prompt_says_the_run_stopped_at_its_budget() -> None:
    msg = _synthesis_user_message().lower()
    assert "step budget" in msg, "the model is not told the analysis was cut short"


def test_the_prompt_asks_for_the_unreached_part_to_be_named() -> None:
    msg = _synthesis_user_message().lower()
    assert "did not reach" in msg or "not reach" in msg, (
        "the model is told the run was cut short but not what to do about it"
    )


def test_the_prompt_forbids_an_invented_caveat_when_the_data_is_enough() -> None:
    """Honesty in both directions — a caveat on a complete answer is also a lie."""
    msg = _synthesis_user_message().lower()
    assert "no caveat" in msg or "add no caveat" in msg, (
        "nothing stops the model hedging an answer the data fully supports"
    )


def test_the_data_section_is_untouched() -> None:
    """The prompt change must not disturb what the model is given to answer from."""
    msg = _synthesis_user_message()
    assert "DATA COLLECTED:" in msg
    assert "SAME language as the original question" in msg
    assert "Original question: Revenue by month" in msg
