"""Every module in `app/models` is imported by `app/models/__init__.py` (DATA-05, B-02).

`alembic/env.py` and the integration harness both read `Base.metadata`, which is filled by
what `__init__` imports. A model module missing from it has a table in production and no
table anywhere the code checks: `audit_log` was the first (DATA-05), `llm_credit` the
second — found only when the integration suite ran on PostgreSQL.
"""

from pathlib import Path

MODELS = Path(__file__).resolve().parents[3] / "app" / "models"


def test_every_model_module_is_imported() -> None:
    init = (MODELS / "__init__.py").read_text()
    modules = {p.stem for p in MODELS.glob("*.py")} - {"__init__", "base"}
    missing = sorted(m for m in modules if f"from app.models.{m} import" not in init)
    assert not missing, f"not imported by app/models/__init__.py: {missing}"
