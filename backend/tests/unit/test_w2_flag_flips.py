"""Wave-2 flag-flip gate: reranker_enabled and context_planner_enabled must be ON by default."""

from app.config import settings


def test_reranker_default_on() -> None:
    assert settings.reranker_enabled is True


def test_context_planner_default_on() -> None:
    assert settings.context_planner_enabled is True
