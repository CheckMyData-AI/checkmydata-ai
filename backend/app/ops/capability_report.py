"""Boot-time check: does the runtime actually provide what the configuration claims?

Three settings in this project name a capability that the deployed image may not carry.
None of them crashes when the capability is absent — each degrades honestly — and that is
precisely the problem: the operator reading ``heroku config`` sees a feature switched on,
and nothing ever tells them otherwise.

Measured in production on 2026-08-23: ``RERANKER_ENABLED=true`` while neither
``sentence_transformers`` nor ``torch`` was importable inside the dyno. The reranker had
been a no-op in every deployment that ever ran. The only signal was a single WARNING
emitted lazily on first use of the vector store — hours into a dyno's life, long past the
boot log anyone reads after a deploy.

**Once is not enough.** A warning that can be missed by scrolling is a warning that will
be. This runs on every boot, and says so even when everything is fine, because silence is
indistinguishable from the check not running.

The check is a diagnostic and must never be able to stop a boot: everything below is
wrapped, and a failure to introspect degrades to reporting nothing.
"""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.config import settings
from app.core.embedder import BUNDLED_EMBEDDING_MODEL

logger = logging.getLogger(__name__)


def _importable(name: str) -> bool:
    """True when *name* can be imported without importing it.

    ``find_spec`` rather than ``import``: the packages this asks about are large
    (``torch`` alone), and a boot check must not pay to load one.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


@dataclass(frozen=True)
class Claim:
    """A setting that asserts something the runtime might not provide.

    ``asserted`` — is the configuration claiming this capability right now?
    ``provided`` — does the runtime actually have it?
    ``remedy`` — what the operator does about it. A warning nobody can act on trains
    them to scroll past the next one.
    """

    setting: str
    asserted: Callable[[], bool]
    provided: Callable[[], bool]
    consequence: str
    remedy: str
    level: int = logging.WARNING


def _active_backend() -> str | None:
    """The store this process will actually use, or ``None`` when it cannot be determined.

    Resolved rather than read: the default is ``auto``, so a literal comparison against
    ``settings.vector_store_backend`` would match neither branch below and the claim would
    silently vanish on the default configuration — a check that disappears exactly where it
    is most needed.

    ``None`` on error because an explicit ``pgvector`` against SQLite raises by design, and
    a boot diagnostic must never be able to stop a boot.
    """
    try:
        from app.knowledge.vector_store import resolve_backend

        return resolve_backend(settings.vector_store_backend, settings.database_url)
    except Exception:
        # WARNING, not debug, and the silent-degradation ratchet is what caught it: a
        # caller cannot tell this `None` from "no claim applies", so an unresolvable
        # backend would make BOTH claims below vanish without a word — a capability check
        # that stops checking, which is the exact failure this module was written against.
        # Rare by construction: `resolve_backend` only raises on a configuration that is
        # already invalid, such as an explicit `pgvector` against SQLite.
        logger.warning(
            "Capability check: the vector backend could not be resolved from "
            "VECTOR_STORE_BACKEND=%r and the configured DATABASE_URL, so the "
            "embedding-model claims below are NOT being checked",
            settings.vector_store_backend,
            exc_info=True,
        )
        return None


def _model_configured() -> bool:
    """True only when a model OTHER than the bundled one is asked for.

    Naming the bundled ONNX all-MiniLM-L6-v2 is not a claim about an optional extra — it
    is a description of what runs, and it is the default. A check that warns about the
    untouched default fires on every boot of every install, which is how an operator
    learns to scroll past the line that one day matters.
    """
    configured = (settings.chroma_embedding_model or "").strip()
    return bool(configured) and configured != BUNDLED_EMBEDDING_MODEL


CLAIMS: tuple[Claim, ...] = (
    Claim(
        setting="reranker_enabled",
        asserted=lambda: bool(settings.reranker_enabled),
        provided=lambda: _importable("sentence_transformers"),
        consequence=(
            "cross-encoder reranking is configured ON but degrades to a no-op; "
            "retrieval is fused-RRF only, and the flag reads as a capability it is not"
        ),
        remedy="install the optional extra (`pip install -e '.[ml]'`) or unset RERANKER_ENABLED",
    ),
    # TWO claims for one setting, because the two backends make different promises and a
    # single claim has to pick one and be wrong on the other.
    Claim(
        setting="chroma_embedding_model",
        asserted=lambda: _model_configured() and _active_backend() == "chroma",
        provided=lambda: _importable("sentence_transformers"),
        consequence=(
            "the configured model is ignored and ChromaDB embeds at 384-d with its "
            "bundled all-MiniLM-L6-v2. 384-d and 768-d vectors are NOT comparable, so "
            "this is a wrong answer rather than a slower one"
        ),
        remedy=(
            "install `.[ml]` AND run a full re-index (queue_embedding_reindex), or clear "
            "CHROMA_EMBEDDING_MODEL so the configuration matches what is actually used"
        ),
    ),
    Claim(
        setting="chroma_embedding_model",
        asserted=lambda: _model_configured() and _active_backend() == "pgvector",
        # False unconditionally, like the `chroma_server_url` claim below: nothing in the
        # image can satisfy this one. `PgVectorStore._embed` constructs
        # `ONNXMiniLM_L6_V2()` directly and never reads the setting, so installing `.[ml]`
        # would make this warning STOP while its condition persisted — a check going quiet
        # without the thing being fixed, which is the exact failure this module documents.
        provided=lambda: False,
        consequence=(
            "the active store is pgvector, which embeds with the bundled ONNX "
            "all-MiniLM-L6-v2 at 384-d and never reads this setting at all — so the "
            "configured model is ignored no matter what is installed, and the "
            "configuration claims a capability that cannot exist on this backend"
        ),
        remedy=(
            "clear CHROMA_EMBEDDING_MODEL so the configuration matches what runs. "
            "Installing `.[ml]` does NOT help here and only hides this line; a different "
            "embedding dimension on pgvector needs EMBEDDING_DIM, its migration, and a "
            "full re-index, because 384-d and 768-d vectors are not comparable"
        ),
    ),
    Claim(
        setting="chroma_server_url",
        # Inverted on purpose: here the *presence* of configuration is the risk, and
        # nothing in the image can make it safe — see `provided` below.
        asserted=lambda: bool((settings.chroma_server_url or "").strip()),
        provided=lambda: False,
        consequence=(
            "a remote ChromaDB HTTP listener is configured, and the installed chromadb "
            "carries GHSA-f4j7-r4q5-qw2c / PYSEC-2026-311 — pre-authentication code "
            "injection, CRITICAL, with NO fixed version available. Embedded "
            "PersistentClient has no listener and so no pre-auth surface; setting this "
            "variable is what creates one"
        ),
        remedy=(
            "unset CHROMA_SERVER_URL to return to the embedded client, or place the "
            "Chroma server behind a network boundary that no untrusted caller can reach"
        ),
        level=logging.CRITICAL,
    ),
)


def report_capabilities() -> list[Claim]:
    """Log one line per unmet claim; return them. Never raises."""
    unmet: list[Claim] = []
    for claim in CLAIMS:
        try:
            if claim.asserted() and not claim.provided():
                unmet.append(claim)
                logger.log(
                    claim.level,
                    "Capability check: %s is set, but %s. Remedy: %s",
                    claim.setting,
                    claim.consequence,
                    claim.remedy,
                )
        except Exception:
            logger.debug("capability claim %s could not be evaluated", claim.setting, exc_info=True)
    if not unmet:
        logger.info(
            "Capability check: %d configuration claims verified against the runtime, all satisfied",
            len(CLAIMS),
        )
    return unmet
