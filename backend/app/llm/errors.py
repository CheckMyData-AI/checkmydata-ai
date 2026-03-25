"""Unified LLM error hierarchy.

Provider-specific exceptions (openai, anthropic, httpx) are caught in each
adapter and re-raised as one of these types so the router and orchestrator
can make retry / fallback decisions without knowing which provider was used.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base for all LLM-layer errors."""

    is_retryable: bool = False
    retry_after_seconds: float | None = None

    def __init__(
        self,
        message: str = "",
        *,
        cause: BaseException | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.__cause__ = cause
        if retry_after is not None:
            self.retry_after_seconds = retry_after

    @property
    def user_message(self) -> str:
        return "An error occurred while communicating with the AI service."


class LLMRateLimitError(LLMError):
    """429 — provider rate limit hit.  Retryable with longer backoff."""

    is_retryable = True
    retry_after_seconds = 5.0

    @property
    def user_message(self) -> str:
        return "The AI service is temporarily overloaded. Please try again in a moment."


class LLMServerError(LLMError):
    """5xx — provider-side server error.  Retryable."""

    is_retryable = True
    retry_after_seconds = 2.0

    @property
    def user_message(self) -> str:
        return "The AI service encountered an internal error. Retrying automatically…"


class LLMAuthError(LLMError):
    """401/403 — bad or missing API key.  NOT retryable."""

    is_retryable = False

    @property
    def user_message(self) -> str:
        return "AI service configuration error. Please contact the project administrator."


class LLMTokenLimitError(LLMError):
    """Context / output token limit exceeded.  NOT retryable as-is."""

    is_retryable = False

    @property
    def user_message(self) -> str:
        return (
            "The conversation has become too long for the AI model's context window. "
            "Starting a fresh chat will resolve this."
        )


class LLMContentFilterError(LLMError):
    """Provider refused due to content policy.  NOT retryable."""

    is_retryable = False

    @property
    def user_message(self) -> str:
        return (
            "The AI service declined this request due to its content policy. "
            "Please rephrase your question."
        )


class LLMTimeoutError(LLMError):
    """Request timed out before the provider responded.  Retryable."""

    is_retryable = True
    retry_after_seconds = 2.0

    @property
    def user_message(self) -> str:
        return "The AI service took too long to respond. Retrying automatically…"


class LLMConnectionError(LLMError):
    """Network-level failure reaching the provider.  Retryable."""

    is_retryable = True
    retry_after_seconds = 2.0

    @property
    def user_message(self) -> str:
        return "Could not reach the AI service. Retrying automatically…"


class LLMAllProvidersFailedError(LLMError):
    """Every configured provider failed (after individual retries)."""

    is_retryable = True  # caller may retry the whole chain once more
    retry_after_seconds = 3.0

    @property
    def user_message(self) -> str:
        return "AI service is temporarily unavailable. Please try again shortly."


RETRYABLE_LLM_ERRORS: tuple[type[LLMError], ...] = (
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    LLMConnectionError,
)
