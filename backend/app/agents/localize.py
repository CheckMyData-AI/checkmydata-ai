"""Put a static answer into the user's language (COR-05).

`README.md` promises multilingual responses, and the rule is a prompt instruction at
every synthesis point — so it holds wherever an LLM writes the text. The moments the
product most needs to explain itself bypass synthesis entirely: the step-limit and
wall-clock fallbacks, the pipeline stage-failure answer, the context-overflow note.
Those are hardcoded English joined in Python and delivered as the answer body. A
Russian-speaking user therefore got Russian on success and English exactly when the
system was degraded, timed out or failing — the moments comprehension matters most,
in a product whose degradation honesty is a §7 invariant.

**Why a translation call rather than a message catalogue.** A catalogue needs a
language detector and a translated string per language, and the detector is the part
that cannot be got right: "Cyrillic means Russian" is wrong for Ukrainian, Bulgarian
and Serbian, and an answer confidently written in the wrong language is worse than
one in English. The model reading the question already knows what language it is in,
and these messages are ~30 words on paths that have just spent a whole step budget —
so one short call is proportionate, and it covers every language rather than a list.

**It can only ever return the original.** This runs where something already failed,
so every failure mode here — no router, budget refused, timeout, an implausible
answer — yields the English text unchanged. A localiser that can raise would turn a
degraded answer into no answer at all.
"""

from __future__ import annotations

import asyncio
import logging

from app.llm.base import Message

logger = logging.getLogger(__name__)

#: One short call, and never a second: this path is already the slow one.
TIMEOUT_SECONDS = 12.0

#: A translation of a short status message is the same order of length as the
#: original. Anything much longer is the model answering the question it was shown
#: instead of translating the sentence, which must not reach the user as the answer.
MAX_GROWTH_RATIO = 3.0

_SYSTEM = (
    "You translate short status messages for a data-analysis product. "
    "Reply with ONLY the translated message — no preamble, no quotes, no commentary. "
    "If the user's question is already in English, reply with the message unchanged. "
    "Keep every number, table name and identifier exactly as written."
)


def _looks_implausible(original: str, candidate: object) -> str | None:
    # Type first: whatever `content` turns out to be, it is about to become the
    # answer body, and a repr of a non-string object reaching a user is worse than
    # the English sentence this was trying to improve on.
    if not isinstance(candidate, str):
        return f"not text ({type(candidate).__name__})"
    if not candidate:
        return "empty"
    if len(candidate) > max(80, len(original) * MAX_GROWTH_RATIO):
        return "too long to be a translation"
    return None


async def localize(
    text: str,
    user_question: str | None,
    llm: object | None,
    *,
    model: str | None = None,
) -> str:
    """Return *text* in the language of *user_question*, or *text* unchanged."""
    if not text or not user_question or llm is None:
        return text
    complete = getattr(llm, "complete", None)
    if complete is None:
        return text

    messages = [
        Message(role="system", content=_SYSTEM),
        Message(
            role="user",
            content=(
                f"User's question:\n{user_question[:500]}\n\n"
                f"Message to translate into that question's language:\n{text}"
            ),
        ),
    ]
    try:
        response = await asyncio.wait_for(
            complete(messages, temperature=0.0, max_tokens=400, model=model),
            timeout=TIMEOUT_SECONDS,
        )
    except (TimeoutError, asyncio.CancelledError):
        logger.info("Static-answer localisation timed out; delivering the English text")
        return text
    except Exception:
        # Includes a refused token budget: the ceiling is doing its job, and an
        # untranslated answer is a far better outcome than none.
        logger.info("Static-answer localisation unavailable", exc_info=True)
        return text

    raw = getattr(response, "content", "")
    candidate = raw.strip() if isinstance(raw, str) else raw
    problem = _looks_implausible(text, candidate)
    if problem:
        logger.info("Static-answer localisation discarded (%s)", problem)
        return text
    return candidate
