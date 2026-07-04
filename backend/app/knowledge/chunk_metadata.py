"""Raw-code embedding chunk metadata schema (contract C-E; consumed in Wave 2)."""

from __future__ import annotations

from dataclasses import dataclass

REQUIRED_CHUNK_METADATA_KEYS: frozenset[str] = frozenset(
    {"path", "symbol", "language", "start_line", "end_line", "kind"}
)


@dataclass
class CodeChunkMetadata:
    path: str
    symbol: str
    language: str
    start_line: int
    end_line: int
    kind: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "symbol": self.symbol,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "kind": self.kind,
        }


def validate_chunk_metadata(meta: dict) -> None:
    missing = REQUIRED_CHUNK_METADATA_KEYS - set(meta)
    if missing:
        raise ValueError(f"chunk metadata missing required keys: {sorted(missing)}")
