"""F-KNOW-09 residual: an exception outside `_parse_one`'s own handler is dropped.

`ast_parse` gathers its per-file tasks with `return_exceptions=True` and never looks
at the results. `_parse_one` wraps the parse itself in try/except and counts those
failures honestly — but anything raised *outside* that block (assigning into
`state.parsed_files`, the semaphore, a `MemoryError` on a large tree) becomes an
exception object in a list nobody reads. The stage then logs `parsed=N` and reports
success while N is quietly short, which is the shape `vision.md` §7 forbids: a
degradation the user is not told about.

Recorded in the audit as "unbounded fan-out plus discarded results". The fan-out half
was **wrong** and is corrected there: `ast_parse_concurrency` defaults to 4 and
`_parse_one` holds the semaphore around the work, so at most four files parse at once;
the 8,541 task objects cost ~7 MiB measured, against a 747 MiB problem. Only the
discarded results were real.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.knowledge.pipeline_runner import IndexingPipelineRunner


@pytest.fixture
def runner() -> IndexingPipelineRunner:
    return IndexingPipelineRunner.__new__(IndexingPipelineRunner)


async def _run(runner, state, monkeypatch_target: Exception | None = None):
    with patch("app.knowledge.pipeline_runner.tracker") as tracker:
        tracker.emit = AsyncMock()
        await runner._run_ast_parse(state, "wf-1", ["a.py", "b.py", "c.py"])
    return tracker


class _State:
    def __init__(self, repo_dir):
        self.repo_dir = repo_dir
        self.changed_files: list[str] = []
        self.parsed_files: dict = {}
        self.ast_failed_files: set[str] = set()
        self.ast_unsupported_count = 0
        self.ast_skipped_count = 0


async def test_an_error_outside_the_per_file_handler_is_reported(tmp_path, caplog, runner):
    state = _State(tmp_path)

    # A dict whose __setitem__ raises: this is the assignment that sits OUTSIDE
    # `_parse_one`'s try/except, so the exception reaches `gather` and — before
    # this change — was collected into a list nobody read.
    class _Hostile(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("boom writing parsed_files")

    state.parsed_files = _Hostile()

    class _FakeParsed:
        symbols: list = []
        imports: list = []
        call_sites: list = []
        parse_errors: list = []

    with (
        patch("app.knowledge.pipeline_runner.ASTParser") as ap,
        caplog.at_level(logging.WARNING),
    ):
        ap.return_value.parse_file.return_value = _FakeParsed()
        await _run(runner, state)

    text = caplog.text.lower()
    assert "ast_parse" in text
    # The count and the cause must both be visible — "3 files failed" with no reason
    # is a number an operator cannot act on.
    assert "3" in caplog.text
    assert "boom writing parsed_files" in caplog.text or "runtimeerror" in text


async def test_a_clean_run_says_nothing_extra(tmp_path, caplog, runner):
    state = _State(tmp_path)

    class _FakeParsed:
        symbols: list = []
        imports: list = []
        call_sites: list = []
        parse_errors: list = []

    with (
        patch("app.knowledge.pipeline_runner.ASTParser") as ap,
        caplog.at_level(logging.WARNING),
    ):
        ap.return_value.parse_file.return_value = _FakeParsed()
        await _run(runner, state)

    # A warning that fires on every healthy run is one an operator learns to skip.
    assert "unexpected" not in caplog.text.lower()
    assert len(state.parsed_files) == 3
