"""A setting nobody reads is a lever an operator pulls during an incident, and nothing moves.

`reranker_enabled` was the loud case: documented as default-on while
`sentence-transformers` was in no dependency list, so it was a no-op in every deployment
that ever ran. That one was findable because it named a missing dependency, which
`ops/capability_report.py` can check at boot.

This is the quieter case, and `capability_report` cannot catch it: a setting that reads
as a tuning knob and is referenced **nowhere outside `config.py`**. There is no
dependency to miss — the value is simply never consulted, while a constant a few files
over decides the behaviour the setting claims to control. `git_freshness_fetch_origin`
had a six-line docstring, an entry in `CLAUDE.md`, a line in `CHANGELOG.md`, and a real
implementation behind it (`GitTracker.classify_freshness_async(..., fetch_origin=...)`)
that both of its two callers declined to reach.

The allowlist below is the honest part: each exemption names why the field is legitimately
unread in application code, and a second test fails when one does not. The point is not
zero exemptions — it is that adding one requires saying something true out loud.
"""

from __future__ import annotations

import pathlib

import pytest

from app.config import Settings

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
CONFIG = APP / "config.py"

#: Fields legitimately unread by application code, each with the reason.
ALLOWED: dict[str, str] = {
    # Read by pydantic-settings itself, or by infrastructure outside `app/`.
    "model_config": "pydantic's own configuration, not a product setting",
    # Read by its own boot validator inside config.py (`:1284`), which is the only
    # place that can refuse a configuration before anything opens a pool.
    "db_connection_ceiling": "consumed by the boot validator in config.py itself",
    # Reached dynamically: `getattr(settings, f"stripe_price_{plan.id}", "")` at
    # `billing_service.py:90`, so the literal name appears in no source file.
    "stripe_price_base": "resolved dynamically by plan id in billing_service.py:90",
    "stripe_price_pro": "resolved dynamically by plan id in billing_service.py:90",
    "stripe_price_scale": "resolved dynamically by plan id in billing_service.py:90",
    "stripe_price_team": "resolved dynamically by plan id in billing_service.py:90",
}

#: Prefixes whose fields are consumed by a framework rather than by our code.
ALLOWED_PREFIXES: tuple[str, ...] = ()


def _declared_fields() -> list[str]:
    return [n for n in Settings.model_fields if not n.startswith("_")]


def _referenced_outside_config() -> set[str]:
    """Every identifier that appears anywhere under `app/` except `config.py`.

    Deliberately textual rather than AST-precise: a field reached through
    `getattr(settings, name)` or named in a string is still *reached*, and a guard
    that only understands attribute access would flag those as dead.
    """
    seen: set[str] = set()
    for path in APP.rglob("*.py"):
        if path == CONFIG:
            continue
        text = path.read_text()
        for field in _declared_fields():
            if field in text:
                seen.add(field)
    return seen


@pytest.mark.parametrize("field", _declared_fields())
def test_every_setting_is_read_somewhere(field: str):
    if field in ALLOWED or field.startswith(ALLOWED_PREFIXES):
        pytest.skip(f"exempt: {ALLOWED.get(field, 'framework-consumed prefix')}")
    assert field in _referenced_outside_config(), (
        f"`{field}` is declared in config.py and read nowhere else under app/. "
        "An operator who sets it during an incident changes nothing — and a constant "
        "somewhere else is deciding the behaviour it claims to control. Either wire it "
        "at the call site, delete it, or add it to ALLOWED with the reason."
    )


def test_the_allowlist_carries_a_reason_for_every_entry():
    for name, reason in ALLOWED.items():
        assert reason and len(reason) > 10, f"{name} is exempt with no reason given"
