def test_r5_sync_remediation_defaults():
    from app.config import settings

    assert settings.sync_pii_scrubbing_enabled is True
    assert settings.sync_min_confidence_to_enforce_filters == 2
    assert settings.sync_min_success_ratio_to_persist == 0.5
    assert settings.sync_budget_enforcement_enabled is True
