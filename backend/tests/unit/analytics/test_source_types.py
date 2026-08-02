"""``ANALYTICS_SOURCE_TYPES`` has exactly one definition (T14, gap 2).

The constant answers "is this connection an analytics vendor?" and is consulted
from four unrelated places — the cron dispatcher, the collect service, the
orchestrator's tool gating and the tool dispatcher's connection resolution. It
was defined twice (a tuple in ``app.services.analytics_collect_service`` and a
frozenset in ``app.agents.tools.analytics_tools``), and each docstring claimed
to be the only one. Two definitions of a membership set drift: adding a vendor
to one of them leaves half the system unable to see connections the other half
happily creates.

The first test is structural on purpose. Asserting the *values* agree only
proves they agree today; walking the AST proves there is nothing left to drift.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[3] / "app"

CANONICAL_MODULE = APP_ROOT / "analytics" / "source_types.py"


def _assignment_sites() -> list[str]:
    """Every module under ``app/`` that *assigns* ``ANALYTICS_SOURCE_TYPES``.

    An ``import`` of the name is a re-export, not a definition; only a binding
    that creates a new value can drift, so only assignments are counted.
    """
    sites: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "ANALYTICS_SOURCE_TYPES":
                    sites.append(str(path.relative_to(APP_ROOT)))
    return sites


def test_exactly_one_definition_in_the_tree() -> None:
    assert _assignment_sites() == [str(CANONICAL_MODULE.relative_to(APP_ROOT))]


def test_both_legacy_import_sites_resolve_to_the_canonical_object() -> None:
    """Identity, not equality — equal-but-separate values are the bug."""
    from app.agents.tools import analytics_tools
    from app.analytics import source_types
    from app.services import analytics_collect_service

    canonical = source_types.ANALYTICS_SOURCE_TYPES
    assert analytics_collect_service.ANALYTICS_SOURCE_TYPES is canonical
    assert analytics_tools.ANALYTICS_SOURCE_TYPES is canonical


def test_canonical_value_still_covers_every_vendor() -> None:
    from app.analytics.source_types import ANALYTICS_SOURCE_TYPES

    assert set(ANALYTICS_SOURCE_TYPES) == {"ga4", "appstore", "googleplay"}


def test_canonical_module_stays_import_light() -> None:
    """The constant must be importable without dragging in the GA4 client libs.

    ``analytics_collect_service`` imports the GA4 adapter and google-api client
    packages; if the constant lived there, every consumer — including the
    orchestrator's tool gating on the hot path — would pay for that import (and
    ``analytics_tools`` would risk an import cycle). Keeping the canonical
    module dependency-free is what makes the single definition affordable.
    """
    tree = ast.parse(CANONICAL_MODULE.read_text(encoding="utf-8"), filename=str(CANONICAL_MODULE))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    assert [name for name in imported if name.startswith("app.")] == []
