"""Tests for retry decorator."""

import pytest

from app.core.retry import retry


class TestRetry:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        @retry(max_attempts=3)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        call_count = 0

        @retry(max_attempts=3, backoff_seconds=0)
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self):
        call_count = 0

        @retry(max_attempts=2, backoff_seconds=0)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError, match="nope"):
            await always_fail()
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_only_retries_specified_exceptions(self):
        call_count = 0

        @retry(
            max_attempts=3,
            backoff_seconds=0,
            retryable_exceptions=(ValueError,),
        )
        async def fail_with_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            await fail_with_type_error()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        retries = []

        def on_retry(attempt, exc):
            retries.append((attempt, str(exc)))

        @retry(max_attempts=3, backoff_seconds=0, on_retry=on_retry)
        async def flaky():
            if len(retries) < 2:
                raise ValueError(f"attempt {len(retries) + 1}")
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert len(retries) == 2
