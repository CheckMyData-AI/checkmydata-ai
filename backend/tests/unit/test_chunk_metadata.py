from __future__ import annotations

import pytest

from app.knowledge.chunk_metadata import (
    REQUIRED_CHUNK_METADATA_KEYS,
    CodeChunkMetadata,
    validate_chunk_metadata,
)


def test_metadata_to_dict_has_all_keys():
    m = CodeChunkMetadata(
        path="a/b.py", symbol="foo", language="python", start_line=1, end_line=9, kind="function"
    )
    d = m.to_dict()
    assert set(d) == REQUIRED_CHUNK_METADATA_KEYS
    assert d["path"] == "a/b.py" and d["start_line"] == 1


def test_validate_rejects_missing_key():
    with pytest.raises(ValueError):
        validate_chunk_metadata({"path": "x", "symbol": "y"})
