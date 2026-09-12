"""Six documents that described a product other than the one that ships.

P3 row 23; BIZ-08, BIZ-10, API-13, ANA-08, ANA-09 and OPS-12.

- **BIZ-08** — an answer could go out with real rows, a real explanation and
  `query: null`, while the landing page promises the SQL is always shown. The comment
  above the back-fill says the three must stay consistent and back-filled two of them.
- **BIZ-10** — `vision.md` §8 denied storing production data while the product stores
  up to 500 rows per answer and per-column value samples. The Terms and Privacy pages
  disclose both; §8, the one described as load-bearing, did not.
- **API-13** — the rate-limiting paragraph named five throttled endpoints as
  unthrottled and stated a route count seven low, with the billing paths missing the
  router's own prefix.
- **ANA-08** — two required-field lists validated the same service-account JSON. The
  store accepted a key the adapter refuses, so a 422 the user could have fixed with
  the file still open arrived hours later as a `_connect` sentinel nobody watches.
- **ANA-09** — the runbook carried a standing caveat about a `_connect` bug the code
  explicitly does not have.
- **OPS-12** — `config.py` asserted `21600 < 7200` and cited a test that had
  deliberately deleted that assertion — the exact error the test file exists to stop
  anybody repeating.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re
import textwrap

_BACKEND = pathlib.Path(__file__).resolve().parents[3]
_ROOT = _BACKEND.parent
_ROUTES = _BACKEND / "app" / "api" / "routes"
_MUTATING = ("post", "put", "patch", "delete")


def _mutating_routes() -> tuple[int, int, list[str]]:
    """`(total, limited, unthrottled names)` read from the route tree."""
    total = limited = 0
    bare: list[str] = []
    for path in sorted(_ROUTES.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            methods = [
                verb
                for d in node.decorator_list
                if isinstance(d, ast.Call)
                for verb in _MUTATING
                if ast.unparse(d.func).endswith("." + verb)
            ]
            if not methods:
                continue
            total += 1
            if any("limiter.limit" in ast.unparse(d) for d in node.decorator_list):
                limited += 1
            else:
                bare.append(f"{path.stem}.{node.name}")
    return total, limited, sorted(bare)


class TestAnAnswerCanShowItsSql:
    """BIZ-08."""

    def test_the_query_is_back_filled_with_its_siblings(self) -> None:
        from app.agents.orchestrator import OrchestratorAgent

        source = textwrap.dedent(inspect.getsource(OrchestratorAgent))
        tree = ast.parse(source)
        blocks = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and "sql_result_blocks[-1].results" in ast.unparse(node.body)
        ]
        assert blocks, "the back-fill is gone; this guard is blind"
        # The exact expression, because `"…[-1].query" in "…[-1].query_explanation"` is
        # True — the substring form of this guard passed against its own planted
        # defect, matching the sibling line it was supposed to be compared against.
        back_filled = {
            ast.unparse(node.value)
            for block in blocks
            for node in block.body
            if isinstance(node, ast.Assign)
        }
        assert "sql_result_blocks[-1].query" in back_filled, (
            "`primary_results` and `primary_explanation` are back-filled from the last "
            "block, with a comment saying the three must stay consistent — and `query` "
            "is not. An answer goes out with real rows and a null query, `chat.py` "
            "persists a null query beside them, and neither the response nor the "
            "stored message can show the SQL the landing page promises (BIZ-08)"
        )


class TestTheVisionNamesWhatIsStored:
    """BIZ-10."""

    def test_the_anti_vision_carves_out_the_answer_trace(self) -> None:
        section = (_ROOT / "vision.md").read_text(encoding="utf-8").split("## 8. Anti-Vision", 1)
        assert len(section) == 2, "§8 is gone; this guard is blind"
        body = section[1].split("\n## ", 1)[0].lower()
        assert "row_cap" in body or "value samples" in body or "raw_result" in body, (
            "§8 denies storing production data while `chat_messages.metadata_json` "
            "holds up to `chat_raw_result_row_cap` rows of it per answer and "
            "`db_index.column_distinct_values_json` holds per-column samples. The "
            "Terms and Privacy pages disclose both; the document described as "
            "load-bearing contradicts them (BIZ-10)"
        )


class TestTheRateLimitParagraphIsMeasured:
    """API-13."""

    def test_the_stated_counts_match_the_route_tree(self) -> None:
        total, limited, bare = _mutating_routes()
        text = (_ROOT / "API.md").read_text(encoding="utf-8")

        claimed = re.search(
            r"\*\*(\d+)\s+mutating routes,\s*(\d+)\s+carrying\s+`@limiter\.limit`,"
            r"\s*(\d+)\s+without",
            text,
        )
        assert claimed is not None, (
            "API.md no longer states the measurement, so nothing can go stale — and "
            "nothing can be checked either"
        )
        assert (int(claimed.group(1)), int(claimed.group(2)), int(claimed.group(3))) == (
            total,
            limited,
            len(bare),
        ), (
            f"API.md says {claimed.groups()} and the tree has "
            f"({total}, {limited}, {len(bare)}): {bare}. The paragraph before this one "
            "named five endpoints as unthrottled that carry limiters, and gave the "
            "billing paths without the router's own `/billing` prefix (API-13)"
        )


class TestOneListValidatesTheCredential:
    """ANA-08."""

    def test_the_store_is_not_more_permissive_than_the_adapter(self) -> None:
        from app.analytics.ga4.config import REQUIRED_SA_FIELDS
        from app.services.vendor_credential_service import _GA4_REQUIRED_FIELDS

        assert set(REQUIRED_SA_FIELDS) <= set(_GA4_REQUIRED_FIELDS), (
            f"the store demands {sorted(_GA4_REQUIRED_FIELDS)} and the adapter demands "
            f"{sorted(REQUIRED_SA_FIELDS)}. The store is the layer that can answer 422 "
            "while the user still has the file open; the adapter's refusal surfaces "
            "hours later as a `_connect` sentinel row (ANA-08)"
        )


class TestTheRunbookDescribesThisCode:
    """ANA-09."""

    def test_it_does_not_report_a_bug_the_code_does_not_have(self) -> None:
        runbook = (_ROOT / "docs" / "ANALYTICS_SOURCES.md").read_text(encoding="utf-8")
        assert "the entry is currently\n> **included**" not in runbook, (
            "the runbook told operators the `_connect` sentinel appears as a sixth row "
            "in `reports[]`, and `connection_service` subtracts it explicitly. A "
            "runbook describing a defect the code does not have sends the reader "
            "looking for something that is not there (ANA-09)"
        )

    def test_the_code_still_subtracts_it(self) -> None:
        from app.services import connection_service

        source = inspect.getsource(connection_service)
        assert "- {CONNECT_SENTINEL_REPORT}" in source, (
            "the runbook now says the sentinel is excluded; make sure it still is"
        )


class TestTheTwoCeilingsAreNotTiedTogether:
    """OPS-12."""

    def test_the_comment_does_not_assert_a_false_relation(self) -> None:
        from app.config import Settings

        settings = Settings()
        config_text = (_BACKEND / "app" / "config.py").read_text(encoding="utf-8")

        full_rebuild = settings.repo_index_job_timeout_seconds
        nightly = settings.daily_knowledge_sync_job_timeout_seconds
        assert full_rebuild > nightly, (
            "the premise of this guard is wrong: the two ceilings no longer disagree, "
            "so re-read whether the comment should be restored"
        )
        assert "stays below `daily_knowledge_sync_job_timeout_seconds`" not in config_text, (
            f"the comment claims {full_rebuild} stays below {nightly}, and cites a test "
            "whose docstring explains that this invariant was deliberately REMOVED "
            "because tying them capped the manual path below what a full rebuild needs "
            "(OPS-12)"
        )
