"""Five public claims the code contradicts (P0-5; BIZ-03, BIZ-09, BIZ-11, BIZ-13, BIZ-15).

A sibling of `test_privacy_claims_match_storage.py`, which pins what is **stored**. This
file pins what is **sent**, **who receives it**, **what the system is made of**, and **what
is for sale** — four different promises that drifted the same way, by being written once and
then outliving the architecture they described.

- **BIZ-03** — the Privacy Policy's two-column table listed `Raw database rows/values` under
  **NOT sent to LLM**. `format_query_results` renders up to `max_rows` (20) of the
  customer's actual result rows into the `execute_query` tool message on every answer, and
  sampled column values ride the schema context. The product's whole ask is production
  database credentials, and this is the sentence a security review reads first.
- **BIZ-11** — §6 "Third-Party Services" enumerated LLM providers and Google OAuth. Stripe
  receives the user's email and display name at first checkout; Sentry receives error events
  from both the backend and the browser. The landing page said "No tracking, no telemetry".
- **BIZ-15** — §5 described a "local-first architecture" of SQLite and ChromaDB, and §9 said
  the authentication token lives in local storage. The hosted deployment runs Supabase
  PostgreSQL with pgvector, and auth has been an httpOnly cookie since the cookie-auth work.
- **BIZ-09** — the pricing FAQ sold a Free plan and a Pro tier, both retired on 2026-08-31.
- **BIZ-13** — the README advertised the cross-encoder reranker as default-on; it is
  default-off and a no-op in every deployment that has ever run.

**Why these are text tests.** In all five the code is doing what it was built to do; the
false statement is on the page. A test that reads the page is the only thing that fails when
someone restores a comfortable sentence years after the system it described stopped existing.
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).parents[4]
PAGES = ROOT / "frontend" / "src" / "app" / "(marketing)"
README = ROOT / "README.md"


def _page(name: str) -> str:
    path = PAGES / name / "page.tsx" if name else PAGES / "page.tsx"
    return path.read_text(encoding="utf-8")


class TestWhatReachesTheModel:
    """BIZ-03."""

    def test_the_policy_does_not_deny_sending_result_rows(self) -> None:
        text = _page("privacy")
        forbidden = [
            "Raw database rows/values",
            "Raw database rows / values",
            "raw rows are never sent",
        ]
        found = [p for p in forbidden if p in text]
        assert not found, (
            f"the Privacy Policy lists {found!r} as NOT sent to the LLM. "
            "`result_handler.format_query_results` puts up to 20 result rows into the "
            "`execute_query` tool message on every answer (result_handler.py:57, reached "
            "from sql_agent.py:649), and db_index sends sampled column values with the "
            "schema. Either the sentence is wrong or the agent changed — check which."
        )

    def test_the_policy_says_what_is_actually_sent_and_how_much(self) -> None:
        text = _page("privacy").lower()
        assert "result rows" in text or "rows of your results" in text, (
            "the policy never tells the reader that their data rows reach the model"
        )
        assert "20" in text, (
            "the bound is missing: 'rows are sent' without the cap reads as 'all of them'"
        )


class TestWhoElseReceivesData:
    """BIZ-11. Two processors the pages never named."""

    @pytest.mark.parametrize("processor", ["Stripe", "Sentry"])
    def test_the_third_party_section_names_the_processor(self, processor: str) -> None:
        assert processor in _page("privacy"), (
            f"{processor} receives user data and appears nowhere in the Privacy Policy. "
            "Stripe gets email and display name at first checkout "
            "(billing_service.py:185-190); Sentry receives error events from the backend "
            "and from the browser (instrumentation-client.ts)."
        )

    def test_the_landing_page_does_not_claim_there_is_no_telemetry(self) -> None:
        text = _page("")
        assert "no telemetry" not in text.lower(), (
            "the landing page says there is no telemetry while Sentry is wired on both "
            "sides. Error monitoring is telemetry by any reading a reader would accept."
        )


class TestTheArchitectureDescribedIsTheOneThatRuns:
    """BIZ-15."""

    def test_the_policy_does_not_present_sqlite_as_the_storage(self) -> None:
        text = _page("privacy")
        assert "local-first architecture" not in text, (
            "the policy describes a local-first SQLite/ChromaDB deployment. The hosted "
            "service runs Supabase PostgreSQL with pgvector; SQLite is the self-hosted "
            "and development path, which is a different sentence."
        )

    def test_the_policy_does_not_put_the_auth_token_in_local_storage(self) -> None:
        """Proximity, not a page-wide conjunction.

        The first draft flagged any page containing both "authentication token" and "local
        storage" — and the page legitimately says UI preferences live in local storage,
        which is true and should stay. A guard that cannot tell a true sentence from a
        false one teaches the next reader to delete it.
        """
        lowered = _page("privacy").lower()
        for idx in range(len(lowered)):
            idx = lowered.find("local storage", idx)
            if idx == -1:
                break
            window = lowered[max(0, idx - 220) : idx]
            assert "authentication token" not in window and "session" not in window, (
                "the policy places the session token in local storage. It is an httpOnly "
                "cookie — the stronger claim, and the one a security reviewer checks."
            )
            idx += 1

    def test_the_policy_names_the_cookie_it_actually_uses(self) -> None:
        assert "httpOnly" in _page("privacy"), (
            "nothing on the page tells the reader the session cookie is httpOnly"
        )

    def test_the_hosted_stack_is_named(self) -> None:
        text = _page("privacy")
        assert "PostgreSQL" in text, "the policy never names the database the service runs on"


class TestNothingRetiredIsStillForSale:
    """BIZ-09. `free` and `pro` were retired from sale on 2026-08-31."""

    def test_the_pricing_page_does_not_sell_a_free_plan(self) -> None:
        text = _page("pricing")
        assert "Free plan" not in text, (
            "the pricing FAQ offers a Free plan. It was retired on 2026-08-31 and "
            "`_no_plan()` means an unsubscribed account resolves to no tier at all."
        )

    def test_the_pricing_page_does_not_sell_a_pro_tier(self) -> None:
        text = _page("pricing")
        assert "Pro and Team" not in text and "Pro plan" not in text, (
            "the pricing FAQ names a Pro tier; the ladder is base/scale/team/enterprise"
        )

    def test_every_tier_the_faq_names_exists_in_the_catalogue(self) -> None:
        from app.services.plan_catalogue import PAID_TIERS

        names = {t["name"] for t in PAID_TIERS}
        text = _page("pricing")
        for retired in ("Free", "Pro"):
            if retired in names:  # pragma: no cover - only if the ladder changes back
                continue
            assert f"{retired} " not in text.replace("free trial", "").replace("for free", ""), (
                f"the pricing page still names the retired tier {retired!r}"
            )


class TestTheReadmeDoesNotSellAnInertFeature:
    """BIZ-13."""

    def test_the_reranker_is_not_advertised_as_on(self) -> None:
        """Proximity again, and for the third time in this file's own history.

        A page-wide conjunction of "reranker" and "default-on" fails against the corrected
        text, which says the *hybrid retrieval* is default-on and the reranker is not —
        two true statements in one bullet. The claim to catch is the one that attaches
        "default-on" to the reranker, so the window is what matters.
        """
        from app.config import settings

        lowered = README.read_text(encoding="utf-8").lower()
        if settings.reranker_enabled:  # pragma: no cover - only if the flag flips
            return
        idx = 0
        while (idx := lowered.find("reranker", idx)) != -1:
            window = lowered[idx : idx + 90]
            assert "default-on" not in window, (
                "the README advertises the cross-encoder reranker as default-on while "
                "`reranker_enabled` is False and `sentence-transformers` is not in the "
                "production image — a no-op in every deployment that has ever run"
            )
            idx += 1
