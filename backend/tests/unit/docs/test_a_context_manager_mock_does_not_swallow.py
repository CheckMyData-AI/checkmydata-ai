"""A mocked `__aexit__` must not suppress what was raised inside it.

`AsyncMock()` returns a `MagicMock` when awaited, which is truthy — and a truthy return
from `__aexit__` tells Python to SUPPRESS the exception. So `step.__aexit__ = AsyncMock()`
turns every exception raised inside a mocked step into silence, and the test goes on to
assert about a state the production code could never reach.

Found by PRJ-03 on 2026-09-17: a deadline raised inside `tracker.step` was swallowed by
exactly this mock, execution continued past the `async with` with `llm_resp` unbound, and
the test failed as `UnboundLocalError` rather than asserting the timeout it was written
for. Ten mocks across four files carried the same shape.
"""

from __future__ import annotations

import pathlib
import re

TESTS = pathlib.Path(__file__).resolve().parents[2]

_SWALLOWING = re.compile(r"__aexit__\s*=\s*AsyncMock\(\s*\)")


def test_no_async_context_manager_mock_suppresses_exceptions() -> None:
    offenders = [
        f"{path.relative_to(TESTS.parent)}:{lineno}"
        for path in sorted(TESTS.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _SWALLOWING.search(line) and "test_a_context_manager_mock" not in path.name
    ]
    assert not offenders, (
        "these mock `__aexit__` with a bare AsyncMock(), whose truthy return suppresses "
        "every exception raised inside the block — use AsyncMock(return_value=False):\n  "
        + "\n  ".join(offenders)
    )
