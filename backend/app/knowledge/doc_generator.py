"""LLM-powered documentation generator for extracted source code."""

import logging

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

MAX_CONTENT_LENGTH = 12_000


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
    ) -> str:
        """Generate structured documentation for a single extracted file.

        *enrichment_context* is optional cross-file context (relationships,
        enum values, usage data) that helps the LLM produce richer docs.

        Returns the generated markdown documentation.
        Falls back to raw content if LLM is unavailable.
        """
        truncated = content[:MAX_CONTENT_LENGTH]
        if len(content) > MAX_CONTENT_LENGTH:
            truncated += f"\n... (truncated, {len(content) - MAX_CONTENT_LENGTH} chars omitted)"

        enrichment_section = ""
        if enrichment_context:
            enrichment_section = (
                f"\nADDITIONAL CONTEXT (from cross-file analysis):\n{enrichment_context}\n"
            )

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

        return content
