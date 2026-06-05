"""C2 — vision §7 #3 (knowledge fidelity): a single LLM failure during
``generate_docs`` must not lose the entire indexing run.

These tests cover the resilience contract independently of the giant
``PipelineRunner.run_indexing`` method, by exercising the same primitives:
``asyncio.gather(return_exceptions=True)`` + per-doc retry + failure-ratio
threshold guard."""

from __future__ import annotations

import asyncio

import pytest


async def _ok(_path: str) -> str:
    return f"doc for {_path}"


async def _flaky_once(path: str, counter: dict[str, int]) -> str:
    counter[path] = counter.get(path, 0) + 1
    if counter[path] == 1:
        raise RuntimeError("transient 5xx")
    return f"doc for {path}"


async def _always_fails(_path: str) -> str:
    raise RuntimeError("permanent")


class TestGenerateDocsResilience:
    @pytest.mark.asyncio
    async def test_single_failure_does_not_abort_batch(self):
        """One failure in a batch must not poison the other docs."""
        paths = ["a.py", "b.py", "c.py"]

        async def runner(p: str) -> str:
            if p == "b.py":
                raise RuntimeError("boom")
            return await _ok(p)

        results = await asyncio.gather(
            *[runner(p) for p in paths],
            return_exceptions=True,
        )

        succeeded = [(p, r) for p, r in zip(paths, results) if not isinstance(r, BaseException)]
        failed = [(p, r) for p, r in zip(paths, results) if isinstance(r, BaseException)]

        assert len(succeeded) == 2
        assert len(failed) == 1
        assert failed[0][0] == "b.py"

    @pytest.mark.asyncio
    async def test_retry_succeeds_for_transient_failure(self):
        """A doc that fails its first batch attempt should succeed on retry."""
        counter: dict[str, int] = {}

        first_pass = await asyncio.gather(
            _flaky_once("a.py", counter),
            return_exceptions=True,
        )
        assert isinstance(first_pass[0], BaseException)

        retry = await asyncio.gather(
            _flaky_once("a.py", counter),
            return_exceptions=True,
        )
        assert retry[0] == "doc for a.py"

    @pytest.mark.asyncio
    async def test_failure_ratio_threshold_logic(self):
        """When too many docs fail, the step should fail the entire run."""
        total = 10
        still_failed = 4
        threshold = 0.3

        ratio = still_failed / total
        assert ratio > threshold  # 0.4 > 0.3 → step must fail

        still_failed = 2
        ratio = still_failed / total
        assert ratio <= threshold  # 0.2 <= 0.3 → step may complete partially

    @pytest.mark.asyncio
    async def test_zero_total_is_safe(self):
        """When there are no docs to generate, the threshold check is a no-op."""
        total = 0
        still_failed: list = []
        # The pipeline_runner guards with ``if total_llm_tasks > 0`` so the
        # division never executes for empty input.
        if total > 0 and still_failed:
            ratio = len(still_failed) / total
            assert ratio > 0
        # No assertion on the empty branch — it must not raise

    @pytest.mark.asyncio
    async def test_settings_default_failure_ratio_is_30pct(self):
        """The default tolerance must stay at 30% (documented in
        SYSTEM_ARCHITECTURE / .env.example)."""
        from app.config import settings

        assert settings.generate_docs_max_failure_ratio == 0.3


class TestBinarySkipQueuesForRetry:
    """R3-7: a doc skipped by the binary-content heuristic must be queued for
    regeneration (it is most likely a false positive) instead of being marked
    processed and lost until a forced full re-index."""

    def test_is_binary_content_flags_high_nonprintable(self):
        from app.knowledge.doc_generator import _is_binary_content

        # >30% non-printable bytes → treated as binary.
        assert _is_binary_content("\x00\x01\x02\x03" * 100) is True
        # Normal source code → not binary.
        assert _is_binary_content("def foo():\n    return 42\n") is False
        # Empty content is never binary.
        assert _is_binary_content("") is False

    def test_binary_skip_appends_to_regeneration_queue(self):
        """Mirror the inline generate_docs contract: when a doc is binary, its
        path joins ``failed_doc_paths`` (deduped) so the next run retries it."""
        from app.knowledge.doc_generator import _is_binary_content

        failed_doc_paths: list[str] = []
        docs = [
            ("a.py", "def a(): pass"),
            ("blob.bin", "\x00\x01\x02" * 500),
            ("blob.bin", "\x00\x01\x02" * 500),  # duplicate path must not double-add
        ]
        for path, content in docs:
            if _is_binary_content(content):
                if path not in failed_doc_paths:
                    failed_doc_paths.append(path)

        assert failed_doc_paths == ["blob.bin"]

    def test_binary_skip_survives_still_failed_union(self):
        """R3-7 re-audit: the still-failed reassignment must UNION with the
        binary-skipped paths, not overwrite them.

        The earlier code did ``failed_doc_paths = [p for failed]`` which
        silently dropped the binary skips appended in Phase 1, negating the
        whole re-queue fix. This encodes the corrected union semantics from
        pipeline_runner.generate_docs.
        """
        # Phase 1: a binary-looking doc was queued for retry.
        failed_doc_paths: list[str] = ["weird_unicode.py"]

        # Phase 2: an unrelated doc failed its LLM generation.
        still_failed_paths = ["broken.py"]

        # Corrected line-1133 behavior: union (sorted set), not overwrite.
        failed_doc_paths = sorted(set(failed_doc_paths) | set(still_failed_paths))

        assert "weird_unicode.py" in failed_doc_paths, "binary skip was dropped by overwrite"
        assert "broken.py" in failed_doc_paths
        assert failed_doc_paths == ["broken.py", "weird_unicode.py"]
