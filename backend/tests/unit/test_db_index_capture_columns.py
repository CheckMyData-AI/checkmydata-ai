from __future__ import annotations

from app.models.db_index import DbIndex


def test_db_index_has_capture_columns():
    cols = set(DbIndex.__table__.columns.keys())
    for name in (
        "enum_labels_json",
        "check_constraints_json",
        "sort_keys_json",
        "column_stats_json",
        "object_kind",
    ):
        assert name in cols, f"missing {name}"


def test_db_index_capture_defaults():
    # SQLAlchemy applies column defaults on flush; assert the mapped default value.
    assert DbIndex.__table__.c.object_kind.default.arg == "table"
    assert DbIndex.__table__.c.enum_labels_json.default.arg == "{}"
    assert DbIndex.__table__.c.sort_keys_json.default.arg == "[]"
