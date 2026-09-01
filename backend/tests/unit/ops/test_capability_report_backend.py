"""The boot-time honesty check was not honest about one setting.

`capability_report` exists because "the operator reading `heroku config` sees a feature
switched on, and nothing ever tells them otherwise" — its own docstring. The
`chroma_embedding_model` claim was that failure mode pointed at itself:

- It asked whether the setting was non-empty and whether `sentence_transformers` was
  importable. It never asked **which store is actually in use**.
- Production runs pgvector, and `PgVectorStore` hard-codes `ONNXMiniLM_L6_V2()`
  (`pgvector_store.py:114-116`) — it never reads that setting at all.

So on pgvector the configured model is ignored *unconditionally*, and installing the `ml`
extra would have made the warning **stop firing while its condition persisted**. A check
that goes quiet without the thing being fixed is worse than no check: silence then reads as
a pass.
"""

from __future__ import annotations

import logging

import pytest

from app.ops.capability_report import CLAIMS, report_capabilities

_SQLITE = "sqlite+aiosqlite:///./x.db"
_PG = "postgresql+asyncpg://u:p@h/db"


def _claims_for(setting: str) -> list:
    return [c for c in CLAIMS if c.setting == setting]


class TestTheEmbeddingModelClaimKnowsTheBackend:
    def test_there_is_a_claim_per_backend(self) -> None:
        """One claim cannot be right for both: on chroma the extra makes the setting real,
        on pgvector nothing can."""
        assert len(_claims_for("chroma_embedding_model")) == 2, (
            "a single claim has to pick one backend's truth and be wrong on the other"
        )

    def test_on_pgvector_the_setting_can_never_be_satisfied(self, monkeypatch) -> None:
        """`provided` must be False regardless of what is installed — otherwise installing
        `.[ml]` silences a warning whose condition is still true."""
        from app.config import settings

        monkeypatch.setattr(settings, "chroma_embedding_model", "BAAI/bge-base-en-v1.5")
        monkeypatch.setattr(settings, "vector_store_backend", "pgvector", raising=False)
        monkeypatch.setattr(settings, "database_url", _PG, raising=False)

        firing = [c for c in _claims_for("chroma_embedding_model") if c.asserted()]
        assert len(firing) == 1, "exactly one of the two claims applies at a time"
        assert firing[0].provided() is False
        assert "pgvector" in firing[0].consequence.lower(), firing[0].consequence
        assert "clear" in firing[0].remedy.lower() or "unset" in firing[0].remedy.lower(), (
            "the remedy must be reachable: a re-index cannot make pgvector read this setting"
        )

    def test_on_chroma_the_extra_is_still_the_remedy(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "chroma_embedding_model", "BAAI/bge-base-en-v1.5")
        monkeypatch.setattr(settings, "vector_store_backend", "chroma", raising=False)
        monkeypatch.setattr(settings, "database_url", _SQLITE, raising=False)

        firing = [c for c in _claims_for("chroma_embedding_model") if c.asserted()]
        assert len(firing) == 1
        assert "ml" in firing[0].remedy

    def test_neither_fires_when_the_setting_is_empty(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "chroma_embedding_model", "")
        monkeypatch.setattr(settings, "vector_store_backend", "auto", raising=False)
        monkeypatch.setattr(settings, "database_url", _PG, raising=False)
        assert not [c for c in _claims_for("chroma_embedding_model") if c.asserted()]

    @pytest.mark.parametrize("url,expect", [(_PG, "pgvector"), (_SQLITE, "chroma")])
    def test_auto_is_resolved_not_guessed(self, monkeypatch, url: str, expect: str) -> None:
        """The default is `auto`, so reading `settings.vector_store_backend` literally
        would match neither branch and the claim would vanish — a check that disappears on
        the default configuration."""
        from app.config import settings

        monkeypatch.setattr(settings, "chroma_embedding_model", "BAAI/bge-base-en-v1.5")
        monkeypatch.setattr(settings, "vector_store_backend", "auto", raising=False)
        monkeypatch.setattr(settings, "database_url", url, raising=False)

        firing = [c for c in _claims_for("chroma_embedding_model") if c.asserted()]
        assert len(firing) == 1, f"no claim applies under auto/{expect}"
        if expect == "pgvector":
            assert firing[0].provided() is False

    def test_a_backend_that_cannot_be_resolved_does_not_crash_the_report(
        self, monkeypatch, caplog
    ) -> None:
        """An explicit `pgvector` on SQLite RAISES by design. The boot report must never be
        able to stop a boot, and must not silently drop the claim either."""
        from app.config import settings

        monkeypatch.setattr(settings, "chroma_embedding_model", "BAAI/bge-base-en-v1.5")
        monkeypatch.setattr(settings, "vector_store_backend", "pgvector", raising=False)
        monkeypatch.setattr(settings, "database_url", _SQLITE, raising=False)
        with caplog.at_level(logging.WARNING, logger="app.ops.capability_report"):
            report_capabilities()  # must not raise

        # And must not go quiet either. Returning None at debug would make BOTH embedding
        # claims vanish with no word — a capability check that stopped checking, which is
        # the failure this module exists to prevent. The silent-degradation ratchet caught
        # exactly this in the first version of `_active_backend`.
        assert any("NOT being checked" in r.getMessage() for r in caplog.records), [
            r.getMessage()[:80] for r in caplog.records
        ]


def test_the_report_still_logs_on_success(monkeypatch, caplog) -> None:
    """Silence must never be indistinguishable from the check not running — the reason this
    module logs a passing line at all."""
    from app.config import settings

    monkeypatch.setattr(settings, "chroma_embedding_model", "")
    monkeypatch.setattr(settings, "reranker_enabled", False, raising=False)
    monkeypatch.setattr(settings, "chroma_server_url", "", raising=False)
    with caplog.at_level(logging.INFO, logger="app.ops.capability_report"):
        assert report_capabilities() == []
    assert any("all satisfied" in r.getMessage() for r in caplog.records)
