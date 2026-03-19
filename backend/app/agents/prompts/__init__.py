"""Prompt builders for the multi-agent system."""

from __future__ import annotations

from datetime import UTC, datetime


def get_current_datetime_str() -> str:
    """Return a human-readable UTC timestamp for injection into agent prompts."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%d %H:%M UTC (%A)")
