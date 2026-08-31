"""The caller list padded itself to the cap with matches from another application.

After #247 the bridge attaches caller refs where it previously attached none, and the
head of each list is genuinely right — `Coupon` gets `ensureCusDevCouponAvailable` and
`isCouponAlreadyApplied` from `CouponRepository.php`. The tail is not: `handle` from
`sendmail/app/Services/Workspaces/AddWorkspaceMember.php` reached a `Coupon` entity
living under `api/app/...`, matched on a method name generic enough to appear in any
codebase.

Every ref carries `confidence: 0.3` (`_CONF_NAME_ONLY`), so the sort key
`(confidence, -depth)` collapses to depth alone and `_max_callers=10` fills whatever
remains with noise. Measured in production: 377 refs across 54 entities, of which 29 sit
at exactly 10 — i.e. truncated, so the noise displaced nothing *and* nothing displaced
the noise.

Two changes. Proximity — how much of the path a caller shares with the entity's own
file — joins the sort key ahead of depth. And a ref that is BOTH name-only and in a
different top-level directory is dropped rather than used as filler: in a repository
holding several applications, the first path segment is what separates them, and a
name-only match across that boundary carries no evidence at all.

Dropping rather than down-ranking, because the cap is what makes down-ranking useless:
with ten slots and four genuine callers, a demoted noise ref still occupies slot five.
"""

from __future__ import annotations

import pytest

from app.knowledge.graph_db_bridge import CallerRef, _path_proximity, rank_callers


def _ref(name: str, path: str, *, confidence: float = 0.3, depth: int = 1) -> CallerRef:
    return CallerRef(
        caller_name=name,
        caller_file=path,
        caller_kind="method",
        endpoint_kind="unknown",
        op_kind="unknown",
        depth=depth,
        confidence=confidence,
    )


class TestProximityIsMeasuredInSharedPathSegments:
    def test_the_same_directory_is_closest(self) -> None:
        assert (
            _path_proximity("api/app/Models/Coupon.php", ["api/app/Models/CouponRepository.php"])
            == 3
        )

    def test_a_shared_application_still_counts(self) -> None:
        assert _path_proximity("api/app/Services/X.php", ["api/app/Models/Coupon.php"]) == 2

    def test_a_different_application_shares_nothing(self) -> None:
        assert (
            _path_proximity(
                "sendmail/app/Services/Workspaces/AddWorkspaceMember.php",
                ["api/app/Models/Coupon.php"],
            )
            == 0
        )

    def test_the_closest_anchor_wins(self) -> None:
        """An entity can resolve to symbols in several files; the nearest one decides."""
        assert (
            _path_proximity(
                "api/app/Models/CouponRepository.php",
                ["sendmail/app/X.php", "api/app/Models/Coupon.php"],
            )
            == 3
        )


class TestTheGenuineCallersComeFirst:
    def test_proximity_outranks_depth_at_equal_confidence(self) -> None:
        anchors = ["api/app/Models/Coupon.php"]
        far = _ref("handle", "sendmail/app/Services/AddWorkspaceMember.php", depth=1)
        near = _ref("isCouponAlreadyApplied", "api/app/Models/CouponRepository.php", depth=3)
        ranked = rank_callers([far, near], anchors, max_callers=10)
        assert [c.caller_name for c in ranked] == ["isCouponAlreadyApplied"], (
            "the far caller should have been dropped, not merely ranked below"
        )

    def test_confidence_still_outranks_proximity(self) -> None:
        """A resolver that actually proved the edge beats one that matched a name, even
        from further away — proximity is a tie-break, not a replacement."""
        anchors = ["api/app/Models/Coupon.php"]
        strong_far = _ref("apply", "api/other/Deep/Nested/Thing.php", confidence=0.9)
        weak_near = _ref("nearby", "api/app/Models/CouponRepository.php", confidence=0.3)
        ranked = rank_callers([strong_far, weak_near], anchors, max_callers=10)
        assert ranked[0].caller_name == "apply"


class TestTheListStopsPaddingWithNoise:
    def test_a_name_only_match_in_another_application_is_dropped(self) -> None:
        anchors = ["api/app/Models/Coupon.php"]
        noise = _ref("handle", "sendmail/app/Services/Workspaces/AddWorkspaceMember.php")
        assert rank_callers([noise], anchors, max_callers=10) == []

    def test_a_name_only_match_in_the_same_application_is_kept(self) -> None:
        """Same application, name-only: weak evidence is still evidence, and dropping it
        would empty most lists in a codebase whose call resolution is name-based."""
        anchors = ["api/app/Models/Coupon.php"]
        weak = _ref("handle", "api/app/Http/Controllers/CouponController.php")
        assert len(rank_callers([weak], anchors, max_callers=10)) == 1

    def test_a_confident_match_across_applications_survives(self) -> None:
        """Distance alone is not disqualifying — a resolved edge across a boundary is a
        real dependency, and a monorepo has those."""
        anchors = ["api/app/Models/Coupon.php"]
        strong = _ref("apply", "sendmail/app/Services/X.php", confidence=0.9)
        assert len(rank_callers([strong], anchors, max_callers=10)) == 1

    def test_the_cap_still_applies(self) -> None:
        anchors = ["api/app/Models/Coupon.php"]
        many = [_ref(f"c{i}", f"api/app/Models/R{i}.php") for i in range(25)]
        assert len(rank_callers(many, anchors, max_callers=10)) == 10


class TestItDegradesSensibly:
    def test_no_anchors_means_no_proximity_signal_and_nothing_is_dropped(self) -> None:
        """Without a file to measure against, every ref is equidistant. Dropping them
        all would turn a missing input into a missing answer."""
        noise = _ref("handle", "sendmail/app/Services/X.php")
        assert len(rank_callers([noise], [], max_callers=10)) == 1

    def test_an_empty_input_is_an_empty_output(self) -> None:
        assert rank_callers([], ["api/app/Models/Coupon.php"], max_callers=10) == []


@pytest.mark.parametrize("bad", ["", "/", "///"])
def test_degenerate_paths_do_not_raise(bad) -> None:
    assert _path_proximity(bad, [bad]) >= 0
