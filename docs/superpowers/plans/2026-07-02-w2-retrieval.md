# Wave 2 — Embedding & Retrieval — TDD Implementation Plan

**Feature:** Intelligence remediation Wave 2 (Embedding & retrieval precision)
**Date:** 2026-07-02
**Spec:** `docs/superpowers/specs/2026-07-02-intelligence-remediation-design.md` (§1 verified facts, §2 contracts C-E, §3 W2 scope, §9 flag flips)
**Audit source:** `docs/INTELLIGENCE_AUDIT_2026-07.md` §5 (RET-*), §3 (CODEIDX-*), §6 (DBIDX-D7)
**Repo:** `/Users/sshlg/DATA/checkmydata-ai`
**Branch (recommended):** `feat/w2-retrieval` in an isolated worktree (`superpowers:using-git-worktrees`) — do NOT start on `main`.
**Owned files (no other wave writes these):** `backend/app/knowledge/chunker.py`, `vector_store.py`, `hybrid_retriever.py`, `reranker.py`, `pipeline_runner.py` (embed stage only), `schema_retriever.py`; `backend/app/agents/context_loader.py`, `context_planner.py`, `orchestrator.py` (single wiring block only — coordinate with W3), `sql_agent.py` (`_build_query_context` safety-net + `_retrieve_tables_for_question` only); `backend/app/services/knowledge_catalog_service.py`; `backend/app/config.py` (new keys only); `backend/.env.example`; new module `backend/app/knowledge/tokenizer_window.py`; new module `backend/app/knowledge/context_pack_renderer.py`; new module `backend/app/knowledge/code_symbol_chunker.py`.

## Dependency graph & parallel groups

```
W0 (DONE — Foundations; contracts C-E scaffold + degradation event + metrics) ─┐
W4 (DONE for this wave's needs — DbIndex distinct-values/FK/numeric capture) ──┤
                                                                                ▼
Group A (sequential, run first — embedding correctness, no runtime deps):
  T1 CODEIDX-C2  tokenizer  ───┐
  T2 CODEIDX-C1  model+window ─┤ (T2 depends:[T1])
  T3 CODEIDX-C1  reindex/migration (T3 depends:[T2])
  T4 CODEIDX-C3  raw-code symbol embedding path (T4 depends:[T1,T2])
Group B (parallel after Group A — retrieval runtime; disjoint files):
  T5 RET-R2   catalog rag via HybridRetriever      (depends:[T2])
  T6 RET-R3   greedy relevance×confidence packing  (depends:[])  file: context_pack_renderer.py (new)
  T7 RET-R8   provenance render                    (depends:[T6]) file: context_pack_renderer.py
  T8 RET-R1   wire build_context_pack into orchestrator (depends:[T5,T6,T7])
  T9 RET-R4   retrieval_degraded event+metric      (depends:[])  file: hybrid_retriever.py
  T10 RET-R5  tighten thresholds + eval            (depends:[])  file: config.py + eval
Group C (parallel after Group A+B — schema retrieval; sql_agent + schema_retriever):
  T11 RET-R9 + DBIDX-D7  FK-hop expand + splice distinct/numeric (depends:[W4]) files: schema_retriever.py, sql_agent.py
  T12 RET-R10 relevance floor on safety-net        (depends:[T11]) file: sql_agent.py
  T13 Reranker CrossEncoder.rank                   (depends:[])   file: reranker.py
Group D (sequential glue, LAST — end-of-wave gate):
  T14 Low batch (RET-R11..R17, CODEIDX-C10/C11/C12/C13/C14/C18/C19/C20/C21)
  T15 Flag flips: reranker_enabled + context_planner_enabled under eval gate (depends:[all])
```

Hard edges consumed from earlier waves (do NOT reimplement):
- **W0 → all**: degradation event helper + metric names + `chunk_document(*, max_tokens, tokenizer)` signature shape.
- **W4 → T11/T12**: `DbIndex.column_distinct_values_json`, `DbIndex.numeric_format_notes` (already present today) + `SchemaInfo.foreign_keys` (already present live). C-D adds `ColumnInfo.distinct_values/distinct_count/null_rate/numeric_format`. T11's test is **gated** on those fields existing (see T11 scene-setting).

---

## Contracts CONSUMED (verbatim — do not redefine)

### From spec §2 C-E (retrieval & embedding)
```python
# app/knowledge/chunker.py — sizing to the real tokenizer window (C-E):
def chunk_document(text: str, *, max_tokens: int, tokenizer) -> list[Chunk]: ...

# Raw-code embedding path metadata (C-E, closes CODEIDX-C3):
#   {path, symbol, language, start_line, end_line, kind}

# ContextPack → runtime behind context_planner_enabled (C-E):
#   orchestrator calls build_context_pack(...); its rag_chunks go through
#   HybridRetriever (not dense-only, RET-R2); packing enforces token_budget by
#   greedy fill on (relevance × confidence) (RET-R3); rendered prompt block
#   includes provenance per artifact:
#     [{source} @ {commit_sha} · {indexed_at} · conf={confidence}]   (RET-R8)

# Degradation signal (C-E, RET-R4): when a retrieval leg returns 0 while the
# other has hits, emit WorkflowTracker event retrieval_degraded{leg, reason}
# + metric retrieval_degraded_total.

# Reranker (C-E): use CrossEncoder.rank(query, docs) — sorted result, no sign assumption.
```

### From W0 (already shipped — call, do not create)
```python
# app/core/workflow_tracker.py
async def emit(self, workflow_id, step, status, detail="", *, span_type=None,
               run_id=None, kind=None, step_index=None, total_steps=None,
               progress_pct=None, **extra) -> None: ...

# app/core/metrics.py
def inc(self, name: str, amount: int = 1, **labels: str) -> None: ...
def get_metrics_collector() -> MetricsCollector: ...
```

### From C-E config keys (spec §2 C-E; add in T2/T3)
```python
# app/config.py
chroma_embedding_model: str = "BAAI/bge-base-en-v1.5"   # was "" (ONNX all-MiniLM-L6-v2, 256-ctx)
embedder_max_tokens: int = 512                          # = bge-base-en-v1.5 model window
```

### Existing config keys CONSUMED read-only
```python
rag_relevance_threshold: float = 0.8      # RET-R5 tightens → 0.45
hybrid_min_score: float = 0.01            # RET-R5 tightens → 0.03
reranker_enabled: bool = False            # T15 flips → True
reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
reranker_candidates: int = 30
context_planner_enabled: bool = False     # T15 flips → True
context_planner_mode: str = "heuristic"
context_planner_budget_tokens: int = 8000
schema_retrieval_enabled: bool = True
sql_agent_max_context_tables: int = 15
hybrid_retrieval_enabled: bool = True
bm25_data_dir: str = "./data/bm25"
hybrid_k: int = 20
hybrid_rrf_k: int = 60
```

### From W4 (consumed by T11/T12 — read-only)
```python
# app/models/db_index.py (DbIndex) — present today:
column_distinct_values_json: Mapped[str]   # JSON dict[col -> list[str]]
numeric_format_notes: Mapped[str]          # JSON dict[col -> note]
# app/connectors/base.py (SchemaInfo) — present today:
foreign_keys: list[ForeignKeyInfo]         # ForeignKeyInfo has .column and target ref
```

---

## Global test conventions

- Runner: `backend/.venv/bin/pytest` (from `backend/`). `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed for async tests, but existing files use it; match the file you edit.
- New unit tests under `backend/tests/unit/knowledge/` or `backend/tests/unit/` mirroring the existing layout.
- Lint/format after each task: `cd backend && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/`.
- Retrieval-quality tests assert **precision/recall on a fixture corpus** (not "runs"): each such test builds a small labelled corpus, runs the retriever, and asserts ordering/precision@k/recall.
- Conventional commits, one per task; docs (`CLAUDE.md`, `.env.example`) updated in the same commit where touched.

---

## Task T1 — CODEIDX-C2: real tokenizer for chunk boundaries

`depends:[]`

**Scene:** `chunker.py` today estimates tokens as `chars/4` (`APPROX_CHARS_PER_TOKEN = 4`, line 12), which under-counts code (~3 chars/token) so "fitting" chunks overflow the embedder. Introduce a real tokenizer abstraction and route sizing through it. This task ships the tokenizer utility + a `count_tokens` used by T2's `chunk_document` rewrite. No model download at import time — the tokenizer lazy-loads and degrades to a conservative char heuristic when `transformers`/`tokenizers` is unavailable.

**Files:**
- NEW `backend/app/knowledge/tokenizer_window.py`
- NEW `backend/tests/unit/knowledge/test_tokenizer_window.py`

**Interfaces (define here; consumed by T2/T4):**
```python
# app/knowledge/tokenizer_window.py
class WindowTokenizer:
    """Lazy HF tokenizer wrapper with a safe char-based fallback."""
    def __init__(self, model_name: str) -> None: ...
    def count_tokens(self, text: str) -> int: ...      # real tokens, or ceil(len/3.2) fallback
    def truncate_to_tokens(self, text: str, max_tokens: int) -> str: ...
    @property
    def is_real(self) -> bool: ...                     # True when HF tokenizer loaded

def get_tokenizer(model_name: str) -> WindowTokenizer: ...   # process-cached
```

**Steps:**

- [ ] **RED** — write `backend/tests/unit/knowledge/test_tokenizer_window.py`:
```python
from app.knowledge.tokenizer_window import WindowTokenizer, get_tokenizer


def test_fallback_counts_more_tokens_than_chars_over_4() -> None:
    # A model name that will not resolve → char fallback (ceil(len/3.2)).
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    assert tk.is_real is False
    code = "def f(x):\n    return x*x\n" * 10  # dense code, ~240 chars
    n = tk.count_tokens(code)
    # chars/4 would UNDER-count; fallback must be >= chars/4 (i.e. use ~3.2).
    assert n >= len(code) / 4
    assert n == -(-len(code) // 3)  # ceil(len/3.2) rounded — see impl note below


def test_truncate_to_tokens_shrinks_text() -> None:
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    text = "word " * 500
    out = tk.truncate_to_tokens(text, max_tokens=50)
    assert tk.count_tokens(out) <= 50
    assert len(out) < len(text)


def test_get_tokenizer_is_process_cached() -> None:
    a = get_tokenizer("m")
    b = get_tokenizer("m")
    assert a is b
```
  Adjust the exact `ceil` constant assertion to match the impl (use `math.ceil(len/3.2)`; write the assertion as `import math; assert n == math.ceil(len(code) / 3.2)`).
- [ ] Run: `cd backend && .venv/bin/pytest tests/unit/knowledge/test_tokenizer_window.py -v` → **fails** (module missing).
- [ ] **GREEN** — create `backend/app/knowledge/tokenizer_window.py`:
```python
"""Tokenizer window utility — size chunks to a real embedder token window.

Wraps a HuggingFace fast tokenizer (loaded lazily to keep import cheap and to
avoid a network dependency at import time). When the tokenizer cannot be
loaded (offline, missing extra, unknown model) it degrades to a conservative
char-based estimate that OVER-counts relative to the old chars/4 so chunks
never silently overflow the embedder window (closes CODEIDX-C2)."""

from __future__ import annotations

import logging
import math
import threading

logger = logging.getLogger(__name__)

# Code is denser than prose: ~3.2 chars/token empirically for BPE tokenizers on
# source. Deliberately below the old ``4`` so the fallback errs toward smaller
# chunks (safe: a too-small chunk still embeds fully; a too-large one truncates).
_FALLBACK_CHARS_PER_TOKEN = 3.2

_CACHE: dict[str, "WindowTokenizer"] = {}
_CACHE_LOCK = threading.Lock()


class WindowTokenizer:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._tok = None
        self._loaded = False
        self._unavailable = False

    def _ensure(self) -> bool:
        if self._loaded:
            return self._tok is not None
        if self._unavailable:
            return False
        try:
            from transformers import AutoTokenizer

            self._tok = AutoTokenizer.from_pretrained(self._model_name)
            self._loaded = True
            logger.info("tokenizer_window: loaded %s", self._model_name)
            return True
        except Exception:
            self._unavailable = True
            self._loaded = True
            logger.warning(
                "tokenizer_window: could not load %s — using char fallback",
                self._model_name,
                exc_info=True,
            )
            return False

    @property
    def is_real(self) -> bool:
        return self._ensure()

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._ensure():
            try:
                return len(self._tok.encode(text, add_special_tokens=False))
            except Exception:
                logger.debug("tokenizer_window: encode failed — fallback", exc_info=True)
        return math.ceil(len(text) / _FALLBACK_CHARS_PER_TOKEN)

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0 or not text:
            return ""
        if self.count_tokens(text) <= max_tokens:
            return text
        if self._ensure():
            try:
                ids = self._tok.encode(text, add_special_tokens=False)[:max_tokens]
                return self._tok.decode(ids, skip_special_tokens=True)
            except Exception:
                logger.debug("tokenizer_window: truncate failed — char fallback", exc_info=True)
        # Char fallback: binary-search-free linear estimate.
        approx_chars = int(max_tokens * _FALLBACK_CHARS_PER_TOKEN)
        out = text[:approx_chars]
        while out and self.count_tokens(out) > max_tokens:
            out = out[: int(len(out) * 0.9)]
        return out


def get_tokenizer(model_name: str) -> WindowTokenizer:
    with _CACHE_LOCK:
        tk = _CACHE.get(model_name)
        if tk is None:
            tk = WindowTokenizer(model_name)
            _CACHE[model_name] = tk
        return tk


__all__ = ["WindowTokenizer", "get_tokenizer"]
```
- [ ] Run the test → **passes**.
- [ ] **DoD:** test green; `ruff format`+`check` clean.
- [ ] Commit: `feat(knowledge): real tokenizer window util for chunk sizing (CODEIDX-C2)`

---

## Task T2 — CODEIDX-C1: chunk to embedder window + default a 512-ctx model

`depends:[T1]`

**Scene:** `chunker.py` targets 1500 tokens but ChromaDB's default embedder (ONNX `all-MiniLM-L6-v2`) truncates at **256 tokens** (Context7-confirmed, spec §1), silently dropping ~80% of each large chunk before it enters the vector. Fix: (a) default `chroma_embedding_model` to a **512-token** model (`BAAI/bge-base-en-v1.5`, confirmed `max_seq_length=512`), (b) rewrite `chunk_document` to the C-E signature `chunk_document(text, *, max_tokens, tokenizer)` sizing on **real tokens** via T1's `WindowTokenizer`, (c) keep a back-compat call shim so existing `pipeline_runner.py` call sites (lines 1056, 1136, 1253: `chunk_document(content=..., file_path=..., doc_type=..., extra_metadata=...)`) keep working while defaulting `max_tokens`/`tokenizer` from settings.

**Files:**
- `backend/app/knowledge/chunker.py`
- `backend/app/config.py` (change `chroma_embedding_model` default; add `embedder_max_tokens`)
- `backend/tests/unit/knowledge/test_chunker.py` (create if absent; else extend)

**Interfaces (C-E, verbatim):**
```python
def chunk_document(text: str, *, max_tokens: int, tokenizer) -> list[Chunk]: ...
```
Plus a compatibility overload preserving the existing keyword call shape used by `pipeline_runner`:
```python
def chunk_document(
    content: str,
    file_path: str,
    doc_type: str,
    extra_metadata: dict | None = None,
    *,
    max_tokens: int | None = None,
    tokenizer=None,
) -> list[Chunk]: ...
```
(When `max_tokens`/`tokenizer` are None, resolve from `settings.embedder_max_tokens` and `get_tokenizer(settings.chroma_embedding_model)`.)

**Steps:**

- [ ] **RED** — `backend/tests/unit/knowledge/test_chunker.py`:
```python
from app.knowledge.chunker import chunk_document
from app.knowledge.tokenizer_window import WindowTokenizer


def test_no_chunk_exceeds_max_tokens() -> None:
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")  # char fallback
    # ~4000 chars of prose → must split into <=max_tokens chunks.
    text = ("The orders table stores each purchase. " * 200)
    chunks = chunk_document(
        content=text, file_path="doc.md", doc_type="markdown", max_tokens=128, tokenizer=tk
    )
    assert len(chunks) >= 2
    for c in chunks:
        assert tk.count_tokens(c.content) <= 128, tk.count_tokens(c.content)


def test_small_doc_single_chunk() -> None:
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    chunks = chunk_document(
        content="short doc", file_path="d.md", doc_type="markdown", max_tokens=128, tokenizer=tk
    )
    assert len(chunks) == 1
    assert chunks[0].metadata["source_path"] == "d.md"


def test_default_model_is_512_ctx() -> None:
    from app.config import settings
    assert settings.chroma_embedding_model == "BAAI/bge-base-en-v1.5"
    assert settings.embedder_max_tokens == 512
```
- [ ] Run: `cd backend && .venv/bin/pytest tests/unit/knowledge/test_chunker.py -v` → **fails**.
- [ ] **GREEN** — edit `backend/app/config.py`:
  - Change line 90 `chroma_embedding_model: str = ""` → `chroma_embedding_model: str = "BAAI/bge-base-en-v1.5"`
  - Add directly below it:
```python
    # Embedder token window. Chunking sizes to this via a real tokenizer
    # (CODEIDX-C1/C2). Must match chroma_embedding_model's max_seq_length —
    # bge-base-en-v1.5 = 512. Changing chroma_embedding_model REQUIRES a full
    # re-embed (see T3 reindex). A startup check warns on mismatch.
    embedder_max_tokens: int = 512
```
- [ ] Edit `backend/app/knowledge/chunker.py`:
  - Replace the module constants block (lines 10-13) — keep `OVERLAP_CHARS`, drop `APPROX_CHARS_PER_TOKEN`, and stop hardcoding `MAX_CHUNK_TOKENS`:
```python
TARGET_CHUNK_FRACTION = 0.55   # target chunk ≈ 55% of the window (headroom for overlap)
OVERLAP_TOKENS = 40
```
  - Rewrite `chunk_document` to size on real tokens: resolve `max_tokens`/`tokenizer` from settings when not passed, split at boundaries (`_split_at_boundaries` unchanged), merge/split by **token count** using `tokenizer.count_tokens`, and truncate any residual oversize with `tokenizer.truncate_to_tokens(section, max_tokens)`. The overlap prefix becomes token-bounded via `tokenizer.truncate_to_tokens(prev, OVERLAP_TOKENS)` taken from the tail (reverse: `prev[-N:]` then truncate). Preserve the `Chunk(content, metadata)` shape and `chunk_index`/`source_path`/`doc_type` metadata exactly as today.
  - Concretely, the token-aware merge/split helpers replace char math:
```python
def _merge_small_sections(sections, target_tokens, tokenizer):
    merged, buf = [], ""
    for s in sections:
        if buf and tokenizer.count_tokens(buf) + tokenizer.count_tokens(s) > target_tokens:
            merged.append(buf); buf = s
        else:
            buf = buf + s if buf else s
    if buf:
        merged.append(buf)
    return merged

def _split_large_section(text, max_tokens, tokenizer):
    paras = re.split(r"\n\n+", text)
    parts, cur = [], ""
    for p in paras:
        cand = (cur + "\n\n" + p) if cur else p
        if cur and tokenizer.count_tokens(cand) > max_tokens:
            parts.append(cur); cur = p
        else:
            cur = cand
    if cur:
        parts.append(cur)
    # Any single paragraph still over the window → hard truncate to the window.
    return [
        (p if tokenizer.count_tokens(p) <= max_tokens else tokenizer.truncate_to_tokens(p, max_tokens))
        for p in parts
    ]
```
- [ ] Run the test → **passes**. Then run `cd backend && .venv/bin/pytest tests/unit/knowledge/ -v` to confirm no regression in nearby tests.
- [ ] **DoD:** tests green; `ruff` clean; `pipeline_runner` call sites still type-check (`mypy app/knowledge/chunker.py app/knowledge/pipeline_runner.py --ignore-missing-imports`).
- [ ] Commit: `feat(knowledge): size chunks to embedder token window; default bge-base-en-v1.5 (CODEIDX-C1)`

---

## Task T3 — CODEIDX-C1: startup window-mismatch check + reindex/migration path

`depends:[T2]`

**Scene:** The spec (§1, §8, §2 C-E) is explicit: **changing the embedding model forces a full re-embed** — ChromaDB resolves the EF at collection create and does not re-embed existing rows on model change, so a project indexed under `all-MiniLM-L6-v2` (256-ctx) keeps its old truncated vectors under a new EF. Since the default flips in T2, existing prod collections are now stale. Ship (a) a startup log warning when `embedder_max_tokens` and the loaded model's `max_seq_length` disagree, and (b) a one-shot reindex trigger the operator runs post-deploy: a management function `queue_embedding_reindex(project_ids)` that deletes each project's Chroma collection and re-enqueues `run_repo_index` (full, not incremental). No Alembic migration is needed (Chroma is not in Postgres), but the reindex is a **required post-deploy human step** (see Human Steps).

**Files:**
- `backend/app/knowledge/vector_store.py` (add `expected_window` mismatch warning on `_get_embedding_function`)
- NEW `backend/app/services/embedding_reindex.py`
- NEW `backend/tests/unit/knowledge/test_embedding_reindex.py`
- `CLAUDE.md` (document the reindex requirement under "Knowledge indexing pipeline")

**Interfaces:**
```python
# app/services/embedding_reindex.py
async def queue_embedding_reindex(project_ids: list[str]) -> dict[str, str]:
    """Drop each project's Chroma collection and enqueue a FULL repo re-index.
    Returns {project_id: 'queued'|'error:<msg>'}. Best-effort per project."""
```

**Steps:**

- [ ] **RED** — `backend/tests/unit/knowledge/test_embedding_reindex.py`:
```python
import app.services.embedding_reindex as er


async def test_queue_reindex_drops_collection_and_enqueues(monkeypatch) -> None:
    dropped: list[str] = []
    enqueued: list[tuple[str, bool]] = []

    class _VS:
        def delete_collection(self, pid): dropped.append(pid)

    async def _enqueue(project_id, *, full): enqueued.append((project_id, full))

    monkeypatch.setattr(er, "_get_vector_store", lambda: _VS())
    monkeypatch.setattr(er, "_enqueue_repo_index", _enqueue)

    out = await er.queue_embedding_reindex(["p1", "p2"])
    assert out == {"p1": "queued", "p2": "queued"}
    assert dropped == ["p1", "p2"]
    assert enqueued == [("p1", True), ("p2", True)]


async def test_queue_reindex_isolates_per_project_failure(monkeypatch) -> None:
    class _VS:
        def delete_collection(self, pid):
            if pid == "bad":
                raise RuntimeError("boom")

    async def _enqueue(project_id, *, full): ...

    monkeypatch.setattr(er, "_get_vector_store", lambda: _VS())
    monkeypatch.setattr(er, "_enqueue_repo_index", _enqueue)
    out = await er.queue_embedding_reindex(["ok", "bad"])
    assert out["ok"] == "queued"
    assert out["bad"].startswith("error:")
```
- [ ] Run → **fails** (module missing).
- [ ] **GREEN** — create `backend/app/services/embedding_reindex.py` with `queue_embedding_reindex`, plus small seams `_get_vector_store()` (returns the app `VectorStore` singleton) and `_enqueue_repo_index(project_id, *, full)` (routes through `app.core.task_queue`/worker `run_repo_index` with `full=True`). Guard each project in try/except; on failure record `f"error:{exc}"[:200]` and log with `exc_info=True`.
- [ ] Add the mismatch warning to `vector_store.py::_get_embedding_function`: after constructing `SentenceTransformerEmbeddingFunction`, best-effort read `getattr(ef, "models", None)` or load `sentence_transformers.SentenceTransformer(model_name).max_seq_length`; if it disagrees with `settings.embedder_max_tokens`, `logger.warning("embedder window mismatch: model=%s window=%s configured=%s — reindex required", ...)`. Wrap in try/except so a load failure never breaks startup.
- [ ] Run the test → **passes**.
- [ ] Document in `CLAUDE.md` (Knowledge indexing pipeline section): a one-line note "Changing `chroma_embedding_model` requires a full re-embed — run `queue_embedding_reindex(project_ids)` post-deploy; ChromaDB does not re-embed existing rows on model change."
- [ ] **DoD:** tests green; `ruff` clean; CLAUDE.md updated.
- [ ] Commit: `feat(knowledge): embedding reindex trigger + startup window-mismatch warning (CODEIDX-C1)`

---

## Task T4 — CODEIDX-C3: raw-code symbol embedding path

`depends:[T1,T2]`

**Scene:** Today only LLM-generated schema *prose* is embedded (via `doc_generator.py` → `chunk_document`); raw source is truncated at 12k chars before the LLM and symbol bodies are never retrievable (`pipeline_runner.py:1056`, `doc_generator.py:60 MAX_CONTENT_LENGTH`). The AST layer already extracts `Symbol` (uid, kind, name, file_path, start_line, end_line, language, signature, docstring) into `state.parsed_files` during `_run_ast_parse` (line 1371). Add a **raw-code symbol embedding path**: for each parsed symbol, read its source span from disk and upsert a chunk with C-E metadata `{path, symbol, language, start_line, end_line, kind}`. This runs inside the embed stage, gated on `hybrid_retrieval_enabled` (always-on default) so code-Q&A retrieval sees actual code, not just prose.

**Files:**
- NEW `backend/app/knowledge/code_symbol_chunker.py`
- `backend/app/knowledge/pipeline_runner.py` (invoke after `_run_ast_parse`, before/alongside embed)
- NEW `backend/tests/unit/knowledge/test_code_symbol_chunker.py`

**Interfaces (C-E metadata verbatim):**
```python
# app/knowledge/code_symbol_chunker.py
from app.knowledge.ast_parser import Symbol
from app.knowledge.chunker import Chunk

def symbol_chunks(
    *,
    repo_dir: str,
    parsed_files: dict[str, "ParsedFile"],   # rel_path -> ParsedFile
    commit_sha: str,
    max_tokens: int,
    tokenizer,
) -> list[Chunk]:
    """One Chunk per code symbol whose source span fits/truncates to the window.
    metadata = {source_path, doc_type='code_symbol', path, symbol, language,
                start_line, end_line, kind, commit_sha, indexed_at}."""
```

**Steps:**

- [ ] **RED** — `backend/tests/unit/knowledge/test_code_symbol_chunker.py`:
```python
from dataclasses import dataclass, field

from app.knowledge.ast_parser import Symbol
from app.knowledge.code_symbol_chunker import symbol_chunks
from app.knowledge.tokenizer_window import WindowTokenizer


@dataclass
class _PF:
    language: str
    symbols: list = field(default_factory=list)


def test_symbol_chunk_carries_ast_span_metadata(tmp_path) -> None:
    src = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
    (tmp_path / "m.py").write_text(src, encoding="utf-8")
    pf = _PF(
        language="python",
        symbols=[
            Symbol(uid="python:m.py:function:alpha:1", kind="function", name="alpha",
                   file_path="m.py", start_line=1, end_line=2, language="python"),
            Symbol(uid="python:m.py:function:beta:5", kind="function", name="beta",
                   file_path="m.py", start_line=5, end_line=6, language="python"),
        ],
    )
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    chunks = symbol_chunks(
        repo_dir=str(tmp_path), parsed_files={"m.py": pf},
        commit_sha="abc123", max_tokens=256, tokenizer=tk,
    )
    assert len(chunks) == 2
    a = next(c for c in chunks if c.metadata["symbol"] == "alpha")
    assert "return 1" in a.content
    assert a.metadata == {
        "source_path": "m.py", "doc_type": "code_symbol", "path": "m.py",
        "symbol": "alpha", "language": "python", "start_line": 1, "end_line": 2,
        "kind": "function", "commit_sha": "abc123",
        **{k: a.metadata[k] for k in a.metadata if k == "indexed_at"},
    }
    assert "indexed_at" in a.metadata


def test_oversize_symbol_is_truncated_not_dropped(tmp_path) -> None:
    body = "    x = 1\n" * 2000
    src = "def big():\n" + body
    (tmp_path / "b.py").write_text(src, encoding="utf-8")
    pf = _PF(language="python", symbols=[
        Symbol(uid="u", kind="function", name="big", file_path="b.py",
               start_line=1, end_line=2001, language="python"),
    ])
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    chunks = symbol_chunks(repo_dir=str(tmp_path), parsed_files={"b.py": pf},
                           commit_sha="s", max_tokens=64, tokenizer=tk)
    assert len(chunks) == 1
    assert tk.count_tokens(chunks[0].content) <= 64
```
- [ ] Run → **fails**.
- [ ] **GREEN** — create `backend/app/knowledge/code_symbol_chunker.py`. For each `(rel_path, pf)` and each `sym` in `pf.symbols`: read the file text (best-effort, skip on IOError), slice lines `[start_line-1:end_line]`, build content, `tokenizer.truncate_to_tokens(content, max_tokens)` if over, skip empty. Metadata exactly as in the interface (`source_path == path == rel_path`; `indexed_at = datetime.now(UTC).isoformat()`). Cache file reads per path within the call. Never raise — per-file/per-symbol failures are logged at debug and skipped.
- [ ] Wire into `pipeline_runner.py`: in the embed stage (after docs are generated and `state.parsed_files` is populated), when `settings.hybrid_retrieval_enabled`, call `symbol_chunks(...)` with `max_tokens=settings.embedder_max_tokens`, `tokenizer=get_tokenizer(settings.chroma_embedding_model)`, then `self._vector_store.add_documents(project_id, doc_ids=[f"sym:{c.metadata['path']}:{c.metadata['start_line']}:{c.metadata['symbol']}" for c in chunks], documents=[...], metadatas=[...])` via `asyncio.to_thread`. Delete stale symbol chunks per path first is already covered by `delete_by_source_path` (they share `source_path`). Emit a tracker line `embed_symbols completed N symbols`.
- [ ] Run the test → **passes**; then `cd backend && .venv/bin/pytest tests/unit/knowledge/ -q`.
- [ ] **DoD:** tests green; `ruff` clean; `mypy` clean on the two edited files.
- [ ] Commit: `feat(knowledge): raw-code symbol embedding path from AST spans (CODEIDX-C3)`

---

## Task T5 — RET-R2: ContextPack rag_chunks through HybridRetriever

`depends:[T2]`

**Scene:** `KnowledgeCatalogService._rag_artifacts` (line 440-473) queries `self._vector_store.query(...)` — **dense-only ChromaDB**, bypassing `HybridRetriever` (BM25+RRF+rerank). This drops exact-identifier recall. Route rag artifacts through a hybrid retriever, degrading to dense-only when hybrid is disabled/unavailable (vision #5). The service is sync at this method; add an async `_rag_artifacts_async` and call it from `get_context_pack` (which is already async).

**Files:**
- `backend/app/services/knowledge_catalog_service.py`
- `backend/tests/unit/test_knowledge_catalog_rag.py` (new)

**Interfaces (consume existing):**
```python
# app/knowledge/hybrid_retriever.py — HybridRetriever.query(project_id, query_text, *, k, where=None) -> list[HybridResult]
# HybridResult has .doc_id, .document, .metadata, .rrf_score
```

**Steps:**

- [ ] **RED** — `backend/tests/unit/test_knowledge_catalog_rag.py` (fixture-corpus precision assertion): construct a `KnowledgeCatalogService` with an injected fake hybrid retriever returning a labelled ordering; assert the produced `rag_chunks` preserve hybrid order and carry `commit_sha`/`indexed_at` provenance from metadata.
```python
from app.knowledge.context_pack import Artifact
from app.services.knowledge_catalog_service import KnowledgeCatalogService


class _FakeHybrid:
    async def query(self, project_id, query_text, *, k, where=None):
        from app.knowledge.hybrid_retriever import HybridResult
        # 'auth' query: exact-identifier doc must rank first (BM25 leg).
        return [
            HybridResult(doc_id="c1", document="def authenticate(): ...",
                         metadata={"source_path": "auth.py", "commit_sha": "sha1",
                                   "indexed_at": "2026-07-01T00:00:00+00:00"}, rrf_score=0.9),
            HybridResult(doc_id="c2", document="unrelated helper",
                         metadata={"source_path": "util.py"}, rrf_score=0.1),
        ]


async def test_rag_artifacts_use_hybrid_order_and_provenance() -> None:
    svc = KnowledgeCatalogService(vector_store=object())
    svc._hybrid = _FakeHybrid()  # seam injected in impl
    arts = await svc._rag_artifacts_async(project_id="p", question="authenticate", n_results=2)
    assert [a.payload["file_path"] for a in arts] == ["auth.py", "util.py"]
    assert arts[0].provenance["commit_sha"] == "sha1"
    assert arts[0].freshness["indexed_at"] == "2026-07-01T00:00:00+00:00"
    assert all(isinstance(a, Artifact) and a.type == "rag_chunk" for a in arts)
```
- [ ] Run → **fails**.
- [ ] **GREEN** — in `knowledge_catalog_service.py`: add a lazily-built `self._hybrid` (mirror `ContextLoader._get_hybrid_retriever`: `HybridRetriever(bm25=BM25Index(settings.bm25_data_dir), vector_store=self._vector_store, rrf_k=settings.hybrid_rrf_k, min_score=settings.hybrid_min_score, chroma_max_distance=settings.rag_relevance_threshold, reranker=build_reranker(enabled=settings.reranker_enabled, model_name=settings.reranker_model), rerank_candidates=settings.reranker_candidates)`). Add `async def _rag_artifacts_async(self, *, project_id, question, n_results)` that: if `settings.hybrid_retrieval_enabled` → `fused = await self._hybrid.query(project_id, question, k=max(n_results, settings.hybrid_k))`, map top `n_results` to `Artifact(type="rag_chunk", ...)` reading `metadata.commit_sha`/`indexed_at`/`source_path`; else fall back to the existing sync `_rag_artifacts`. In `get_context_pack`, replace the `pack.rag_chunks = self._rag_artifacts(...)` call with `await self._rag_artifacts_async(...)`.
- [ ] Run the test → **passes**; run existing `test_knowledge_catalog*` if any (`cd backend && .venv/bin/pytest -k knowledge_catalog -q`).
- [ ] **DoD:** green; `ruff` clean; degradation path covered (add a test asserting fallback when `hybrid_retrieval_enabled=False` via monkeypatch of settings → uses `_vector_store.query`).
- [ ] Commit: `fix(knowledge): route ContextPack rag_chunks through HybridRetriever (RET-R2)`

---

## Task T6 — RET-R3: greedy relevance×confidence token-budget packing

`depends:[]`

**Scene:** `ContextPack.token_budget` is recorded but never enforced (`context_pack.py:76`, `knowledge_catalog_service.py:197`); there is no global most-relevant-first ordering. Add a pure packer that, given a `ContextPack` and a tokenizer + budget, orders all artifacts by `relevance × confidence` and greedily fills to `token_budget["total"]`, dropping the tail. `relevance` is derived from each artifact's rank within its section (rag_chunks carry an `rrf_score` or position; tables carry `relevance_score`); default relevance 1.0 when unknown. This lives in a NEW pure module so it is testable without I/O and does not collide with W3's orchestrator edits.

**Files:**
- NEW `backend/app/knowledge/context_pack_renderer.py`
- NEW `backend/tests/unit/knowledge/test_context_pack_renderer.py`

**Interfaces:**
```python
# app/knowledge/context_pack_renderer.py
from app.knowledge.context_pack import Artifact, ContextPack

def pack_by_budget(
    pack: ContextPack, *, budget_tokens: int, tokenizer,
) -> list[Artifact]:
    """Return artifacts greedily selected by (relevance * confidence) desc until
    budget_tokens is exhausted. relevance defaults to artifact.payload.get(
    'relevance', 1.0). Token cost = tokenizer.count_tokens(artifact.summary)."""
```

**Steps:**

- [ ] **RED** — `backend/tests/unit/knowledge/test_context_pack_renderer.py`:
```python
from app.knowledge.context_pack import Artifact, ContextPack
from app.knowledge.context_pack_renderer import pack_by_budget
from app.knowledge.tokenizer_window import WindowTokenizer


def _art(i, conf, rel, summary):
    return Artifact(id=i, type="rag_chunk", title=i, summary=summary,
                    confidence=conf, payload={"relevance": rel})


def test_packs_highest_relevance_times_confidence_first() -> None:
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    pack = ContextPack(project_id="p")
    pack.token_budget = {"total": 20}
    # each summary ~ 30 chars ≈ 10 tokens (fallback ceil(30/3.2)=10).
    pack.rag_chunks = [
        _art("low", 0.2, 1.0, "x" * 30),      # score 0.2
        _art("high", 1.0, 1.0, "y" * 30),     # score 1.0
        _art("mid", 0.5, 1.0, "z" * 30),      # score 0.5
    ]
    out = pack_by_budget(pack, budget_tokens=20, tokenizer=tk)
    # budget fits 2 chunks (~20 tokens): highest two by score.
    assert [a.id for a in out] == ["high", "mid"]


def test_budget_zero_returns_empty() -> None:
    tk = WindowTokenizer("definitely/not-a-real-tokenizer-xyz")
    pack = ContextPack(project_id="p")
    pack.rag_chunks = [_art("a", 1.0, 1.0, "hello")]
    assert pack_by_budget(pack, budget_tokens=0, tokenizer=tk) == []
```
- [ ] Run → **fails**.
- [ ] **GREEN** — implement `pack_by_budget`: flatten `pack.all_artifacts()`, sort by `(-(payload.get('relevance',1.0) * confidence), original_index)` for stable ties, greedily accumulate while running token total + `count_tokens(summary)` ≤ budget, stop at first that would overflow (continue scanning to fit smaller later items? No — spec says greedy fill by score order; stop adding once an item overflows but keep scanning is optional. Implement simple greedy: iterate sorted; add if it fits, else skip and continue — so a smaller lower-ranked item can still fill remaining budget). Return selected in score order.
- [ ] Run → **passes**.
- [ ] **DoD:** green; `ruff` clean; pure module, no imports of I/O.
- [ ] Commit: `feat(knowledge): greedy relevance×confidence token-budget packer (RET-R3)`

---

## Task T7 — RET-R8: render provenance per artifact into the prompt

`depends:[T6]`

**Scene:** `context_loader.load_relevant_knowledge` renders `- [source_path] snippet` only — provenance/trust/freshness never reach the LLM (`context_loader.py:389`, RET-R8). Add a renderer (same NEW module as T6) that turns the packed artifact list into a prompt block with per-artifact provenance in the C-E format `[{source} @ {commit_sha} · {indexed_at} · conf={confidence}]`.

**Files:**
- `backend/app/knowledge/context_pack_renderer.py` (extend)
- `backend/tests/unit/knowledge/test_context_pack_renderer.py` (extend)

**Interfaces (C-E provenance format verbatim):**
```python
def render_context_block(artifacts: list[Artifact]) -> str:
    """Prompt block, one line per artifact:
    - [{source} @ {commit_sha} · {indexed_at} · conf={confidence:.2f}] {summary}
    where source = provenance.source, commit_sha/indexed_at fall back to '—'."""
```

**Steps:**

- [ ] **RED** — extend the test file:
```python
from app.knowledge.context_pack import Artifact
from app.knowledge.context_pack_renderer import render_context_block


def test_render_includes_provenance_per_artifact() -> None:
    a = Artifact(id="1", type="rag_chunk", title="auth.py", summary="does auth",
                 confidence=0.8,
                 provenance={"source": "rag", "commit_sha": "abcdef1"},
                 freshness={"indexed_at": "2026-07-01T00:00:00+00:00"})
    block = render_context_block([a])
    assert "@ abcdef1" in block
    assert "conf=0.80" in block
    assert "2026-07-01T00:00:00+00:00" in block
    assert "does auth" in block


def test_render_missing_provenance_uses_dash() -> None:
    a = Artifact(id="1", type="rule", title="r", summary="s", confidence=1.0)
    block = render_context_block([a])
    assert "@ —" in block
```
- [ ] Run → **fails**.
- [ ] **GREEN** — implement `render_context_block`: for each artifact build `src = a.provenance.get("source","unknown")`, `sha = a.provenance.get("commit_sha") or "—"`, `iat = a.freshness.get("indexed_at") or "—"`, line `f"- [{src} @ {sha} · {iat} · conf={a.confidence:.2f}] {a.summary}"`. Prepend a header `"RELEVANT KNOWLEDGE (traceable):"`. Return `""` for empty input.
- [ ] Run → **passes**.
- [ ] **DoD:** green; `ruff` clean.
- [ ] Commit: `feat(knowledge): render per-artifact provenance into prompt block (RET-R8)`

---

## Task T8 — RET-R1: wire build_context_pack into orchestrator runtime

`depends:[T5,T6,T7]`

**Scene:** `build_context_pack` (`context_loader.py:87`) is never called by the agent runtime — only a read-only UI route (`RET-R1`). Wire it into `_run_unified_agent` **behind `context_planner_enabled`** (default off; T15 flips it under the eval gate). When enabled and it returns a pack, pack it with T6's `pack_by_budget` and render with T7's `render_context_block`, feeding the block into `recent_knowledge`/`recent_learnings` in place of the thin `load_relevant_knowledge` (which stays as the fallback when disabled or the pack is empty/None — vision #5). This edits **one contiguous block** in `orchestrator.py` (lines ~845-864) — flag it to W3 as the only W2-owned edit there.

**Files:**
- `backend/app/agents/orchestrator.py` (lines 845-864 block only)
- `backend/tests/unit/agents/test_orchestrator_context_pack.py` (new)

**Interfaces (consume existing):**
```python
# ContextLoader.build_context_pack(*, project_id, connection_id, question,
#   has_connection, has_repo, estimated_queries, needs_multiple_data_sources) -> ContextPack | None
# pack_by_budget(pack, *, budget_tokens, tokenizer) -> list[Artifact]
# render_context_block(artifacts) -> str
```

**Steps:**

- [ ] **RED** — `backend/tests/unit/agents/test_orchestrator_context_pack.py`: build a minimal orchestrator/`ContextLoader` with `context_planner_enabled=True` (monkeypatch settings) and a fake `build_context_pack` returning a `ContextPack` with two rag chunks + one rule; assert the assembled knowledge text contains the provenance format `@` and that with `context_planner_enabled=False` the code path calls `load_relevant_knowledge` instead. (Mirror the existing orchestrator unit-test harness — check `backend/tests/unit/agents/` for the fixture pattern; if none, test `ContextLoader` in isolation via a new helper method `assemble_knowledge_block`.)
  - Prefer the isolated seam: add `ContextLoader.assemble_knowledge_block(*, project_id, connection_id, question, has_connection, has_repo, estimated_queries, needs_multiple_data_sources, has_kb) -> str | None` that internally decides pack-vs-legacy, and test THAT (keeps orchestrator.py edit to a one-line call, minimizing W3 conflict).
```python
from app.agents.context_loader import ContextLoader


async def test_assemble_uses_context_pack_when_enabled(monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "context_planner_enabled", True)
    monkeypatch.setattr(settings, "context_planner_budget_tokens", 4000)

    loader = ContextLoader(vector_store=object(), tracker=_FakeTracker(),
                           mcp_cache={})

    from app.knowledge.context_pack import Artifact, ContextPack
    pack = ContextPack(project_id="p")
    pack.token_budget = {"total": 4000}
    pack.rag_chunks = [Artifact(id="1", type="rag_chunk", title="auth.py",
                                summary="def authenticate", confidence=0.9,
                                provenance={"source": "rag", "commit_sha": "sha1"},
                                freshness={"indexed_at": "2026-07-01T00:00:00+00:00"})]

    async def _fake_pack(**kw): return pack
    monkeypatch.setattr(loader, "build_context_pack", _fake_pack)

    block = await loader.assemble_knowledge_block(
        project_id="p", connection_id=None, question="authenticate?",
        has_connection=False, has_repo=True, estimated_queries=1,
        needs_multiple_data_sources=False, has_kb=True,
    )
    assert block and "@ sha1" in block and "def authenticate" in block


async def test_assemble_falls_back_to_legacy_when_disabled(monkeypatch) -> None:
    from app.config import settings
    monkeypatch.setattr(settings, "context_planner_enabled", False)
    loader = ContextLoader(vector_store=object(), tracker=_FakeTracker(), mcp_cache={})
    called = {"legacy": False}
    async def _legacy(pid, q, **kw):
        called["legacy"] = True
        return "RELEVANT KNOWLEDGE (top documentation snippets):\n- [d] x"
    monkeypatch.setattr(loader, "load_relevant_knowledge", _legacy)
    block = await loader.assemble_knowledge_block(
        project_id="p", connection_id=None, question="q",
        has_connection=False, has_repo=True, estimated_queries=1,
        needs_multiple_data_sources=False, has_kb=True,
    )
    assert called["legacy"] is True and block.startswith("RELEVANT KNOWLEDGE")
```
  (Define `_FakeTracker` with an async `emit(*a, **k)` no-op at the top of the test file.)
- [ ] Run → **fails**.
- [ ] **GREEN** — add `ContextLoader.assemble_knowledge_block`: if `settings.context_planner_enabled` → call `self.build_context_pack(...)`; if pack not None and not `pack.is_empty()` → `arts = pack_by_budget(pack, budget_tokens=pack.token_budget.get("total", settings.context_planner_budget_tokens), tokenizer=get_tokenizer(settings.chroma_embedding_model))`; return `render_context_block(arts)`. Otherwise (disabled, None, or empty) and `has_kb` → return `await self.load_relevant_knowledge(project_id, question)`. Then in `orchestrator.py` lines 854-863, replace the `if has_kb and context.user_question:` block with a single call to `assemble_knowledge_block(...)` and merge its result into `recent_learnings` exactly as today.
- [ ] Run → **passes**; run `cd backend && .venv/bin/pytest tests/unit/agents/ -k context -q`.
- [ ] **DoD:** green; `ruff` clean; the orchestrator diff is a single-block replacement (note in commit body: "W2-owned edit in orchestrator.py; W3 owns the rest").
- [ ] Commit: `feat(agents): wire ContextPack into orchestrator behind context_planner_enabled (RET-R1)`

---

## Task T9 — RET-R4: retrieval_degraded event + metric

`depends:[]`

**Scene:** In `HybridRetriever.query`, when the BM25 leg returns `[]` (missing snapshot on ephemeral Heroku disk) while Chroma has hits (or vice-versa), retrieval silently degrades to single-leg with **no signal** (`hybrid_retriever.py:118`, RET-R4). Emit W0's `retrieval_degraded{leg, reason}` WorkflowTracker event + increment `retrieval_degraded_total` when exactly one leg is empty and the other non-empty. `HybridRetriever` currently has no tracker — inject an optional `tracker` + `wf_id` param plumbed from callers; when absent, still increment the metric (metric is global via `get_metrics_collector()`).

**Files:**
- `backend/app/knowledge/hybrid_retriever.py`
- `backend/tests/unit/knowledge/test_hybrid_retriever_degraded.py` (new)

**Interfaces (consume W0):**
```python
# get_metrics_collector().inc("retrieval_degraded_total", leg=<"bm25"|"chroma">, reason="empty_leg")
# tracker.emit(wf_id, "retrieval_degraded", "degraded", detail, leg=..., reason=...)  # when tracker+wf_id present
```

**Steps:**

- [ ] **RED** — `backend/tests/unit/knowledge/test_hybrid_retriever_degraded.py`:
```python
from app.core.metrics import get_metrics_collector
from app.knowledge.hybrid_retriever import HybridRetriever


class _BM25Empty:
    def query(self, project_id, q, n): return []


class _ChromaHits:
    def query(self, project_id, q, n, where=None):
        return [{"id": "d1", "document": "hit", "metadata": {}}]


async def test_emits_degraded_when_one_leg_empty(monkeypatch) -> None:
    hr = HybridRetriever(bm25=_BM25Empty(), vector_store=_ChromaHits())
    before = get_metrics_collector().snapshot_counters("retrieval_degraded_total")
    out = await hr.query("proj", "auth", k=5)
    after = get_metrics_collector().snapshot_counters("retrieval_degraded_total")
    assert out  # still returns chroma-only results (graceful)
    assert sum(after.values()) == sum(before.values()) + 1


async def test_no_degraded_when_both_have_hits() -> None:
    class _BM25Hits:
        def query(self, p, q, n): return [{"id": "d1", "document": "x", "metadata": {}}]
    hr = HybridRetriever(bm25=_BM25Hits(), vector_store=_ChromaHits())
    before = sum(get_metrics_collector().snapshot_counters("retrieval_degraded_total").values())
    await hr.query("proj", "auth", k=5)
    after = sum(get_metrics_collector().snapshot_counters("retrieval_degraded_total").values())
    assert after == before
```
  (Confirm `snapshot_counters(prefix)` exists — it does, `metrics.py:132`.)
- [ ] Run → **fails**.
- [ ] **GREEN** — in `hybrid_retriever.py`: add `tracker=None, wf_id=""` to `__init__` (store); after the `await asyncio.gather(...)` in `query`, compute `bm25_empty = not bm25_results`, `chroma_empty = not chroma_results`; if `bm25_empty ^ chroma_empty` (exactly one empty): `leg = "bm25" if bm25_empty else "chroma"`; `get_metrics_collector().inc("retrieval_degraded_total", leg=leg, reason="empty_leg")`; if `self._tracker and self._wf_id` → best-effort `await self._tracker.emit(self._wf_id, "retrieval_degraded", "degraded", f"{leg} leg empty; using other leg only", leg=leg, reason="empty_leg")` in try/except. Do not change fusion behaviour otherwise.
- [ ] Run → **passes**.
- [ ] **DoD:** green; `ruff` clean; metric registered (grep `retrieval_degraded_total` appears in `/api/metrics` snapshot path — it does via `snapshot_counters`). Add `retrieval_degraded_total` to the metrics doc line in `CLAUDE.md` LLM-routing/observability section if not already present (W0 added it — verify; skip if present).
- [ ] Commit: `feat(knowledge): emit retrieval_degraded event + metric on single-leg retrieval (RET-R4)`

---

## Task T10 — RET-R5: tighten relevance floor + validate against retrieval-eval

`depends:[]`

**Scene:** `rag_relevance_threshold=0.8` ≈ cosine similarity 0.2 (near-zero floor); `hybrid_min_score=0.01` is below a rank-30 RRF contribution (`config.py:267,469`, RET-R5). Tighten to a real floor and **prove no recall regression** on the golden set. Spec §8 flags "exact cosine-distance→similarity" as needs-validation — a W0 characterization test should already assert the distance semantics; this task consumes that (cosine distance in `[0,2]`, similarity = 1 − distance, so distance ≤ 0.45 ⇔ sim ≥ 0.55). Set `rag_relevance_threshold=0.45`, `hybrid_min_score=0.03`.

**Files:**
- `backend/app/config.py`
- `backend/.env.example`
- `backend/tests/unit/test_retrieval_floor.py` (new)
- Validate (not modify) `backend/tests/unit/test_retrieval_eval.py`

**Steps:**

- [ ] **RED** — `backend/tests/unit/test_retrieval_floor.py`: a fixture-corpus precision test — build a `HybridRetriever` over a tiny in-memory-ish corpus (use a fake vector_store returning hits with known `distance` values and a fake BM25); assert that with `chroma_max_distance=0.45` a hit at distance 0.6 is dropped and a hit at distance 0.3 is kept, and precision@k on the labelled set is ≥ 0.5 (relevant hits survive, noise dropped).
```python
from app.knowledge.hybrid_retriever import HybridRetriever


class _BM25Empty:
    def query(self, p, q, n): return []


class _Chroma:
    def __init__(self, hits): self._hits = hits
    def query(self, p, q, n, where=None): return self._hits


async def test_distance_floor_drops_low_relevance() -> None:
    hits = [
        {"id": "relevant", "document": "orders total revenue", "metadata": {}, "distance": 0.30},
        {"id": "noise", "document": "unrelated", "metadata": {}, "distance": 0.60},
    ]
    hr = HybridRetriever(bm25=_BM25Empty(), vector_store=_Chroma(hits),
                         chroma_max_distance=0.45)
    out = await hr.query("p", "revenue", k=10)
    ids = [r.doc_id for r in out]
    assert "relevant" in ids
    assert "noise" not in ids
    # precision@k on the single labelled relevant doc:
    precision = sum(1 for i in ids if i == "relevant") / max(len(ids), 1)
    assert precision >= 0.5


def test_config_floor_values() -> None:
    from app.config import settings
    assert settings.rag_relevance_threshold == 0.45
    assert settings.hybrid_min_score == 0.03
```
- [ ] Run → **fails**.
- [ ] **GREEN** — edit `config.py`: `rag_relevance_threshold: float = 0.45` (line 267), `hybrid_min_score: float = 0.03` (line 469); update the inline comments to reflect the new semantics. Mirror in `backend/.env.example` if the keys are documented there (add `RAG_RELEVANCE_THRESHOLD=0.45`, `HYBRID_MIN_SCORE=0.03` with comments).
- [ ] Run `test_retrieval_floor.py` → **passes**.
- [ ] **Validate no regression:** `cd backend && .venv/bin/pytest tests/unit/test_retrieval_eval.py -v` → must still pass (the oracle/broken gates are floor-agnostic; the golden set is retriever-injected so config floors don't affect it — but confirm). If the eval harness ever wires the real retriever, re-run with tightened floors and confirm `hit_at_k ≥ 0.70`.
- [ ] **DoD:** both tests green; `ruff` clean; `.env.example` updated.
- [ ] Commit: `perf(knowledge): tighten RAG relevance floor + min-score, validate vs eval (RET-R5)`

---

## Task T11 — RET-R9 + DBIDX-D7: FK-aware schema retrieval + splice distinct/numeric notes

`depends:[T13]` and **`depends:[W4]`** (schema-capture fields)

**Scene (W4 dependency — gate the test):** The schema BM25 doc (`schema_retriever.py:_build_schema_doc`, line 75) has **no FK/relationships** and **no distinct-values/numeric-format notes**, so join/bridge tables and value-level questions (`status='shipped'`) under-retrieve (`RET-R9`, `DBIDX-D7`). W4 lands the capture: `DbIndex.column_distinct_values_json` + `numeric_format_notes` (present today) and connector `SchemaInfo.foreign_keys` (present today live). **Before running the impl test, verify these fields exist** (`grep -n "column_distinct_values_json\|numeric_format_notes" backend/app/models/db_index.py`). If W4's C-D column additions (`ColumnInfo.distinct_values` etc.) are the source, gate the FK-hop expansion on `SchemaInfo.foreign_keys` being populated. Two changes: (1) splice distinct-values + numeric-format notes into `_build_schema_doc`; (2) after BM25 retrieval, expand the retrieved table set **one FK hop** (add tables directly FK-referenced by any retrieved table) before the `sql_agent_max_context_tables` cap in `sql_agent._build_query_context`.

**Files:**
- `backend/app/knowledge/schema_retriever.py` (`_build_schema_doc` + a new `expand_fk_hop` helper)
- `backend/app/agents/sql_agent.py` (`_build_query_context` retrieval union block, lines 1145-1177)
- `backend/tests/unit/knowledge/test_schema_retriever_fk.py` (new)

**Interfaces:**
```python
# schema_retriever.py — new pure helper (testable without BM25):
@staticmethod
def _build_schema_doc(entry: DbIndex) -> str:  # extend: append distinct + numeric lines
    ...

def expand_fk_hop(
    selected: list[str],                 # lowercased table names, in order
    fk_edges: dict[str, list[str]],      # table -> [referenced tables] (lowercased)
    *, max_tables: int,
) -> list[str]:
    """Append one-hop FK neighbours of selected tables (dedup, order-stable)
    until max_tables. Returns the expanded ordered list."""
```

**Steps:**

- [ ] **Pre-check (W4 gate):** `grep -n "column_distinct_values_json\|numeric_format_notes" backend/app/models/db_index.py` → must print both. `grep -n "foreign_keys" backend/app/connectors/base.py` → must print. If missing, W2 T11 is BLOCKED on W4 — report NEEDS_CONTEXT.
- [ ] **RED** — `backend/tests/unit/knowledge/test_schema_retriever_fk.py`:
```python
from types import SimpleNamespace

from app.knowledge.schema_retriever import SchemaRetriever, expand_fk_hop


def _entry(name, notes=None, distinct=None, numeric=None):
    import json
    return SimpleNamespace(
        table_name=name, table_schema="public", business_description="",
        data_patterns="", query_hints="",
        column_notes_json=json.dumps(notes or {}),
        column_distinct_values_json=json.dumps(distinct or {}),
        numeric_format_notes=json.dumps(numeric or {}),
        relevance_score=3, is_active=True, row_count=10, connection_id="c",
    )


def test_schema_doc_splices_distinct_and_numeric() -> None:
    e = _entry("orders", notes={"status": "order state"},
               distinct={"status": ["shipped", "pending", "cancelled"]},
               numeric={"amount": "USD cents, integer"})
    doc = SchemaRetriever._build_schema_doc(e)
    assert "shipped" in doc and "pending" in doc          # value-level retrievable
    assert "USD cents" in doc                              # numeric format retrievable


def test_expand_fk_hop_adds_referenced_tables_order_stable() -> None:
    selected = ["orders"]
    fk_edges = {"orders": ["customers", "line_items"], "customers": ["regions"]}
    out = expand_fk_hop(selected, fk_edges, max_tables=15)
    assert out == ["orders", "customers", "line_items"]   # ONE hop only, no regions


def test_expand_fk_hop_respects_cap() -> None:
    out = expand_fk_hop(["a"], {"a": ["b", "c", "d"]}, max_tables=2)
    assert out == ["a", "b"]
```
- [ ] Run → **fails**.
- [ ] **GREEN** — in `schema_retriever.py`:
  - Extend `_build_schema_doc`: after column notes, parse `column_distinct_values_json` (dict[col->list]) and append `f"{col} values: {', '.join(vals[:20])}"` per column with values; parse `numeric_format_notes` and append `f"{col} format: {note}"`. Guard JSON parse in try/except (mirror existing).
  - Add module-level `def expand_fk_hop(selected, fk_edges, *, max_tables)`: copy `selected`, iterate a snapshot of `selected` adding each `neighbour` in `fk_edges.get(t, [])` if not seen and `len < max_tables`; return.
- [ ] In `sql_agent._build_query_context` (line ~1164 region): after building `retrieved` (BM25 ranked, lowercased names) and before the `retrieved + safety_net` union, build `fk_edges` from the live `schema.tables` (`{t.name.lower(): [fk.<target_table>.lower() for fk in t.foreign_keys]}`), and expand: `retrieved_names = expand_fk_hop([e.table_name.lower() for e in retrieved], fk_edges, max_tables=max_tables)`, then map back to entries via `entries_by_name` preserving order. Keep the safety-net union + cap logic. (Note: `schema` is fetched later at line 1181 today — move the `schema`/`schema_map` fetch up so `fk_edges` is available, or fetch FK edges from `DbIndex` if W4 persists them; prefer the live `schema` which already has `foreign_keys`.)
- [ ] Run the unit test → **passes**. Then run `cd backend && .venv/bin/pytest -k "schema_retriev or sql_agent" -q` to confirm no regression.
- [ ] **DoD:** green; `ruff` clean; `mypy` clean on both edited files.
- [ ] Commit: `feat(knowledge): FK-hop schema expansion + splice distinct/numeric notes (RET-R9, DBIDX-D7)`

---

## Task T12 — RET-R10: relevance floor on safety-net tables

`depends:[T11]`

**Scene:** The safety net appends **all** `relevance_score >= 2` active tables (`sql_agent.py:1152`); on a small DB this dominates the 15-slot budget with noise, crowding out FK-expanded/retrieved tables (`RET-R10`). Raise the safety-net floor and **reserve slots for retrieved+FK tables first** so the safety net only backfills remaining slots.

**Files:**
- `backend/app/agents/sql_agent.py` (safety-net block, lines 1145-1177)
- `backend/tests/unit/agents/test_sql_agent_safety_net.py` (new) — or extend an existing sql_agent test file if present.

**Steps:**

- [ ] **RED** — write a fixture test that constructs the union logic in isolation (extract the union into a pure staticmethod `_union_context_tables(retrieved_names, safety_entries, *, max_tables, safety_floor)` to make it testable) and assert: given 3 retrieved tables and 20 safety-net tables (relevance 2-3), the result puts all 3 retrieved first and backfills to `max_tables=15` with only the highest-relevance safety-net tables (floor applied — a relevance-2 table is dropped in favour of relevance-4 when over budget).
```python
from app.agents.sql_agent import SQLAgent


def test_retrieved_reserved_then_safety_backfill() -> None:
    retrieved = ["orders", "customers", "line_items"]
    safety = [("t%d" % i, 2 + (i % 3)) for i in range(20)]  # (name, relevance)
    out = SQLAgent._union_context_tables(retrieved, safety, max_tables=15, safety_floor=3)
    assert out[:3] == ["orders", "customers", "line_items"]
    assert len(out) == 15
    # only relevance>=safety_floor from the safety net were used to backfill:
    used_safety = set(out[3:])
    assert all(rel >= 3 for name, rel in safety if name in used_safety)
```
- [ ] Run → **fails**.
- [ ] **GREEN** — extract `SQLAgent._union_context_tables(retrieved_names, safety_entries, *, max_tables, safety_floor)`: start with dedup'd `retrieved_names` (order-stable, capped), then append safety-net names sorted by relevance desc, only those with `relevance >= safety_floor`, until `max_tables`. Add config `sql_agent_safety_net_min_relevance: int = 3` in `config.py` and pass it. Rewire `_build_query_context` to call this helper with `safety_entries = [(e.table_name.lower(), e.relevance_score) for e in all_entries if e.is_active]`.
- [ ] Run → **passes**; `cd backend && .venv/bin/pytest -k sql_agent -q`.
- [ ] **DoD:** green; `ruff` clean; config key documented in `.env.example` + CLAUDE.md flag table.
- [ ] Commit: `fix(agents): relevance floor + reserve slots on schema safety net (RET-R10)`

---

## Task T13 — Reranker: use CrossEncoder.rank(query, docs)

`depends:[]`

**Scene:** `CrossEncoderReranker._score_sync` uses `self._model.predict(pairs)` then a manual `sorted(...)` (reranker.py:123-142). Spec §1 confirms `CrossEncoder.rank(query, docs)` returns a **sorted** `[{corpus_id, score}, ...]` — use it to eliminate the manual-sort/sign assumption (`RET-R14`). Keep the stub-model tests passing by supporting a `rank`-capable model and falling back to `predict` when `rank` is absent (some stub models in tests only implement `predict`).

**Files:**
- `backend/app/knowledge/reranker.py`
- `backend/tests/unit/test_reranker.py` (extend — do NOT break existing tests)

**Interfaces (C-E / Context7 verbatim):**
```python
# CrossEncoder.rank(query, documents, return_documents=False, top_k=None)
#   -> list[{"corpus_id": int, "score": float}] sorted desc by score.
```

**Steps:**

- [ ] **RED** — add to `test_reranker.py`:
```python
@pytest.mark.asyncio
async def test_uses_rank_when_model_supports_it() -> None:
    rr = CrossEncoderReranker("stub")

    class _RankModel:
        def rank(self, query, documents, return_documents=False, top_k=None):
            # sorted desc by len — mimic sentence-transformers .rank output.
            order = sorted(range(len(documents)), key=lambda i: len(documents[i]), reverse=True)
            return [{"corpus_id": i, "score": float(len(documents[i]))} for i in order]

    rr._model = _RankModel()
    items = [_Result("short"), _Result("the-longest-document"), _Result("medium-doc")]
    out = await rr.rerank("q", items, top_k=3)
    assert [r.document for r in out] == ["the-longest-document", "medium-doc", "short"]
    assert out[0].metadata["rerank_position"] == 1
```
- [ ] Run existing + new: `cd backend && .venv/bin/pytest tests/unit/test_reranker.py -v` → new test **fails** (rank not used).
- [ ] **GREEN** — rewrite `rerank` scoring: if `hasattr(self._model, "rank")` → `results = await asyncio.to_thread(self._model.rank, query, documents, return_documents=False, top_k=None)`; iterate `results` (already sorted) to build `reranked` in order using `item = items[r["corpus_id"]]`, annotate `_annotate(item, r["score"], rank)`, trim to `top_k`. Else keep the existing `predict`+`sorted` path (so `predict`-only stubs still pass). Update the module docstring/`_score_sync` note.
- [ ] Run → all reranker tests **pass** (existing `predict` tests + the new `rank` test).
- [ ] **DoD:** green; `ruff` clean.
- [ ] Commit: `fix(knowledge): use CrossEncoder.rank sorted output in reranker (RET-R14)`

---

## Task T14 — Low batch (RET-R11..R17, CODEIDX-C10/C11/C12/C13/C14/C18/C19/C20/C21)

`depends:[T1,T2,T4,T6,T9,T13]`

**Scene:** Group the Low-severity robustness fixes into one task with one test file. Each is small; do them TDD-style with a focused assertion each. Skip any that a Crit/High task above already subsumed (note it in the commit body).

**Files:**
- `backend/app/knowledge/hybrid_retriever.py`, `bm25_index.py`, `context_loader.py`, `schema_retriever.py`, `chunker.py`, `code_symbol_chunker.py`, `pipeline_runner.py` (embed stage), `vector_store.py`
- `backend/tests/unit/knowledge/test_w2_low_batch.py` (new)

**Items (one checkbox each; write a failing assertion, fix, confirm):**
- [ ] **RET-R11** — fusion pool shrinks when caller `max_results` small: in `HybridRetriever.query`, floor `per_leg` at `max(10, 2*k, self._rerank_candidates if reranker else 0)` so a small `k` doesn't starve the rerank candidate pool. Test: with `k=2` and a reranker, `_run_bm25` is asked for ≥ rerank_candidates.
- [ ] **RET-R12** — empty-corpus BM25 sentinel (`__empty__`) must never surface as a hit: assert `HybridRetriever` drops any hit with `doc_id == "__empty__"`.
- [ ] **RET-R13** — `distance=None` bypasses the floor: in `_run_chroma`, when `chroma_max_distance` is set, treat `distance is None` as **dropped** (not kept) OR keep but flag — spec says the None-bypass is a bug; change to drop when a floor is configured. Test: a hit with `distance=None` and a configured floor is excluded. (Coordinate with T5/T9 behaviour — keep degradation intact.)
- [ ] **RET-R15** — no cross-source conflict resolution: add a dedup on `(source_path, start_line)` for symbol chunks vs prose chunks in `render_context_block` input (dedup identical summaries). Test: two artifacts with identical summary collapse to one line.
- [ ] **RET-R16** — schema freshness not checked at query: in `SchemaRetriever.query`, if `has_index` is False, log-once a debug and return `[]` cleanly (already does via BM25 miss) — add a test asserting no exception on missing snapshot.
- [ ] **RET-R17** — 1024-token BM25 doc cap truncates long schema docs silently: raise `_MAX_TOKENS_PER_DOC` awareness — the schema doc builder should log when a doc exceeds the BM25 token cap. Test: a very long schema doc logs a truncation debug (assert via caplog).
- [ ] **CODEIDX-C10** — chunk overlap byte-suffix: overlap is now token-bounded (T2). Add a test asserting the overlap prefix is ≤ `OVERLAP_TOKENS`.
- [ ] **CODEIDX-C11** — boundary regex Python/MD-only: extend `CLASS_BOUNDARY` in `chunker.py` to also match JS/TS (`^export `, `^function `, `^const \w+ = `) and Go (`^func `). Test: a TS file with `export class X` splits at the class.
- [ ] **CODEIDX-C12** — file_splitter silent truncation: in `code_symbol_chunker`, when a symbol span is truncated to the window, set `metadata["truncated"] = True`. Test: oversize symbol chunk carries `truncated=True`.
- [ ] **CODEIDX-C13** — method heuristic Python-only: N/A to embedding path (graph concern) — mark subsumed/skip with a comment; assert `symbol_chunks` emits chunks for `kind in {"function","method","class"}` regardless of language.
- [ ] **CODEIDX-C14** — cross-lang import false edges: N/A to embedding (graph concern, W6). Skip with note in commit; add a no-op assertion that symbol chunks don't emit import edges.
- [ ] **CODEIDX-C18** — embed batch not isolated: in the embed stage, wrap each `add_documents` symbol batch in try/except so one bad batch doesn't abort the rest. Test: a batch raising doesn't propagate (monkeypatch add_documents to raise once).
- [ ] **CODEIDX-C19** — BM25/Chroma divergence: ensure symbol chunks are added to Chroma only (BM25 is built separately by the bm25_build stage from the same docs) — assert symbol chunk ids are prefixed `sym:` and distinct from prose chunk ids.
- [ ] **CODEIDX-C20/C21** — Louvain over-merge / cluster staleness: clustering is W6-owned — mark **out of scope for W2** in the commit body (these were mis-listed; confirm with spec §3 which assigns C-cluster to W6). If genuinely W2, add a placeholder skip test `pytest.mark.skip(reason="W6 clustering scope")`.
- [ ] Run: `cd backend && .venv/bin/pytest tests/unit/knowledge/test_w2_low_batch.py -v` → all green.
- [ ] **DoD:** all items green or explicitly skipped-with-reason; `ruff` clean; commit body lists each ID's disposition (fixed / subsumed / out-of-scope).
- [ ] Commit: `fix(knowledge): W2 low-severity robustness batch (RET-R11..R17, CODEIDX-C10..C21)`

---

## Task T15 — End-of-wave flag flips under the eval gate

`depends:[T1..T14]`

**Scene:** Spec §9 posture is *flip-after-fix under eval gate*: flip `reranker_enabled=True` and `context_planner_enabled=True` **only after** the retrieval-eval + reranker tests pass. This task flips the two defaults and adds a wave-gate assertion test that the eval + reranker suites are green.

**Files:**
- `backend/app/config.py` (lines 475, 498)
- `backend/.env.example`
- `CLAUDE.md` (feature-flag table: update defaults)
- `CHANGELOG.md` ([Unreleased])

**Gate command (run BEFORE flipping — must pass):**
```bash
cd backend && .venv/bin/pytest tests/unit/test_retrieval_eval.py tests/unit/test_reranker.py -v
```
Expected: `test_retrieval_eval.py` — all pass incl. `test_harness_oracle_passes_thresholds` (PASS, `hit_at_k == 1.0`); `test_reranker.py` — all pass incl. the new `test_uses_rank_when_model_supports_it`. Both files exit `0`.

**Steps:**

- [ ] Run the gate command above → confirm **all pass** (paste the pass summary into the commit body).
- [ ] **RED** — add `backend/tests/unit/test_w2_flag_flips.py`:
```python
from app.config import settings


def test_reranker_default_on() -> None:
    assert settings.reranker_enabled is True


def test_context_planner_default_on() -> None:
    assert settings.context_planner_enabled is True
```
- [ ] Run → **fails**.
- [ ] **GREEN** — `config.py`: `reranker_enabled: bool = True` (line 475), `context_planner_enabled: bool = True` (line 498). Update inline comments to note "default ON as of W2 (gated on retrieval-eval + reranker tests)".
- [ ] Update `.env.example` (`RERANKER_ENABLED=true`, `CONTEXT_PLANNER_ENABLED=true`), `CLAUDE.md` feature-flag tables (`reranker_enabled` → on; `context_planner_enabled` → on), and `CHANGELOG.md` `[Unreleased]` with the W2 summary.
- [ ] Re-run the full gate: `cd backend && .venv/bin/pytest tests/unit/test_retrieval_eval.py tests/unit/test_reranker.py tests/unit/test_w2_flag_flips.py -v` → all pass.
- [ ] **DoD:** flags flipped; eval+reranker gate green; docs+changelog updated.
- [ ] Commit: `feat(config): flip reranker_enabled + context_planner_enabled default-on under eval gate (W2)`

---

## Wave-level Definition of Done

- [ ] `cd backend && .venv/bin/ruff format --check app/ tests/ && .venv/bin/ruff check app/ tests/` — clean.
- [ ] `cd backend && .venv/bin/mypy app/ --ignore-missing-imports` — clean on touched modules.
- [ ] `cd backend && .venv/bin/pytest tests/unit tests/integration -q` then `coverage report --fail-under=72` — coverage ≥ 72%.
- [ ] Retrieval-eval gate: `tests/unit/test_retrieval_eval.py` + `tests/unit/test_reranker.py` pass.
- [ ] Docs updated in the same commits: `CLAUDE.md` (flag table + reindex note), `.env.example` (new/changed keys), `CHANGELOG.md` `[Unreleased]`.
- [ ] Self-review: every W2 spec §3 item maps to a task (CODEIDX-C1→T2/T3, C2→T1, C3→T4; RET-R1→T8, R2→T5, R3→T6, R8→T7, R4→T9, R5→T10, R9/DBIDX-D7→T11, R10→T12, reranker→T13; low→T14; flips→T15). No placeholders. No two parallel-group tasks write the same file (Group B: T5=catalog, T6/T7=renderer, T8=orchestrator/context_loader, T9=hybrid_retriever, T10=config; Group C: T11/T12=schema_retriever+sql_agent, T13=reranker — disjoint).

## Assumptions / open questions / risks (surfaced now, not mid-execution)

- **Embedding model = `BAAI/bge-base-en-v1.5`, `max_seq_length = 512`** (Context7-confirmed, spec §1). Reindex implication: flipping the default (T2) invalidates existing prod Chroma vectors — T3 ships the reindex trigger and CLAUDE.md note; **the actual prod reindex is a required post-deploy human step** (below). If bge-base is too heavy for the deploy target, `intfloat/e5-base-v2` (also 512) is the drop-in alternate — set `chroma_embedding_model`+`embedder_max_tokens` together.
- **`transformers` availability:** T1's tokenizer lazy-loads; if `transformers` is not installed in prod, chunking uses the char fallback (safe: over-counts, no truncation). Confirm `transformers` (a `sentence-transformers` transitive dep) is present when `chroma_embedding_model` is set; otherwise chunks size conservatively but the *embedder* still truncates at 512 — acceptable.
- **W4 dependency for T11:** `column_distinct_values_json` + `numeric_format_notes` are present on `DbIndex` **today**; `SchemaInfo.foreign_keys` is present live. So T11 is not hard-blocked, but its distinct/numeric quality depends on W4 actually *populating* those fields for all dialects (esp. Mongo/CH). Gate is the pre-check grep in T11.
- **orchestrator.py conflict with W3:** T8 edits one contiguous block (~845-864) via a new `ContextLoader.assemble_knowledge_block` seam to minimize surface. If W3 runs concurrently, sequence T8 after W3's orchestrator decomposition or coordinate the merge (spec §5 assigns orchestrator.py to W3; W2's touch is the single knowledge-assembly call).
- **`RET-R13` (distance=None drop):** changing None→drop could reduce recall if a legit backend returns None distances; the T14 change is gated behind "only when a floor is configured" and validated by the eval gate.

## Human steps (isolated, at the very end)

1. **Post-deploy prod reindex (required):** after the model default flips, run `queue_embedding_reindex(<all project_ids>)` (T3) against prod so existing Chroma collections re-embed under bge-base-en-v1.5. Until this runs, previously-indexed projects retrieve against stale 256-ctx vectors. Schedule during low traffic; monitor `run_repo_index` completion.
2. **Confirm `transformers`/`sentence-transformers` installed on the deploy target** (Heroku dyno / Docker image) before flipping — otherwise the reranker degrades to no-op and chunking uses the char fallback.
3. **Re-pull prod telemetry** (`request_traces`, retrieval metrics) before/after the wave to measure impact (recall proxy: fewer `retrieval_degraded_total`, answer quality) per spec §10.
