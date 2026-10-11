"""The only gate between a merged commit and production could not report a failure.

Five findings, one pipeline (P0-4; TEST-01, TEST-15, TEST-16, TEST-17, DATA-10).

**The release step cannot fail.** The two `curl -s -X PATCH` calls that put the new image
into production pass no `--fail`, read no status and inspect no body, and `curl` exits 0 on
any HTTP status. A rotated `HEROKU_API_KEY` (401), a quota refusal (403), a renamed app
(404) or an image id Heroku will not accept (422) is a **passing step**.

**And the verification that follows checks the previous release.** It polls the public
health URL, which is served by whatever release is currently live — so when the release
never happened, the old one answers 200 and the job goes green. Production silently stops
receiving deploys while the pipeline stays green (TEST-01).

**Migrations run in no channel this pipeline uses** (TEST-15). `deploy.yml` PATCHes the
formation with images whose CMD is uvicorn-only; `Dockerfile.worker` says in its own comment
that "the repo Procfile is not honored" for container releases; `heroku.yml`'s `run.web`
belongs to a channel this pipeline does not use. Measured on production 2026-09-11:
`heroku ps` shows the web formation running `sh -c uvicorn app.main:app …`, with no alembic
in it. `alembic_version` happens to equal the repository head — because some other channel
applied it once, not because this pipeline applies anything.

**The worker is verified by nothing** (TEST-16): both verify steps check HTTP, and the
worker serves no HTTP. The repo's own incident history says the worker is the recurring
failure surface.

**`cancel-in-progress: true` can cancel between the two release steps** (TEST-17), leaving
the backend on the new sha and the frontend on the old one until the next run's ten-minute
build finishes.

**2026-10-11: the workflow ships the site only, by hand.** The hosted product was switched
off (`docs/handoffs/2026-10-11-hosted-product-off.md`), so the backend half — its three
images, the release phase, the worker poll — left `deploy.yml`; it is in git history for a
relaunch. The guards for that half went with it (`Dockerfile.release` is still checked,
because it still exists), and one was added: the site's own check must prove the waitlist
endpoint is deployed without mailing the team inbox on every deploy. Everything that made
the release step able to fail still applies to the one release left.

This file reads the workflow as **YAML**, not as text. A guard that greps its own subject
matches its own comments — the shape this audit files as TEST-04, met three times while
closing these rows.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).parents[2].parent
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))


def _run_steps(workflow: dict) -> list[dict]:
    return [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and step.get("run")
    ]


def _code(step: dict) -> str:
    """A run block with its shell comments removed.

    Every guard in this file that reads a step's body reads THIS, because three separate
    drafts went red against their own explanatory comments — the TEST-04 shape the audit
    names, met four times in one day. A guard that cannot tell code from prose about code
    is a guard the next reader deletes.
    """
    return "\n".join(line for line in step["run"].splitlines() if not line.lstrip().startswith("#"))


def _step(workflow: dict, needle: str) -> dict | None:
    for step in _run_steps(workflow):
        if needle in step["run"]:
            return step
    return None


class TestTheReleaseStepCanFail:
    def test_every_mutating_curl_fails_on_an_http_error(self, workflow: dict) -> None:
        offenders = []
        for step in _run_steps(workflow):
            body = step["run"]
            for line in body.splitlines():
                if "curl" in line and ("-X PATCH" in line or "-X POST" in line):
                    # A probe that captures the status and compares it reads the status,
                    # which is all `--fail` is for — the waitlist check expects a 422,
                    # which `--fail` would turn into an exit code.
                    reads_status = "%{http_code}" in line or "%{http_code}" in body
                    if "--fail" not in body and not reads_status:
                        offenders.append(step.get("name", "<unnamed>"))
        assert not offenders, (
            "these steps PATCH production and exit 0 on 401/403/404/422, because curl "
            f"does not fail on an HTTP error without --fail: {offenders}"
        )

    def test_the_release_is_verified_by_the_platform_not_by_a_public_url(
        self, workflow: dict
    ) -> None:
        """A health URL answers from whatever is live — including the release that did not
        get replaced. The release itself has to be read from the API that created it."""
        reading = [s for s in _run_steps(workflow) if "/releases" in s["run"]]
        assert reading, (
            "nothing reads the releases API, so a release that never happened is "
            "indistinguishable from one that did (TEST-01)"
        )
        # Two steps read it — one before the deploy to capture the baseline, one after to
        # compare. The one that decides has to check the status as well as the version.
        assert any("succeeded" in s["run"] for s in reading), (
            "the release's status is not checked — a release whose release-phase command "
            "failed is reported as a deploy"
        )
        assert any("failed" in s["run"] for s in reading), (
            "a release stuck in `failed` is never distinguished from one still `pending`"
        )

    def test_the_releases_query_asks_for_the_newest_not_the_first_page(
        self, workflow: dict
    ) -> None:
        """The collection is paginated and ASCENDING — found by this pipeline failing its
        own first deploy (2026-09-11).

        A plain `GET /releases` returns releases 1..200 on an app that is at 375, so
        `[.[].version] | max` reads 200. The version then never appears to move, the
        verification waits out its attempts, and the job fails on a release that had
        already succeeded — a false red, which is the same class of defect as the false
        green it replaced: the check was reading something other than what it claimed.
        """
        for step in _run_steps(workflow):
            code = _code(step)
            if "/releases" not in code:
                continue
            assert "Range: version" in code, (
                f"{step.get('name', '<unnamed>')!r} reads the releases collection with no "
                "Range header, so it sees the first page — the OLDEST 200 releases"
            )
            assert "| max" not in code, (
                "taking max() over a page is what made the first page look like the whole "
                "collection; ask the API for the newest release instead"
            )

    def test_the_new_release_version_is_compared_with_the_old_one(self, workflow: dict) -> None:
        joined = "\n".join(s["run"] for s in _run_steps(workflow))
        assert "BEFORE_VERSION" in joined, (
            "no before/after comparison of the release version, so 'a release exists' is "
            "read as 'my release happened'"
        )


class TestOnlyTheSiteShips:
    def test_no_backend_app_is_released(self, workflow: dict) -> None:
        """A release of `checkmydata-api` would start dynos against a database that no
        longer exists — and start billing for them."""
        joined = "\n".join(_code(s) for s in _run_steps(workflow))
        assert "BACKEND_APP" not in joined and "checkmydata-api" not in joined, (
            "deploy.yml releases the backend again; it was switched off on 2026-10-11"
        )

    def test_the_waitlist_is_checked_without_sending_mail(self, workflow: dict) -> None:
        step = _step(workflow, "/api/waitlist")
        assert step is not None, "nothing checks that the waitlist endpoint was deployed"
        code = _code(step)
        assert "422" in code and "-d '{}'" in code, (
            "the check must post an EMPTY body and expect the validation refusal — a real "
            "sign-up would mail contact@ on every deploy"
        )


class TestMigrationsRunInTheChannelThatDeploys:
    def test_a_release_image_exists_and_runs_alembic(self) -> None:
        dockerfile = ROOT / "Dockerfile.release"
        assert dockerfile.exists(), "no release image to run the migration"
        body = dockerfile.read_text(encoding="utf-8")
        assert "alembic" in body and "upgrade" in body and "head" in body
        assert "BASE_IMAGE" in body, (
            "the release image must be the deployed backend image with a different CMD, "
            "as Dockerfile.worker already is — a separately built one can drift from it"
        )


class TestAReleaseIsNotCancelledHalfway:
    def test_the_deploy_queues_rather_than_cancels(self, workflow: dict) -> None:
        concurrency = workflow.get("concurrency") or {}
        assert concurrency.get("cancel-in-progress") is False, (
            "a second merge can cancel this run between the backend release and the "
            "frontend release, leaving the two on different commits until the next "
            "ten-minute build finishes (TEST-17)"
        )
