from app.knowledge import pii_scrubber as p


def test_sensitive_column_detection():
    assert p.is_sensitive_column("password_hash")
    assert p.is_sensitive_column("user_API_Key")
    assert not p.is_sensitive_column("created_at")


def test_redact_email_phone_card_jwt():
    assert "[redacted-email]" in p.redact_value("contact a@b.com please")
    assert "[redacted-card]" in p.redact_value("4111 1111 1111 1111")
    assert "[redacted-jwt]" in p.redact_value("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def")
    assert p.redact_value("just text") == "just text"


def test_scrub_distinct_sensitive_column_returns_cardinality_only():
    out = p.scrub_distinct_values("email", ["a@b.com", "c@d.com"])
    assert out == ["[redacted: 2 values]"]


def test_scrub_distinct_disabled_returns_raw():
    assert p.scrub_distinct_values("email", ["a@b.com"], enabled=False) == ["a@b.com"]


def test_scrub_sample_json_redacts_and_survives_bad_json():
    good = '[{"email": "a@b.com", "note": "call 415-555-1212"}]'
    out = p.scrub_sample_json(good)
    assert "a@b.com" not in out and "415-555-1212" not in out
    # non-JSON still masked, not raw
    assert "a@b.com" not in p.scrub_sample_json("raw blob a@b.com")
    assert p.scrub_sample_json("anything", enabled=False) == "anything"


def test_scrub_row_cells_redacts_sensitive_columns():
    cols = ["id", "password", "email"]
    rows = [[1, "hunter2", "a@b.com"]]
    out = p.scrub_row_cells(cols, rows)
    assert out[0][0] == 1
    assert "hunter2" not in str(out[0][1])
    assert "a@b.com" not in str(out[0][2])
