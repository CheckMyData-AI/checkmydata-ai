"""Wave-2 flag-flip gate: reranker_enabled and context_planner_enabled must be ON by default."""

from app.config import settings


def test_reranker_default_off_until_the_extra_is_installed() -> None:
    """Corrected 2026-08-10 — this test defended a claim that was never true in prod.

    It asserted `reranker_enabled is True` as a W2 flag-flip. But
    `sentence-transformers` was in no dependency list, so the flag was on and the
    reranker was a no-op in every deployment that ever ran: the assertion passed while
    the capability it stood for did not exist.

    The honest default tracks what the image can actually do. A flag that advertises a
    missing capability reads as configuration and behaves as absence — the same failure
    shape as a `0` threshold that silently disables a breaker.
    """
    import importlib.util

    installed = importlib.util.find_spec("sentence_transformers") is not None
    assert settings.reranker_enabled is installed


def test_context_planner_default_on() -> None:
    assert settings.context_planner_enabled is True
