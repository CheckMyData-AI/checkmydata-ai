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
    Claim(
        setting="chroma_embedding_model",
        asserted=lambda: bool((settings.chroma_embedding_model or "").strip()),
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
