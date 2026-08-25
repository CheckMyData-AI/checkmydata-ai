"""Every pull request gets CI, including one that targets another branch.

`ci.yml` triggered on `pull_request: branches: [main]` — pull requests whose **base** is
`main`. PR #218 was stacked on PR #217, so its base was `proj/role-domain`, and
`gh run list --branch proj/leave-and-caps` returned nothing: over its whole life that PR
had run **zero** checks.

That is how three raw git conflict markers reached a branch and sat there through
review. They were not missed by a check that looked; nothing looked. And the failure
mode is the worst kind, because the PR page shows no red — an unmeasured branch and a
passing one are visually identical.

The `push` trigger stays scoped to `main` on purpose: every branch push does not need a
full run, and the PR trigger already covers the work. What must not be scoped is the
pull-request one, because the base branch of a PR says nothing about whether its diff
deserves testing.

The second assertion guards the blast radius of the first. `deploy.yml` fires on a
completed CI run whose head branch is `main`; widening CI means PR-triggered runs now
exist that did not before, so the deploy job additionally requires the CI run to have
come from a `push`. A PR opened *from* `main` is the one shape that could otherwise
reach the deploy path through a pull request.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[4] / ".github" / "workflows"


def _load(name: str) -> dict:
    # PyYAML parses the unquoted key `on:` as the boolean True (YAML 1.1's "y/yes/on"
    # rule). Both spellings are checked so the test does not depend on how the file
    # happens to quote it.
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.get("on", data.get(True))
    return data


def test_the_workflows_are_there_to_read() -> None:
    assert (WORKFLOWS / "ci.yml").exists()
    assert (WORKFLOWS / "deploy.yml").exists()


def test_ci_runs_on_a_pull_request_whatever_its_base() -> None:
    triggers = _load("ci.yml")["on"]
    assert "pull_request" in triggers, "CI must run on pull requests at all"
    pr = triggers["pull_request"]
    assert not (pr or {}).get("branches"), (
        "ci.yml filters pull requests by base branch. A stacked PR — one whose base is "
        "another feature branch — then runs no checks at all, and its page shows no red "
        "because nothing ran. PR #218 shipped three git conflict markers this way."
    )


def test_push_stays_scoped_to_main() -> None:
    """Not an oversight to fix: the PR trigger already covers branch work, and running
    a full suite on every push to every branch buys nothing."""
    push = _load("ci.yml")["on"].get("push") or {}
    assert push.get("branches") == ["main"]


def test_deploy_only_follows_a_push_to_main() -> None:
    """Widening CI creates PR-triggered runs that did not exist before. The deploy job
    must not be reachable from one."""
    deploy = _load("deploy.yml")
    trigger = deploy["on"]["workflow_run"]
    assert trigger["branches"] == ["main"]

    condition = deploy["jobs"]["deploy"]["if"]
    assert "conclusion == 'success'" in condition
    assert "event == 'push'" in condition, (
        "a CI run triggered by a pull request must not reach the deploy job; the base "
        "branch filter alone does not exclude a PR opened from `main`"
    )


@pytest.mark.parametrize("name", ["ci.yml", "deploy.yml"])
def test_the_file_parses_as_yaml(name: str) -> None:
    assert isinstance(_load(name), dict)
