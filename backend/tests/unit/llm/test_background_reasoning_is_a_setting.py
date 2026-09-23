"""O-1 (audit 2026-09-23 §2): the background model's reasoning is a setting.

`deepseek/deepseek-v4-flash-0731` was repriced on 2026-09-21 ($0.64/M out), and 25-40%
of its completion tokens on background work are reasoning (measured on production's
runtime 2026-09-23: 228-505 of 867-1 089 tokens per three-table batch). With reasoning
off the same batch cost 30-40% less, all three tool calls still came back, and 3 of 3
runs still said `amount` is cents and `currency` is multi-currency.

The switch applies only to calls that resolve to `DEFAULT_LLM_MODEL` — the background
stream. A pinned model (chat, indexing) is never touched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.base import Message
from app.llm.openrouter_adapter import OpenRouterAdapter


def _resp():
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = {
        "choices": [{"message": {"content": "ok", "role": "assistant"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        "model": "deepseek/deepseek-v4-flash-0731",
    }
    return r


async def _payload(monkeypatch, *, setting: str, model: str) -> dict:
    from app.config import settings

    monkeypatch.setattr(settings, "default_llm_model", "deepseek/deepseek-v4-flash-0731")
    monkeypatch.setattr(settings, "default_llm_model_reasoning", setting)
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    adapter = OpenRouterAdapter()
    adapter._client.post = AsyncMock(return_value=_resp())
    await adapter.complete([Message(role="user", content="hi")], model=model)
    return adapter._client.post.call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_off_turns_reasoning_off_for_the_default_model(monkeypatch) -> None:
    payload = await _payload(monkeypatch, setting="off", model="deepseek/deepseek-v4-flash-0731")
    assert payload["reasoning"] == {"enabled": False}


@pytest.mark.asyncio
async def test_a_pinned_model_is_never_touched(monkeypatch) -> None:
    payload = await _payload(monkeypatch, setting="off", model="z-ai/glm-5.2")
    assert "reasoning" not in payload


@pytest.mark.asyncio
async def test_default_leaves_the_provider_default(monkeypatch) -> None:
    payload = await _payload(
        monkeypatch, setting="default", model="deepseek/deepseek-v4-flash-0731"
    )
    assert "reasoning" not in payload


def test_an_unknown_value_is_refused_at_boot() -> None:
    from app.config import Settings

    with pytest.raises(ValueError, match="DEFAULT_LLM_MODEL_REASONING"):
        Settings(default_llm_model_reasoning="maybe")
