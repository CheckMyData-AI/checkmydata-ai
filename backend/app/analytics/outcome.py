"""Honest outcome of one analytics collection run (spec §2.4, REQ-008).

The distinction the rest of the system depends on: *no errors and zero rows* is
``ok`` — nothing was due — while *errors and zero rows* is ``failed``. Collapsing
the two would let a broken credential look like a quiet day, which is exactly the
kind of silent lie this module exists to prevent.

``partial`` sits between them: something was written, something also broke, and
the answer built on top of that data must say so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CollectStatus = Literal["ok", "partial", "failed"]

#: Process/job exit code per status — 0 success, 1 partial, 2 total failure.
_EXIT_CODES: dict[CollectStatus, int] = {"ok": 0, "partial": 1, "failed": 2}


@dataclass
class CollectOutcome:
    """Accumulator for one collection run over one connection.

    Attributes:
        rows_written: Fact-table rows upserted across every report and period.
        periods_ok: Periods fetched and written successfully.
        periods_empty: Periods the vendor reported as having no data.
        errors: Human-readable failures, one per failed period/report. Every
            entry must be safe to surface to the user — no secrets, no raw
            credentials.
    """

    rows_written: int = 0
    periods_ok: int = 0
    periods_empty: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> CollectStatus:
        """``ok`` | ``partial`` | ``failed`` — never collapse the first and last."""
        if not self.errors:
            return "ok"
        if self.rows_written > 0:
            return "partial"
        return "failed"

    @property
    def exit_code(self) -> int:
        """0 for ``ok``, 1 for ``partial``, 2 for ``failed``."""
        return _EXIT_CODES[self.status]
