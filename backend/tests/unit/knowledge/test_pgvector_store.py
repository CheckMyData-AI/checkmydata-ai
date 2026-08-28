"""The vector store must survive a dyno restart, and the swap must not change answers.

ChromaDB persisted to ``CHROMA_PERSIST_DIR`` — ``/app/data/chroma``, the container
filesystem, wiped on every restart and not shared between the ``web`` and ``worker``
process types. What that cost, measured in production on 2026-08-27:

    22:00:44  repair_embeddings  "Vector store empty but 758 docs in DB.
                                  Forcing a full re-index."
    22:01:21  code_symbol_embed  started   (all 8 646 files, because force_full)
    22:39:09  code_symbol_embed  completed (38 minutes)
    23:59:50  heartbeat stops — the 7 200 s ceiling, at 380 of 758 documents
    00:04     stale run reaped

A full rebuild costs 12 039 s and the nightly budget is 7 200 s, so the store was
empty again the next night, and the night after. `index_repo` has completed 16 times
in 94 runs. The self-repair (C3, v1.13.0) was correct — the repair simply cost more
than the budget allowed, which is not something a bigger ceiling can fix.

These tests cover what can be checked without a database. The store's behaviour
against real Postgres — ranking, filters, upsert, delete — was verified end to end
against the production database before this file existed; what is asserted here is
the part that would rot silently: the interface staying identical to the backend it
replaces, and the two refusals that must stay loud.
"""

from __future__ import annotations

import inspect

import pytest

from app.knowledge import pgvector_store as pgv
from app.knowledge.vector_store import VectorStore, make_vector_store


class TestTheInterfaceIsIdenticalToTheBackendItReplaces:
    """Ten call sites take whichever store they are handed and never ask which one.
    The moment one backend grows a method the other lacks, that stops being true —
    and it stops being true at runtime, on whichever deployment flipped the flag."""

    PUBLIC = (
        "get_or_create_collection",
        "add_documents",
        "query",
        "delete_by_source_path",
        "delete_collection",
        "close",
    )

    @pytest.mark.parametrize("name", PUBLIC)
    def test_both_backends_have_it(self, name: str) -> None:
        assert callable(getattr(VectorStore, name, None)), f"VectorStore.{name}"
        assert callable(getattr(pgv.PgVectorStore, name, None)), f"PgVectorStore.{name}"

    @pytest.mark.parametrize("name", PUBLIC)
    def test_the_signatures_match(self, name: str) -> None:
        """Positional parameters and their order, not annotations — a caller passes
        `(project_id, query_text, n_results)` and must keep meaning the same thing."""
        a = list(inspect.signature(getattr(VectorStore, name)).parameters)
        b = list(inspect.signature(getattr(pgv.PgVectorStore, name)).parameters)
        assert a == b, f"{name}: chroma={a} pgvector={b}"

    def test_the_collection_handle_answers_count(self) -> None:
        """`pipeline_runner.py:415` and `context_loader.py:213` both do
        `get_or_create_collection(pid).count()`. That call decides whether the store
        is empty and a full re-index is owed — the very decision this change exists
        to make correct — so the handle must answer it."""
        assert hasattr(pgv._ProjectHandle, "count")
        assert "name" in pgv._ProjectHandle.__slots__

    def test_the_handle_names_the_collection_chroma_would_have(self) -> None:
        """Logs and metrics carry that name. Changing it silently breaks a grep."""
        store = object.__new__(pgv.PgVectorStore)
        handle = pgv._ProjectHandle(store, "fc6554a5-55bd-4490-ac0e-4e6a45afee34")
        assert handle.name == "project_fc6554a5_55bd_4490_ac0e_4e6a45afee34"
        assert handle.name == VectorStore._collection_name(
            object.__new__(VectorStore), "fc6554a5-55bd-4490-ac0e-4e6a45afee34"
        )


class TestTheDsnConversion:
    """SQLAlchemy's URL names a driver; libpq does not understand one."""

    @pytest.mark.parametrize(
        ("given", "want"),
        [
            ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
            ("postgresql+psycopg://u:p@h/db", "postgresql://u:p@h/db"),
            ("postgresql://u:p@h/db", "postgresql://u:p@h/db"),
        ],
    )
    def test_the_driver_is_stripped(self, given: str, want: str) -> None:
        assert pgv._sync_dsn(given) == want

    def test_a_password_containing_the_driver_name_is_not_mangled(self) -> None:
        """Belt and braces: the replacement is anchored on the scheme, and a password
        is not a scheme. Worth a test because the failure would be an intermittent
        auth error nobody would trace back to here."""
        dsn = pgv._sync_dsn("postgresql+asyncpg://u:pass@h/db")
        assert dsn.startswith("postgresql://")
        assert "pass" in dsn


class TestTheTwoRefusals:
    """Both exist because the alternative is a wrong answer nobody can see."""

    def test_an_operator_filter_is_refused_rather_than_matching_nothing(self) -> None:
        """ChromaDB accepts `{"k": {"$eq": v}}`. Translated naively to
        `metadata ->> 'k' = '{...}'` it matches no row and returns an empty result —
        which reads as "nothing found" rather than "this filter is not implemented"."""
        store = object.__new__(pgv.PgVectorStore)
        with pytest.raises(ValueError, match="operator filter"):
            store.query("p", "q", where={"chunk": {"$eq": 1}})

    def test_a_dimension_mismatch_raises(self) -> None:
        """A vector of the wrong width is not a crash — Postgres would reject it, but
        only if the column is declared. The check is here so the message names the
        cause (the embedder changed) rather than a cast error."""
        store = object.__new__(pgv.PgVectorStore)
        store._embedding_fn = lambda texts: [[0.0] * 7 for _ in texts]
        import threading

        store._embed_lock = threading.Lock()
        with pytest.raises(pgv.EmbeddingDimensionError, match="7 dimensions"):
            store._embed(["x"])


class TestTheBackendSwitch:
    def test_the_default_is_still_chroma(self) -> None:
        """The flip is a decision taken on a verified deployment, not a side effect of
        merging this change."""
        from app.config import Settings

        assert Settings.model_fields["vector_store_backend"].default == "chroma"

    def test_the_factory_returns_chroma_by_default(self) -> None:
        assert isinstance(make_vector_store(), VectorStore)

    def test_pgvector_on_sqlite_says_so_instead_of_failing_later(self, monkeypatch) -> None:
        """Development and the test suite run on SQLite, where the migration that
        creates `doc_embeddings` is deliberately a no-op. Asking for pgvector there is
        a configuration error, and it should read as one — not as a missing table
        several stack frames deep."""
        from app.config import settings

        monkeypatch.setattr(settings, "vector_store_backend", "pgvector", raising=False)
        monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///x.db", raising=False)
        with pytest.raises(ValueError, match="requires a PostgreSQL"):
            make_vector_store()

    def test_an_unknown_backend_is_refused(self, monkeypatch) -> None:
        from app.config import settings

        monkeypatch.setattr(settings, "vector_store_backend", "qdrant", raising=False)
        with pytest.raises(ValueError, match="not a backend"):
            make_vector_store()


def test_the_batch_cap_still_governs_the_embed_call() -> None:
    """`EMBEDDING_UPSERT_BATCH_SIZE` was cut 200 -> 8 because the ONNX model pads every
    document to 256 tokens and its activations are sized by the batch: 967 MiB for 200
    against 415 MiB for 8, on a worker that had been SIGKILLed at 1 053 MiB. The
    constraint belongs to the embedder, which moved into this class — so the cap has
    to move with it rather than being left behind in the backend that no longer runs.
    """
    source = inspect.getsource(pgv.PgVectorStore.add_documents)
    assert "embedding_upsert_batch_size" in source
