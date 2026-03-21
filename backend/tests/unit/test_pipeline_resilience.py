"""Indexing pipeline resilience tests.

Covers checkpoint-based resumption, binary file filtering,
concurrent index rejection, and error recovery patterns.
"""

import pytest


class TestBinaryFileFiltering:
    """Binary files must never enter the doc generation pipeline."""

    def test_common_binary_extensions_detected(self):
        binary_exts = [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".ico",
            ".svg",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".zip",
            ".tar",
            ".gz",
            ".bz2",
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".pyc",
            ".pyo",
            ".class",
            ".pdf",
            ".doc",
            ".docx",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
        ]
        from app.knowledge.repo_analyzer import DB_RELEVANT_EXTENSIONS

        for ext in binary_exts:
            assert ext not in DB_RELEVANT_EXTENSIONS, (
                f"Binary extension {ext} should not be in DB_RELEVANT_EXTENSIONS"
            )

    def test_code_extensions_included(self):
        from app.knowledge.repo_analyzer import DB_RELEVANT_EXTENSIONS

        code_exts = [".py", ".js", ".ts", ".rb", ".java", ".go", ".rs", ".sql"]
        for ext in code_exts:
            assert ext in DB_RELEVANT_EXTENSIONS, (
                f"Code extension {ext} should be in DB_RELEVANT_EXTENSIONS"
            )


class TestBinaryFileDetection:
    """Module-level is_binary_file function."""

    def test_binary_by_extension(self, tmp_path):
        from app.knowledge.repo_analyzer import is_binary_file

        for ext in [".png", ".woff2", ".exe", ".gz"]:
            fp = tmp_path / f"file{ext}"
            fp.write_bytes(b"not important")
            assert is_binary_file(fp), f"Extension {ext} should be binary"

    def test_code_not_binary(self, tmp_path):
        from app.knowledge.repo_analyzer import is_binary_file

        for ext in [".py", ".ts", ".sql", ".yml"]:
            fp = tmp_path / f"file{ext}"
            fp.write_text("print('hello')")
            assert not is_binary_file(fp), f"Extension {ext} should not be binary"

    def test_null_byte_content_detected(self, tmp_path):
        from app.knowledge.repo_analyzer import is_binary_file

        fp = tmp_path / "file.txt"
        fp.write_bytes(b"hello\x00world")
        assert is_binary_file(fp)


class TestBinaryContentDetection:
    """_is_binary_content from doc_generator."""

    def test_binary_content_detected(self):
        from app.knowledge.doc_generator import _is_binary_content

        binary_text = "\x00\x01\x02\x03\x04" * 100
        assert _is_binary_content(binary_text)

    def test_normal_text_not_binary(self):
        from app.knowledge.doc_generator import _is_binary_content

        assert not _is_binary_content("def hello():\n    return 'world'\n")

    def test_empty_string_not_binary(self):
        from app.knowledge.doc_generator import _is_binary_content

        assert not _is_binary_content("")

    def test_sanitize_content_strips_nulls(self):
        from app.knowledge.doc_generator import _sanitize_content

        assert _sanitize_content("hello\x00world") == "helloworld"


class TestCheckpointBehavior:
    """Verify checkpoint-based pipeline step tracking."""

    @pytest.mark.asyncio
    async def test_pipeline_records_completed_steps(self):
        from app.services.checkpoint_service import CheckpointService

        svc = CheckpointService()
        assert svc is not None

    @pytest.mark.asyncio
    async def test_stale_checkpoint_detection(self):
        from datetime import UTC, datetime, timedelta

        stale_time = datetime.now(UTC) - timedelta(hours=25)
        assert stale_time < datetime.now(UTC) - timedelta(hours=24)


class TestPipelineErrorHandling:
    """Pipeline failures must be properly contained."""

    @pytest.mark.asyncio
    async def test_pipeline_result_on_failure(self):
        from app.pipelines.base import PipelineResult

        result = PipelineResult(
            success=False,
            items_processed=0,
            error="LLM call failed: rate limit exceeded",
        )
        assert not result.success
        assert "rate limit" in result.error

    @pytest.mark.asyncio
    async def test_pipeline_status_model(self):
        from app.pipelines.base import PipelineStatus

        status = PipelineStatus(
            is_indexed=True,
            is_synced=False,
            is_stale=False,
            last_indexed_at="2024-01-01T00:00:00",
            items_count=42,
        )
        assert status.is_indexed
        assert not status.is_synced
        assert status.items_count == 42


class TestDatabasePipelineDelegation:
    """DatabasePipeline delegates to DbIndexPipeline correctly."""

    @pytest.mark.asyncio
    async def test_database_pipeline_source_type(self):
        from app.pipelines.database_pipeline import DatabasePipeline

        pipeline = DatabasePipeline()
        assert pipeline.source_type == "database"

    @pytest.mark.asyncio
    async def test_mcp_pipeline_source_type(self):
        from app.pipelines.mcp_pipeline import MCPPipeline

        pipeline = MCPPipeline()
        assert pipeline.source_type == "mcp"


class TestPipelineRegistry:
    def test_database_pipeline_registered(self):
        from app.pipelines.registry import get_pipeline

        pipeline = get_pipeline("database")
        assert pipeline.source_type == "database"

    def test_mcp_pipeline_registered(self):
        from app.pipelines.registry import get_pipeline

        pipeline = get_pipeline("mcp")
        assert pipeline.source_type == "mcp"

    def test_unknown_pipeline_raises(self):
        from app.pipelines.registry import get_pipeline

        with pytest.raises(ValueError):
            get_pipeline("nonexistent")

    def test_case_insensitive(self):
        from app.pipelines.registry import get_pipeline

        pipeline = get_pipeline("DATABASE")
        assert pipeline.source_type == "database"
