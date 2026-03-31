"""Agent error hierarchy.

The orchestrator uses these to decide whether to retry a sub-agent,
return an error to the user, or fall back to a simpler strategy.
"""


class AgentError(Exception):
    """Base exception for all agent-related errors."""


class AgentRetryableError(AgentError):
    """Transient failure — the orchestrator may retry with adjusted context."""


class AgentFatalError(AgentError):
    """Unrecoverable error (missing connection, auth failure, etc.)."""
