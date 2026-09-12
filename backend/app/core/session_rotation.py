"""The one place that decides how full a chat session's history is (COR-04).

`/api/chat/estimate` reported `history_budget_remaining = max_history_tokens` — the
constant, unconditionally — and computed `context_utilization_pct` from the size of
the SCHEMA, rules and learnings, which do not change while a conversation runs. So a
meter the UI paints red above 80% read the same number on a user's thousandth message
as on their first, and `rotation_imminent` shared no variable with the thing that
triggers rotation: `chat.py` compares stored history against
`max_context_tokens * session_rotation_threshold_pct / 100`, where the endpoint used
`max_history_tokens` (2 500 against 32 000 — not even the same constant).

The arithmetic therefore lives here, and both the trigger and the meter call it. A
meter that merely *matches* the trigger today is one refactor away from lying again.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.context_budget import CHARS_PER_TOKEN

#: How close to the threshold counts as "about to happen". The estimate endpoint used
#: `threshold_pct - 5` on a percentage that measured something else entirely; this is a
#: fraction OF the threshold, so it keeps its meaning when the threshold moves.
IMMINENT_FRACTION = 0.9


@dataclass(frozen=True)
class HistoryPressure:
    """What is known about one session's history, in the trigger's own terms."""

    history_tokens: int
    threshold_tokens: int
    rotation_enabled: bool

    @property
    def utilization_pct(self) -> float:
        if self.threshold_tokens <= 0:
            return 0.0
        return round(min(100.0, self.history_tokens / self.threshold_tokens * 100), 1)

    @property
    def should_rotate(self) -> bool:
        return self.rotation_enabled and self.history_tokens >= self.threshold_tokens

    @property
    def imminent(self) -> bool:
        return (
            self.rotation_enabled
            and not self.should_rotate
            and self.history_tokens >= self.threshold_tokens * IMMINENT_FRACTION
        )


def history_tokens(contents: list[str]) -> int:
    """The same estimate `chat.py` has always made: total characters over 4."""
    return sum(len(c) for c in contents) // CHARS_PER_TOKEN


def rotation_threshold_tokens() -> int:
    from app.config import settings

    return int(settings.max_context_tokens * settings.session_rotation_threshold_pct / 100)


def measure(contents: list[str]) -> HistoryPressure:
    from app.config import settings

    return HistoryPressure(
        history_tokens=history_tokens(contents),
        threshold_tokens=rotation_threshold_tokens(),
        rotation_enabled=bool(settings.session_rotation_enabled),
    )
