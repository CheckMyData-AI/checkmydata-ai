"""Semantic chunking for vector store documents.

Splits documents by class/model boundaries to produce chunks
that embed well and retrieve meaningfully.
"""

import re
from dataclasses import dataclass

TARGET_CHUNK_TOKENS = 800
MAX_CHUNK_TOKENS = 1500
APPROX_CHARS_PER_TOKEN = 4
OVERLAP_CHARS = 150

CLASS_BOUNDARY = re.compile(r"^(?:class |## |### |model |\bCREATE TABLE\b)", re.MULTILINE)


@dataclass
class Chunk:
    content: str
    metadata: dict


def chunk_document(
    content: str,
    file_path: str,
    doc_type: str,
    extra_metadata: dict | None = None,
) -> list[Chunk]:
    """Split a document into semantic chunks suitable for embedding.

    Strategy:
    1. Split on class/model/heading boundaries
    2. Merge small consecutive sections
    3. Split oversized sections at paragraph boundaries
    """
    base_meta = {"source_path": file_path, "doc_type": doc_type}
    if extra_metadata:
        base_meta.update(extra_metadata)

    max_chars = MAX_CHUNK_TOKENS * APPROX_CHARS_PER_TOKEN
    target_chars = TARGET_CHUNK_TOKENS * APPROX_CHARS_PER_TOKEN

    if not content.strip():
        return []

    if len(content) <= max_chars:
        return [Chunk(content=content, metadata=base_meta)]

    sections = _split_at_boundaries(content)
    merged = _merge_small_sections(sections, target_chars)
    raw_chunks: list[str] = []
    for section in merged:
        if len(section) > max_chars:
            raw_chunks.extend(_split_large_section(section, max_chars))
        else:
            raw_chunks.append(section)

    chunks = []
    for i, text in enumerate(raw_chunks):
        overlap_prefix = ""
        if i > 0 and OVERLAP_CHARS > 0:
            prev = raw_chunks[i - 1]
            overlap_prefix = prev[-OVERLAP_CHARS:] if len(prev) > OVERLAP_CHARS else prev
        chunk_text = (overlap_prefix + text).strip() if overlap_prefix else text.strip()
        if chunk_text:
            meta = {**base_meta, "chunk_index": str(i)}
            chunks.append(Chunk(content=chunk_text, metadata=meta))

    return chunks


def _split_at_boundaries(content: str) -> list[str]:
    positions = [m.start() for m in CLASS_BOUNDARY.finditer(content)]
    if not positions:
        return [content]

    sections = []
    starts = [0] + positions
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(content)
        section = content[start:end]
        if section.strip():
            sections.append(section)
    return sections


def _merge_small_sections(sections: list[str], target_chars: int) -> list[str]:
    merged = []
    buffer = ""
    for section in sections:
        if buffer and len(buffer) + len(section) > target_chars:
            merged.append(buffer)
            buffer = section
        else:
            buffer = buffer + section if buffer else section
    if buffer:
        merged.append(buffer)
    return merged


def _split_large_section(text: str, max_chars: int) -> list[str]:
    paragraphs = re.split(r"\n\n+", text)
    parts = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_chars:
            parts.append(current)
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current:
        parts.append(current)
    return parts
