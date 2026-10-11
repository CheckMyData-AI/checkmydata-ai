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

**2026-10-11: the workflow ships the site only, by hand. 2026-10-12: to Cloudflare.**
The hosted product was switched off (`docs/handoffs/2026-10-11-hosted-product-off.md`) and
the site became a static export on Cloudflare Workers, so the Heroku pipeline above — its
images, the release phase, the worker poll, the releases API — is history. What carries
over is the point of every finding: a deploy must be able to FAIL, and the check after it
must read something only the NEW deploy can produce. `wrangler deploy` exits non-zero on
a refused upload; the verification asks the live site for answers only the Worker gives.

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


class TestTheDeployCanFail:
    def test_every_mutating_curl_fails_on_an_http_error(self, workflow: dict) -> None:
        offenders = []
        for step in _run_steps(workflow):
            body = step["run"]
            for line in body.splitlines():
                if "curl" in line and ("-X PATCH" in line or "-X POST" in line):
                    # A probe that captures the status and compares it reads the status,
                    # which is all `--fail` is for — the waitlist check expects a 422.
                    reads_status = "%{http_code}" in line or "%{http_code}" in body
                    if "--fail" not in body and not reads_status:
                        offenders.append(step.get("name", "<unnamed>"))
        assert not offenders, (
            "these steps change production and exit 0 on an HTTP error, because curl "
            f"does not fail without --fail: {offenders}"
        )

    def test_the_deploy_is_wrangler_and_its_failure_is_not_swallowed(self, workflow: dict) -> None:
        deploy = _step(workflow, "wrangler deploy")
        assert deploy is not None, "nothing deploys the Worker"
        assert "|| true" not in _code(deploy), "a swallowed wrangler failure is a green deploy"
        route = _step(workflow, "attach-site-route")
        assert route is not None, "the Worker is deployed but never put in front of the domain"


class TestTheVerificationReadsTheNewDeploy:
    def test_it_asks_for_an_answer_only_the_worker_gives(self, workflow: dict) -> None:
        """A 200 from the home page proves nothing: the previous origin served one too.
        The Worker's own JSON 404 for an unknown /api path does."""
        step = _step(workflow, "/api/deploy-probe")
        assert step is not None, "the live site is never asked something only the Worker answers"
        assert '{"ok":false,"error":"Not found."}' in _code(step)

    def test_a_retired_route_is_checked_to_redirect(self, workflow: dict) -> None:
        step = _step(workflow, "/login")
        assert step is not None and "#waitlist" in _code(step)


class TestOnlyTheSiteShips:
    def test_no_backend_app_is_released(self, workflow: dict) -> None:
        """A release of `checkmydata-api` would start dynos against a database that no
        longer exists — and start billing for them."""
        joined = "\n".join(_code(s) for s in _run_steps(workflow))
        for needle in ("BACKEND_APP", "checkmydata-api", "registry.heroku.com"):
            assert needle not in joined, f"deploy.yml reaches Heroku again ({needle})"

    def test_the_waitlist_is_checked_without_sending_mail(self, workflow: dict) -> None:
        step = _step(workflow, "/api/waitlist")
        assert step is not None, "nothing checks that the waitlist endpoint was deployed"
        code = _code(step)
        assert "422" in code and "-d '{}'" in code, (
            "the check must post an EMPTY body and expect the validation refusal — a real "
            "sign-up would mail contact@ on every deploy"
        )


class TestTheReleaseImageStaysBuildable:
    def test_a_release_image_exists_and_runs_alembic(self) -> None:
        """Not deployed any more, but kept for a relaunch: it must still describe one."""
        dockerfile = ROOT / "Dockerfile.release"
        assert dockerfile.exists(), "no release image to run the migration"
        body = dockerfile.read_text(encoding="utf-8")
        assert "alembic" in body and "upgrade" in body and "head" in body
        assert "BASE_IMAGE" in body


class TestADeployIsNotCancelledHalfway:
    def test_the_deploy_queues_rather_than_cancels(self, workflow: dict) -> None:
        concurrency = workflow.get("concurrency") or {}
        assert concurrency.get("cancel-in-progress") is False, (
            "a second run can cancel this one between the Worker upload and the route, "
            "leaving the domain on the old origin (TEST-17)"
        )
