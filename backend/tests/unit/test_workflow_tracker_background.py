from app.core.workflow_tracker import BACKGROUND_PIPELINES


def test_daily_sync_is_background_pipeline():
    assert "daily_sync" in BACKGROUND_PIPELINES
    assert {"index_repo", "db_index", "code_db_sync"} <= BACKGROUND_PIPELINES
