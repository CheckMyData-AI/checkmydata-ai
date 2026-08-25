"""A flag that claims a capability the image does not carry must say so at every boot.

`RERANKER_ENABLED=true` sat in production while neither `sentence_transformers` nor
`torch` was in the image (verified inside the running dyno on 2026-08-23). Nothing broke:
the reranker degrades honestly to a no-op. But an operator reading `heroku config` saw an
enabled feature that does not exist, and had no way to learn otherwise — the only signal
was one WARNING emitted lazily, on first use of the vector store, hours into a dyno's life
and long past the boot log anybody reads after a deploy.

`chroma_embedding_model` has the same shape and a worse consequence. Its default names a
768-dimension model; without the extra, Chroma silently embeds at 384 with its bundled
MiniLM. The two are not comparable, so the mismatch is not a degradation but a **wrong
answer**, and switching later needs a full re-index.

`CHROMA_SERVER_URL` is the third, and it is the one that is not a problem yet. The
installed `chromadb` carries GHSA-f4j7-r4q5-qw2c — pre-authentication code injection,
CRITICAL, **no fixed version exists**. Today there is no HTTP listener because the URL is
unset, so the vector is unreachable. It becomes reachable the moment somebody sets one
environment variable, which is exactly the transition a boot check should defend rather
than the state it currently observes.

What all three have in common: the configuration asserts something the runtime does not
provide, and the gap is silent. Once at import is not enough — a warning that can be
missed by scrolling is a warning that will be.
"""

from __future__ import annotations

import logging

import pytest

from app.ops.capability_report import Claim, report_capabilities


def _claims(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records]


@pytest.fixture
def loud(caplog):
    caplog.set_level(logging.INFO, logger="app.ops.capability_report")
    return caplog


def test_an_enabled_flag_without_its_dependency_warns(loud, monkeypatch) -> None:
    monkeypatch.setattr("app.ops.capability_report._importable", lambda name: False)
    monkeypatch.setattr("app.ops.capability_report.settings.reranker_enabled", True)

    unmet = report_capabilities()

    assert "reranker_enabled" in {c.setting for c in unmet}
    assert any("reranker_enabled" in m for m in _claims(loud))
    assert any(r.levelno == logging.WARNING for r in loud.records)


def test_the_same_flag_with_its_dependency_present_is_silent(loud, monkeypatch) -> None:
    monkeypatch.setattr("app.ops.capability_report._importable", lambda name: True)
    monkeypatch.setattr("app.ops.capability_report.settings.reranker_enabled", True)

    unmet = report_capabilities()

    assert "reranker_enabled" not in {c.setting for c in unmet}


def test_a_disabled_flag_is_not_reported(loud, monkeypatch) -> None:
    """Off and unavailable is a coherent state, not a warning."""
    monkeypatch.setattr("app.ops.capability_report._importable", lambda name: False)
    monkeypatch.setattr("app.ops.capability_report.settings.reranker_enabled", False)

    assert "reranker_enabled" not in {c.setting for c in report_capabilities()}


def test_a_custom_embedding_model_without_the_extra_warns(loud, monkeypatch) -> None:
    """Silently embedding at 384 when the config names a 768-d model is not a
    degradation — the vectors are not comparable, so the answer is wrong."""
    monkeypatch.setattr("app.ops.capability_report._importable", lambda name: False)
    monkeypatch.setattr(
        "app.ops.capability_report.settings.chroma_embedding_model", "BAAI/bge-base-en-v1.5"
    )

    unmet = {c.setting for c in report_capabilities()}
    assert "chroma_embedding_model" in unmet
    assert any("384" in m for m in _claims(loud)), "the message has to name the real dimension"


def test_an_empty_embedding_model_is_not_a_claim(loud, monkeypatch) -> None:
    """Empty means "use Chroma's default", which is exactly what happens."""
    monkeypatch.setattr("app.ops.capability_report._importable", lambda name: False)
    monkeypatch.setattr("app.ops.capability_report.settings.chroma_embedding_model", "")

    assert "chroma_embedding_model" not in {c.setting for c in report_capabilities()}


class TestRemoteChromaIsTheTransitionNotTheState:
    """GHSA-f4j7-r4q5-qw2c is CRITICAL with no fixed version. It is unreachable only
    because no HTTP listener is configured — one environment variable away."""

    def test_no_server_url_is_silent(self, loud, monkeypatch) -> None:
        monkeypatch.setattr("app.ops.capability_report.settings.chroma_server_url", "")
        assert "chroma_server_url" not in {c.setting for c in report_capabilities()}

    def test_a_server_url_is_reported_at_critical(self, loud, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.ops.capability_report.settings.chroma_server_url", "http://chroma:8000"
        )
        unmet = report_capabilities()
        assert "chroma_server_url" in {c.setting for c in unmet}
        assert any(r.levelno == logging.CRITICAL for r in loud.records), (
            "a reachable pre-auth code-injection vector with no available fix is not a WARNING"
        )


def test_a_clean_configuration_says_so_once(loud, monkeypatch) -> None:
    """Silence is indistinguishable from the check not running."""
    monkeypatch.setattr("app.ops.capability_report._importable", lambda name: True)
    monkeypatch.setattr("app.ops.capability_report.settings.chroma_server_url", "")
    monkeypatch.setattr("app.ops.capability_report.settings.reranker_enabled", False)
    monkeypatch.setattr("app.ops.capability_report.settings.chroma_embedding_model", "")

    assert report_capabilities() == []
    assert any("capability check" in m.lower() for m in _claims(loud))


def test_it_never_raises(monkeypatch) -> None:
    """A boot-time diagnostic that can stop the boot is a worse bug than the one it
    reports."""
    monkeypatch.setattr(
        "app.ops.capability_report._importable",
        lambda name: (_ for _ in ()).throw(RuntimeError("import machinery broke")),
    )
    assert report_capabilities() == []


def test_every_claim_names_the_remedy() -> None:
    """A warning an operator cannot act on trains them to scroll past it."""
    from app.ops.capability_report import CLAIMS

    assert CLAIMS
    for claim in CLAIMS:
        assert isinstance(claim, Claim)
        assert len(claim.remedy) > 20, f"{claim.setting} has no usable remedy"
