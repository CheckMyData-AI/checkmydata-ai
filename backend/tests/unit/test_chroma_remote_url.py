"""AUD-0819-23: `CHROMA_SERVER_URL` is a URL, and the client wants host/port/ssl.

`chromadb.HttpClient(host, port=8000, ssl=False, …)` takes a HOSTNAME. The setting
is named `chroma_server_url` and was passed straight through as `host`, so a real
value — `https://chroma.example.com` — became
`http://https://chroma.example.com:8000`. The existing tests mock `chromadb`
wholesale, so nothing ever exercised the construction and the defect was invisible
to a green suite.

This matters beyond tidiness: moving Chroma off the dyno is the architecturally
right answer to a 512 MiB worker holding an HNSW index for 25,161 vectors, and it
also makes the store durable — which is the root cause behind `repair_embeddings`
running on every restart. A migration path that cannot parse its own setting is
not a path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.knowledge.vector_store import _parse_chroma_server_url


class TestParse:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # A full URL — the shape the setting's name invites.
            ("https://chroma.example.com", ("chroma.example.com", 443, True)),
            ("http://chroma.example.com", ("chroma.example.com", 80, False)),
            ("https://chroma.example.com:9000", ("chroma.example.com", 9000, True)),
            ("http://remote:8000", ("remote", 8000, False)),
            # A bare host keeps the historical default so an existing deployment
            # that happened to set one is not silently repointed.
            ("chroma.internal", ("chroma.internal", 8000, False)),
            ("chroma.internal:9001", ("chroma.internal", 9001, False)),
            # Trailing slash and whitespace are an operator's, not a bug.
            ("  https://chroma.example.com/  ", ("chroma.example.com", 443, True)),
        ],
    )
    def test_parses(self, value: str, expected: tuple[str, int, bool]) -> None:
        assert _parse_chroma_server_url(value) == expected

    def test_an_unparseable_value_is_refused_rather_than_guessed(self) -> None:
        # Silently defaulting to localhost would make a typo look like a working
        # deployment reading an empty index.
        with pytest.raises(ValueError, match="CHROMA_SERVER_URL"):
            _parse_chroma_server_url("https://")


class TestClientConstruction:
    def test_the_client_gets_host_port_and_ssl_separately(self) -> None:
        from app.knowledge import vector_store as vs

        with (
            patch.object(vs, "chromadb") as chroma,
            patch.object(vs.settings, "chroma_server_url", "https://chroma.example.com"),
            patch.object(vs, "_get_embedding_function", return_value=None),
        ):
            chroma.HttpClient.return_value = MagicMock()
            vs.VectorStore()

        chroma.HttpClient.assert_called_once_with(host="chroma.example.com", port=443, ssl=True)
