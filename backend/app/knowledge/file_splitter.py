"""Intelligently split large source files into per-class/per-model segments.

Used before LLM doc generation so that each model gets its own LLM call
with full context, rather than blind truncation at 12000 chars.
"""

import ast
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_SINGLE_SEGMENT = 12_000


@dataclass
class FileSegment:
    """A slice of a source file representing one logical unit (class/model/section)."""

    name: str
    content: str
    start_line: int = 0
    end_line: int = 0


def split_large_file(
    content: str,
    file_path: str,
    max_segment_chars: int = MAX_SINGLE_SEGMENT,
) -> list[FileSegment]:
    """Split a file into segments by class/model boundaries.

    If the file is small enough, returns a single segment.
    """
    if len(content) <= max_segment_chars:
        return [FileSegment(name=file_path, content=content)]

    try:
        if file_path.endswith(".py"):
            return _split_python(content, file_path, max_segment_chars)
        if file_path.endswith(".prisma"):
            return _split_prisma(content, file_path, max_segment_chars)
        if file_path.endswith((".ts", ".tsx", ".js", ".jsx")):
            return _split_js_ts(content, file_path, max_segment_chars)

        return _split_generic(content, file_path, max_segment_chars)
    except Exception:
        logger.warning("File split failed for %s, returning single segment", file_path, exc_info=True)
        return [FileSegment(name=file_path, content=content[:max_segment_chars])]


def _split_python(
    content: str,
    file_path: str,
    max_chars: int,
) -> list[FileSegment]:
    """Split Python file at class boundaries, preserving imports as preamble."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _split_generic(content, file_path, max_chars)

    lines = content.splitlines(keepends=True)
    class_nodes = [node for node in ast.iter_child_nodes(tree) if isinstance(node, ast.ClassDef)]

    if not class_nodes:
        return _split_generic(content, file_path, max_chars)

    first_class_line = class_nodes[0].lineno - 1
    preamble = "".join(lines[:first_class_line])

    segments: list[FileSegment] = []
    for i, node in enumerate(class_nodes):
        start = node.lineno - 1
        if i + 1 < len(class_nodes):
            end = class_nodes[i + 1].lineno - 1
        else:
            end = len(lines)

        class_text = "".join(lines[start:end])
        segment_content = preamble + "\n" + class_text

        if len(segment_content) > max_chars:
            segment_content = segment_content[:max_chars] + "\n# ... truncated"

        segments.append(
            FileSegment(
                name=node.name,
                content=segment_content,
                start_line=start + 1,
                end_line=end,
            )
        )

    return segments if segments else [FileSegment(name=file_path, content=content[:max_chars])]


def _split_prisma(
    content: str,
    file_path: str,
    max_chars: int,
) -> list[FileSegment]:
    """Split Prisma schema at model boundaries."""
    model_pattern = re.compile(r"^(model\s+(\w+)\s*\{)", re.MULTILINE)
    matches = list(model_pattern.finditer(content))

    if not matches:
        return [FileSegment(name=file_path, content=content[:max_chars])]

    preamble_end = matches[0].start()
    preamble = content[:preamble_end]

    segments: list[FileSegment] = []
    for i, m in enumerate(matches):
        start = m.start()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(content)

        model_text = content[start:end]
        segment_content = preamble + "\n" + model_text

        if len(segment_content) > max_chars:
            segment_content = segment_content[:max_chars]

        segments.append(
            FileSegment(
                name=m.group(2),
                content=segment_content,
            )
        )

    return segments


def _split_js_ts(
    content: str,
    file_path: str,
    max_chars: int,
) -> list[FileSegment]:
    """Split JS/TS at class/export boundaries."""
    boundary = re.compile(
        r"^(?:export\s+)?(?:class|interface|const\s+\w+Schema|const\s+\w+\s*=\s*(?:pgTable|mysqlTable|sqliteTable))\b",
        re.MULTILINE,
    )
    matches = list(boundary.finditer(content))

    if not matches:
        return _split_generic(content, file_path, max_chars)

    preamble_end = matches[0].start()
    preamble = content[:preamble_end]

    segments: list[FileSegment] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)

        block = content[start:end]
        name_match = re.search(r"(?:class|interface|const)\s+(\w+)", block)
        name = name_match.group(1) if name_match else f"block_{i}"

        segment_content = preamble + "\n" + block
        if len(segment_content) > max_chars:
            segment_content = segment_content[:max_chars]

        segments.append(FileSegment(name=name, content=segment_content))

    return segments


def _split_generic(
    content: str,
    file_path: str,
    max_chars: int,
) -> list[FileSegment]:
    """Fallback: split at blank-line boundaries."""
    if len(content) <= max_chars:
        return [FileSegment(name=file_path, content=content)]

    segments: list[FileSegment] = []
    parts = re.split(r"\n\n+", content)
    buffer = ""
    idx = 0

    for part in parts:
        if buffer and len(buffer) + len(part) + 2 > max_chars:
            segments.append(
                FileSegment(
                    name=f"{file_path}#part{idx}",
                    content=buffer,
                )
            )
            buffer = part
            idx += 1
        else:
            buffer = buffer + "\n\n" + part if buffer else part

    if buffer:
        segments.append(
            FileSegment(
                name=f"{file_path}#part{idx}",
                content=buffer,
            )
        )

    return segments
