"""The key that says whether a generated document is still the right document.

`generate_docs` is the most expensive step the product runs: measured on production, a
full rebuild of `esim-php` spends ~9 375 s of its 12 039 s there, 758 documents at ~4.8
per minute and 1.7–2.0M tokens. 535 of those documents describe database migrations —
files that are never edited after they are merged.

Full rebuilds are routine rather than exceptional. `reconcile_embeddings` enqueues one
whenever `SYMBOL_UID_SCHEMA`, `GRAPH_EXTRACTION_SCHEMA` or the embedding configuration
changes, so every structural fix to the extractor re-buys the same prose about the same
unchanged migrations.

A generated document is a function of what was fed to the model, so that is what the key
is made of — and, pointedly, nothing else. The commit sha is absent because a rebuild
triggered by a schema bump has not altered one character of a migration; including it
would make the cache miss on exactly the runs it exists to make cheap.
"""

from __future__ import annotations

import hashlib

#: Bump when the document prompt, its format, or the meaning of a `doc_type` changes —
#: anything that would make the model produce a different document from identical input.
#:
#: Deliberately NOT part of `embedding_fingerprint()`, and the independence runs both
#: ways. Inside it, rewording a prompt would re-embed every chunk of every project (the
#: 2 300 s `code_symbol_embed` step) for a change that moves no vector. And the reverse —
#: the UID/graph schema constants inside this key — would discard 758 cached documents
#: whenever a symbol's identity moved, which is the cost this module exists to avoid.
DOC_GEN_SCHEMA = 1

#: `knowledge_docs.content_hash` is `String(80)`; a sha256 hex digest is 64 plus room for
#: a future prefix.
_SEP = "\x00"


def doc_content_hash(
    *,
    content: str,
    doc_type: str,
    enrichment_context: str | None,
) -> str:
    """Identify the inputs a generated document was produced from.

    The separator is load-bearing: without it ``("ab", "c")`` and ``("a", "bc")`` would
    hash alike, and a `doc_type` rename could silently inherit another document's cache
    entry. ``\\x00`` cannot occur in the stored text — `DocStore.upsert` strips it.
    """
    h = hashlib.sha256()
    h.update(content.encode("utf-8", "replace"))
    h.update(_SEP.encode())
    h.update(doc_type.encode("utf-8", "replace"))
    h.update(_SEP.encode())
    h.update((enrichment_context or "").encode("utf-8", "replace"))
    h.update(_SEP.encode())
    h.update(str(DOC_GEN_SCHEMA).encode())
    return h.hexdigest()


def should_reuse_document(
    *,
    existing_content: str | None,
    stored_hash: str | None,
    computed_hash: str,
) -> bool:
    """Is the document already on record still the right document?

    Three states, and only one of them is a hit:

    * **no stored document** — nothing to reuse, whatever the hash says. A row can carry
      a hash and no usable content only through a partial write, and generating is the
      cheap way to be sure.
    * **stored hash is `None`** — the document predates this cache. That is *unknown*,
      not *unchanged*: nobody recorded what it was generated from, so claiming a match
      would be asserting something never measured. It regenerates once and records the
      hash; the run after that is the cheap one.
    * **hashes equal** — the inputs are identical, so the model would be asked the same
      question it has already answered. Reuse.

    Kept as a named function rather than an `if` inside the pipeline step because it is
    the rule the whole cache rests on, and the step it lives in is a 400-line body that
    no unit test can reach without an LLM, a tracker and two sessions.
    """
    if existing_content is None:
        return False
    if stored_hash is None:
        return False
    return stored_hash == computed_hash
