"""Which failed documents get retried, and which are quietly forgotten.

`next_regeneration_queue` decides what the next repo-index run will try to regenerate.
Getting a term wrong here does not fail anything: documents simply stop being retried, or
are regenerated forever, and both look like normal operation from outside.

It had no test because it was not reachable as a unit — the expression lived inside
`_finalise`, an eighty-line method that also writes the git index, saves caches, marks
staleness and deletes the checkpoint. Reaching it meant driving the whole pipeline, which
is why `pipeline_runner.py` sat at 53% with this among the uncovered lines.

Each term protects a different failure, so each is asserted on its own:

* subtracting `requeued` is what lets a path **leave** the queue
* the union with `still_failed` is what stops a short run **forgiving** what it never
  reached
"""

from __future__ import annotations

from app.knowledge.pipeline_runner import next_regeneration_queue as queue


def test_a_retried_document_that_succeeded_leaves_the_queue() -> None:
    """It was owed, it was attempted, it is not in the failure list — it worked."""
    assert queue(prior_failed=["a.py"], requeued=["a.py"], still_failed=[]) == []


def test_a_retried_document_that_failed_again_stays() -> None:
    assert queue(prior_failed=["a.py"], requeued=["a.py"], still_failed=["a.py"]) == ["a.py"]


def test_a_document_the_run_never_reached_stays_owed() -> None:
    """The union with `still_failed` is not enough on its own: a run that generated
    nothing must not be read as a run in which everything succeeded."""
    assert queue(prior_failed=["a.py", "b.py"], requeued=[], still_failed=[]) == ["a.py", "b.py"]


def test_a_document_failing_for_the_first_time_is_added() -> None:
    assert queue(prior_failed=[], requeued=["new.py"], still_failed=["new.py"]) == ["new.py"]


def test_a_clean_run_over_a_full_queue_empties_it() -> None:
    assert queue(prior_failed=["a.py", "b.py"], requeued=["a.py", "b.py"], still_failed=[]) == []


def test_the_three_populations_combine_rather_than_replace() -> None:
    """One run holding all four cases at once — the shape a real resume produces."""
    assert queue(
        prior_failed=["owed_untried.py", "owed_retried_ok.py", "owed_retried_failed.py"],
        requeued=["owed_retried_ok.py", "owed_retried_failed.py"],
        still_failed=["owed_retried_failed.py", "newly_broken.py"],
    ) == ["newly_broken.py", "owed_retried_failed.py", "owed_untried.py"]


def test_the_result_is_sorted_and_deduplicated() -> None:
    """The value is persisted, so an unstable order makes every run look like a change
    to anything that compares the stored list."""
    out = queue(prior_failed=["z.py", "a.py", "a.py"], requeued=[], still_failed=["m.py", "a.py"])
    assert out == ["a.py", "m.py", "z.py"]


def test_it_accepts_any_iterable_not_just_lists() -> None:
    """The call site passes whatever `state` holds; a set or a generator must not
    change the answer."""
    assert queue(
        prior_failed={"a.py", "b.py"},
        requeued=(p for p in ["a.py"]),
        still_failed=iter([]),
    ) == ["b.py"]


class TestTheTermsAreLoadBearing:
    """Each assertion below fails if the corresponding term is dropped — which is the
    only way to know the expression is doing three jobs rather than one."""

    def test_without_subtracting_requeued_a_working_document_never_leaves(self) -> None:
        prior, requeued, failed = ["a.py"], ["a.py"], []
        assert queue(prior_failed=prior, requeued=requeued, still_failed=failed) == []
        # what the expression would return with the subtraction removed
        assert sorted(set(prior) | set(failed)) == ["a.py"]

    def test_without_the_union_a_new_failure_is_lost(self) -> None:
        prior, requeued, failed = [], ["new.py"], ["new.py"]
        assert queue(prior_failed=prior, requeued=requeued, still_failed=failed) == ["new.py"]
        # what the expression would return with the union removed
        assert sorted(set(prior) - set(requeued)) == []
