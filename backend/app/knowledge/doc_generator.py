"""LLM-powered documentation generator for extracted source code."""

import logging
import string

from app.llm.base import Message
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

DOC_GENERATION_PROMPT = """\
You are a database documentation specialist. Analyze the following source code \
and extract structured information about the database schema it defines or uses.

For each table/model found, provide:
1. **Table name** and a 1-2 sentence description of its purpose
2. **Columns**: name, what it represents, valid values if constrained/enum
3. **Relationships** to other tables (has-many, belongs-to, many-to-many)
4. **Business rules** implied by the code (validations, defaults, computed fields)
5. **Query patterns** visible in the code (common filters, JOINs, aggregations)

If the file contains migrations, describe what each migration changes.
If the file contains raw SQL, describe the tables and operations involved.

Be concise but thorough. Output as structured markdown.

SOURCE FILE: {file_path}
DOC TYPE: {doc_type}
{enrichment_section}
```
{content}
```"""

DOC_UPDATE_PROMPT = """\
You are a database documentation specialist. The source file below has changed.
Update the existing documentation to reflect the changes.

SOURCE FILE: {file_path}
DOC TYPE: {doc_type}
{enrichment_section}

EXISTING DOCUMENTATION:
{existing_doc}

CHANGES (unified diff):
```diff
{diff_text}
```

CURRENT FILE (for reference):
```
{content}
```

Produce the complete updated documentation in structured markdown. \
Preserve sections that are unchanged. Update/add/remove sections as needed."""

DIFF_THRESHOLD_RATIO = 0.3

MAX_CONTENT_LENGTH = 12_000
MAX_FALLBACK_LENGTH = 50_000
_PRINTABLE = set(string.printable)


def _is_binary_content(text: str, sample_size: int = 1024) -> bool:
    """Return True if *text* looks like binary data (high non-printable ratio)."""
    sample = text[:sample_size]
    if not sample:
        return False
    non_printable = sum(1 for ch in sample if ch not in _PRINTABLE)
    return non_printable / len(sample) > 0.3


def _sanitize_content(text: str) -> str:
    """Strip null bytes that PostgreSQL TEXT columns cannot store."""
    return text.replace("\x00", "")


class DocGenerator:
    """Generates structured documentation from raw source code using LLM."""

    def __init__(self, llm_router: LLMRouter | None = None):
        self._llm = llm_router or LLMRouter()

    async def generate(
        self,
        file_path: str,
        content: str,
        doc_type: str,
        preferred_provider: str | None = None,
        model: str | None = None,
        enrichment_context: str = "",
        previous_content: str | None = None,
        existing_doc: str | None = None,
    ) -> str:
        """Generate structured documentation for a single extracted file.

        *enrichment_context* is optional cross-file context (relationships,
        enum values, usage data) that helps the LLM produce richer docs.

        When *previous_content* and *existing_doc* are both provided and the
        change is small (< DIFF_THRESHOLD_RATIO of file), a diff-based update
        prompt is used instead of regenerating from scratch.

        Returns the generated markdown documentation.
        Falls back to sanitized raw content if LLM is unavailable.
        """
        content = _sanitize_content(content)

        use_diff = False
        diff_text = ""
        if previous_content and existing_doc:
            diff_text = self._compute_diff(previous_content, content)
            if diff_text:
                changed_lines = sum(
                    1
                    for ln in diff_text.splitlines()
                    if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
                )
                total_lines = max(len(content.splitlines()), 1)
                if changed_lines / total_lines < DIFF_THRESHOLD_RATIO:
                    use_diff = True

        truncated = content[:MAX_CONTENT_LENGTH]
        if len(content) > MAX_CONTENT_LENGTH:
            truncated += f"\n... (truncated, {len(content) - MAX_CONTENT_LENGTH} chars omitted)"

        enrichment_section = ""
        if enrichment_context:
            enrichment_section = (
                f"\nADDITIONAL CONTEXT (from cross-file analysis):\n{enrichment_context}\n"
            )

        if use_diff:
            prompt = DOC_UPDATE_PROMPT.format(
                file_path=file_path,
                doc_type=doc_type,
                enrichment_section=enrichment_section,
                existing_doc=existing_doc[:MAX_CONTENT_LENGTH],
                diff_text=diff_text[:4000],
                content=truncated,
            )
        else:
            prompt = DOC_GENERATION_PROMPT.format(
                file_path=file_path,
                doc_type=doc_type,
                content=truncated,
                enrichment_section=enrichment_section,
            )

        messages = [
            Message(role="user", content=prompt),
        ]

        try:
            response = await self._llm.complete(
                messages=messages,
                temperature=0.0,
                max_tokens=2048,
                preferred_provider=preferred_provider,
                model=model,
            )
            generated = response.content.strip()
            if generated:
                return generated
        except Exception:
            logger.warning(
                "LLM doc generation failed for %s, using raw content",
                file_path,
                exc_info=True,
            )

        if _is_binary_content(content):
            logger.warning("Skipping binary-looking fallback content for %s", file_path)
            return f"# {file_path}\n\n*Binary or non-text content — no documentation generated.*"

        if len(content) > MAX_FALLBACK_LENGTH:
            logger.warning(
                "Truncating oversized fallback content for %s (%d chars)",
                file_path,
                len(content),
            )
            return content[:MAX_FALLBACK_LENGTH]

        return content

    @staticmethod
    def _compute_diff(old: str, new: str) -> str:
        import difflib

        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        diff = difflib.unified_diff(old_lines, new_lines, n=2)
        return "".join(diff)
