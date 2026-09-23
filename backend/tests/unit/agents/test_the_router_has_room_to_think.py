"""B-25 — the router's completion cap leaves room for a model that reasons first.

Measured 2026-09-23 in the production runtime on z-ai/glm-5.2 (the chat model the router
runs on there): 15 routings of one question spent 159-297 reasoning tokens of 237-378
completion tokens, and the routing eval saw 1 EMPTY reply in 90 at the old 512 cap —
the budget gone before the JSON began, silently becoming the default route.
"""

from app.agents import router

MEASURED_MAX_COMPLETION = 378


def test_the_cap_keeps_the_margin_the_old_cap_gave_a_non_reasoning_model() -> None:
    assert router._ROUTER_MAX_TOKENS >= 2 * MEASURED_MAX_COMPLETION
