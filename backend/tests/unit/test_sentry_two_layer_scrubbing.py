"""Sentry needs two scrubbing layers, because each one misses what the other catches.

Sentry's built-in `EventScrubber` matches **key names**. It does not look inside string
values, so a credential embedded in a URL — in a message, an exception value, a
breadcrumb — passes through untouched. `before_send` was written for exactly that, and
this codebase has had it since T-OBS-1.

But `before_send` here walked only `exception.values`, `logentry` and `breadcrumbs`. It
never walked `extra` or `contexts` — and the built-in scrubber's denylist does not carry
`dsn` or `database_url`. So a key of either name, in either of those two places, was
caught by **neither layer**.

Measured on `sentry-sdk` 2.64.0 (2026-08-26), before the fix:

    DEFAULT_DENYLIST holds 33 keys; 'dsn', 'database_url', 'auth_key' are not among them
    scrub_event({"extra": {"database_url": "postgresql://u:SUPERSECRET@h/db"}})
      → SUPERSECRET survived
    scrub_event({"contexts": {"conn": {"dsn": "postgresql://u:SECRET2@h/db"}}})
      → SECRET2 survived

That mattered from the moment `SENTRY_DSN` was set in production on 2026-08-25: a
service that merely logs a database URL starts forwarding the password to a third party,
with a wider blast radius than the log had.

`test_layer_one_alone_still_leaks_values` is deliberately an assertion about Sentry
rather than about this code. If it ever goes red, the SDK has started scrubbing values
and layer 2 may be redundant — which is a thing to learn from a red test rather than
never.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

from app.core.sentry import EXTRA_DENYLIST, init_sentry, scrub_event

SECRET = "SUPERSECRET"
URL = f"postgresql://user:{SECRET}@db.internal:5432/app"


class TestLayerOneIsNecessaryAndNotSufficient:
    def test_layer_one_alone_still_leaks_values(self) -> None:
        """Sentry's scrubber matches keys, not values. This is the reason `before_send`
        exists; if this ever fails, re-read whether layer 2 is still load-bearing."""
        event = {"message": f"could not connect to {URL}"}
        EventScrubber().scrub_event(event)
        assert SECRET in str(event)

    @pytest.mark.parametrize("key", ["dsn", "database_url", "auth_key"])
    def test_the_keys_that_matter_here_are_not_in_the_default_denylist(self, key: str) -> None:
        """Version-dependent, so it is measured rather than trusted. When one of these
        joins the default list, the entry in EXTRA_DENYLIST becomes redundant — harmless,
        but worth knowing."""
        assert key not in DEFAULT_DENYLIST

    def test_our_denylist_extends_rather_than_replaces(self) -> None:
        """Naming only the extras would drop the 33 keys Sentry already covers —
        `password`, `token`, `api_key`, `authorization` among them."""
        assert set(DEFAULT_DENYLIST).issubset(set(EXTRA_DENYLIST))
        assert set(EXTRA_DENYLIST) - set(DEFAULT_DENYLIST)


class TestLayerTwoWalksEverywhereAValueCanHide:
    """One test per container `scrub_event` must reach. Each was a real hole or is a
    real guard; `extra` and `contexts` are the two that were leaking."""

    def test_exception_value(self) -> None:
        event = {"exception": {"values": [{"value": f"connect failed: {URL}"}]}}
        assert SECRET not in str(scrub_event(event))

    def test_log_message(self) -> None:
        event = {"logentry": {"message": f"dsn={URL}", "formatted": f"dsn={URL}"}}
        assert SECRET not in str(scrub_event(event))

    def test_breadcrumb(self) -> None:
        event = {"breadcrumbs": {"values": [{"message": f"opening {URL}"}]}}
        assert SECRET not in str(scrub_event(event))

    def test_extra(self) -> None:
        """The hole. `extra` is where a developer puts context by hand, which is exactly
        where a connection string ends up."""
        event = {"extra": {"database_url": URL, "note": "retrying"}}
        cleaned = scrub_event(event)
        assert SECRET not in str(cleaned)
        assert cleaned["extra"]["note"] == "retrying", "scrubbing must not eat context"

    def test_contexts_including_nested(self) -> None:
        """The other hole, and it nests: `contexts` is a dict of dicts by design."""
        event = {"contexts": {"connection": {"dsn": URL, "driver": "asyncpg"}}}
        cleaned = scrub_event(event)
        assert SECRET not in str(cleaned)
        assert cleaned["contexts"]["connection"]["driver"] == "asyncpg"

    def test_the_host_survives_scrubbing(self) -> None:
        """A redaction that eats the host tells an operator nothing about what failed."""
        cleaned = scrub_event({"extra": {"database_url": URL}})
        assert "db.internal" in str(cleaned)

    def test_a_non_dict_shape_does_not_raise(self) -> None:
        """`before_send` runs on the error path. Raising there loses the event it was
        called to clean, and the crash that produced it."""
        for shape in ({"extra": "not a dict"}, {"contexts": None}, {}):
            assert scrub_event(dict(shape)) is not None


class TestTheReleaseNamesACommit:
    """A Sentry release is only useful if the SDK's `release` matches the release the
    commits were attached to. When they drift, issues attach to a release with no
    commits and suspect-commit attribution silently does nothing — which reads as
    "Sentry is not very good" rather than as a wiring bug."""

    def test_release_is_taken_from_the_platform(self) -> None:
        with patch.dict(os.environ, {"HEROKU_SLUG_COMMIT": "abc123def"}, clear=False):
            with patch("sentry_sdk.init") as fake_init:
                with patch("app.core.sentry.settings") as fake_settings:
                    fake_settings.sentry_dsn = "https://k@o1.ingest.sentry.io/1"
                    fake_settings.sentry_environment = "production"
                    fake_settings.environment = "production"
                    fake_settings.sentry_traces_sample_rate = 0.0
                    fake_settings.sentry_profiles_sample_rate = 0.0
                    init_sentry()
        assert fake_init.call_args.kwargs["release"] == "abc123def"

    def test_an_empty_slug_commit_falls_through_to_the_baked_release(self) -> None:
        """The container stack's actual behaviour, and the reason the fallback exists.

        `HEROKU_SLUG_COMMIT` is populated only for slug (buildpack) deploys. On the
        container stack the variable is present and **empty** — measured on this app at
        release v271. `os.getenv` returns `""` there, not `None`, so an `is None` check
        would have accepted it and produced a blank release: issues attaching to a
        release with no commits, and attribution silently doing nothing.
        """
        env = {"HEROKU_SLUG_COMMIT": "", "RELEASE": "bakedsha123"}
        with patch.dict(os.environ, env, clear=True):
            with patch("sentry_sdk.init") as fake_init:
                with patch("app.core.sentry.settings") as fake_settings:
                    fake_settings.sentry_dsn = "https://k@o1.ingest.sentry.io/1"
                    fake_settings.sentry_environment = "production"
                    fake_settings.environment = "production"
                    fake_settings.sentry_traces_sample_rate = 0.0
                    fake_settings.sentry_profiles_sample_rate = 0.0
                    init_sentry()
        assert fake_init.call_args.kwargs["release"] == "bakedsha123"

    def test_no_platform_variable_means_no_release_rather_than_a_wrong_one(self) -> None:
        """`None` leaves the release unset. Inventing one — a version string, a
        timestamp — produces a release nothing ever attached commits to, which is worse
        than none: it looks configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sentry_sdk.init") as fake_init:
                with patch("app.core.sentry.settings") as fake_settings:
                    fake_settings.sentry_dsn = "https://k@o1.ingest.sentry.io/1"
                    fake_settings.sentry_environment = ""
                    fake_settings.environment = "development"
                    fake_settings.sentry_traces_sample_rate = 0.0
                    fake_settings.sentry_profiles_sample_rate = 0.0
                    init_sentry()
        assert fake_init.call_args.kwargs["release"] is None


class TestInitWiresBothLayers:
    def test_both_layers_reach_sentry_init(self) -> None:
        with patch("sentry_sdk.init") as fake_init:
            with patch("app.core.sentry.settings") as fake_settings:
                fake_settings.sentry_dsn = "https://k@o1.ingest.sentry.io/1"
                fake_settings.sentry_environment = "production"
                fake_settings.environment = "production"
                fake_settings.sentry_traces_sample_rate = 0.0
                fake_settings.sentry_profiles_sample_rate = 0.0
                init_sentry()
        kwargs = fake_init.call_args.kwargs
        assert kwargs["before_send"] is scrub_event, "layer 2"
        assert isinstance(kwargs["event_scrubber"], EventScrubber), "layer 1"
        assert kwargs["send_default_pii"] is False
        assert kwargs["include_local_variables"] is False
