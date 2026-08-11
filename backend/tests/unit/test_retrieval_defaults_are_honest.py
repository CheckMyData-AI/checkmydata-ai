"""A default that names a capability the deploy does not have is a false claim.

`sentence-transformers` is in **no** dependency list — not `dependencies`, not the
`redis` or `dev` optional groups. The code handles that correctly: `vector_store.py`
probes with `importlib.util.find_spec` and falls back, `reranker.py` imports lazily.
Nothing crashes.

What was wrong was the *advertising*. `reranker_enabled` defaulted to `True` and was
documented as "ON by default", while being a no-op in every deployment that has ever
run. `CHROMA_EMBEDDING_MODEL` named a 768-d model that never loads; production embeds
at 384-d through Chroma's built-in fallback.

These tests pin the honest position: the optional capability is **off** unless the
optional extra is installed, and the extra exists as a declared, installable thing
rather than as folklore in a deploy note.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

from app.config import Settings

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_reranker_is_off_unless_the_extra_is_installed():
    """Default must match what a stock deploy can actually do."""
    installed = importlib.util.find_spec("sentence_transformers") is not None
    assert Settings().reranker_enabled is installed, (
        "reranker_enabled must not claim a capability the image does not carry; "
        f"sentence-transformers installed={installed}"
    )


def test_the_optional_extra_is_declared_and_installable():
    """`pip install -e '.[ml]'` must be a real instruction, not a deploy-note wish."""
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert "ml" in extras, "the retrieval extra must be declarable, not folklore"
    joined = " ".join(extras["ml"])
    assert "sentence-transformers" in joined


def test_the_embedding_model_setting_says_what_it_needs():
    """The 768-d model silently degrades to 384-d without the extra; say so."""
    field = Settings.model_fields["chroma_embedding_model"]
    described = f"{field.description or ''}"
    assert "sentence-transformers" in described, (
        "a setting whose value is silently ignored without an optional package must "
        "name that package where it is defined"
    )
