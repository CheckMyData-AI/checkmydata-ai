"""AUD-0819-06: TOFU must not claim a guarantee the host cannot keep.

`config.py` describes `tofu` as "pin the host key on first connect ... and verify
against it thereafter (secure default; a *changed* key is rejected)". On the
primary deploy target the store is `/tmp/checkmydata_known_hosts`, and `/tmp`
does not survive a dyno restart — which production does routinely (AUD-0819-01
records a SIGKILL and restart mid-index). So first use runs again on every boot
and whatever key is offered is accepted, which is the property TOFU exists to
deny. Production, both sides of a restart:

    2026-08-19T00:00:15.995 app[worker.1]: TOFU: pinned host key for
    64.188.10.62 into /tmp/checkmydata_known_hosts

Until the pins live somewhere durable (ADR-0002), the system must at least say
so rather than assert a protection it does not have.
"""

from __future__ import annotations

import logging

from app.connectors.ssh_known_hosts import (
    known_hosts_is_ephemeral,
    reset_durability_warning,
)


class TestEphemeralDetection:
    def test_tmp_is_ephemeral(self):
        assert known_hosts_is_ephemeral("/tmp/checkmydata_known_hosts") is True
        assert known_hosts_is_ephemeral("/var/tmp/kh") is True
        assert known_hosts_is_ephemeral("/private/tmp/kh") is True

    def test_a_real_home_or_data_path_is_not_ephemeral(self):
        assert known_hosts_is_ephemeral("/app/data/known_hosts") is False
        assert known_hosts_is_ephemeral("/home/u/.ssh/known_hosts") is False

    def test_blank_path_is_not_claimed_either_way(self):
        # An unset path is a different failure (nothing to write to); the
        # ephemerality question does not apply and must not be guessed.
        assert known_hosts_is_ephemeral("") is False


class TestDurabilityWarning:
    def setup_method(self):
        reset_durability_warning()

    def test_tofu_over_ephemeral_store_warns_with_the_consequence(self, caplog, monkeypatch):
        from app.connectors import ssh_known_hosts as m

        monkeypatch.setattr(m.settings, "ssh_host_key_policy", "tofu", raising=False)
        monkeypatch.setattr(
            m.settings, "ssh_known_hosts_path", "/tmp/checkmydata_known_hosts", raising=False
        )
        with caplog.at_level(logging.WARNING, logger=m.logger.name):
            m.warn_if_known_hosts_ephemeral()
        text = caplog.text
        assert "ephemeral" in text.lower()
        # The consequence must be named, not merely the condition.
        assert "first use" in text.lower() or "re-pin" in text.lower()
        assert "/tmp/checkmydata_known_hosts" in text

    def test_the_warning_is_emitted_once_not_per_connection(self, caplog, monkeypatch):
        from app.connectors import ssh_known_hosts as m

        monkeypatch.setattr(m.settings, "ssh_host_key_policy", "tofu", raising=False)
        monkeypatch.setattr(m.settings, "ssh_known_hosts_path", "/tmp/kh", raising=False)
        with caplog.at_level(logging.WARNING, logger=m.logger.name):
            for _ in range(5):
                m.warn_if_known_hosts_ephemeral()
        assert caplog.text.lower().count("ephemeral") == 1

    def test_a_durable_store_says_nothing(self, caplog, monkeypatch):
        from app.connectors import ssh_known_hosts as m

        monkeypatch.setattr(m.settings, "ssh_host_key_policy", "tofu", raising=False)
        monkeypatch.setattr(m.settings, "ssh_known_hosts_path", "/app/data/kh", raising=False)
        with caplog.at_level(logging.WARNING, logger=m.logger.name):
            m.warn_if_known_hosts_ephemeral()
        assert "ephemeral" not in caplog.text.lower()

    def test_disabled_policy_does_not_warn_about_durability(self, caplog, monkeypatch):
        """`disabled` already warns loudly on its own; a second warning dilutes it."""
        from app.connectors import ssh_known_hosts as m

        monkeypatch.setattr(m.settings, "ssh_host_key_policy", "disabled", raising=False)
        monkeypatch.setattr(m.settings, "ssh_known_hosts_path", "/tmp/kh", raising=False)
        with caplog.at_level(logging.WARNING, logger=m.logger.name):
            m.warn_if_known_hosts_ephemeral()
        assert "ephemeral" not in caplog.text.lower()
