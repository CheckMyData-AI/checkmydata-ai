"""A default that names a capability the deploy does not have is a false claim.

`sentence-transformers` is in **no** dependency list — not `dependencies`, not the
`redis` or `dev` optional groups. The code handles that correctly: `vector_store.py`
probes with `importlib.util.find_spec` and falls back. Nothing crashes.

What was wrong was the *advertising*. `CHROMA_EMBEDDING_MODEL` names a 768-d model
that never loads; production embeds at 384-d through Chroma's built-in fallback. The
other half of this pair was `reranker_enabled`, which defaulted to `True` while being
a no-op in every deployment that ever ran; it was corrected to `False` on 2026-08-10
and the whole capability was deleted in 2026-09, so only the embedder is pinned here.

These tests pin the honest position: the optional capability is **off** unless the
optional extra is installed, and the extra exists as a declared, installable thing
rather than as folklore in a deploy note.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from app.config import Settings

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


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
