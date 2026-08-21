"""Validation for ``ssh_pre_commands`` (F-SEC-5).

Pre-commands are user-supplied strings that get joined with ``&&`` and
executed on the SSH host before every query. Without restriction they are a
remote-command-execution surface: any shell metacharacter or arbitrary binary
in a pre-command runs verbatim on the tunnel host.

This module restricts pre-commands to a small allowlist of environment-setup
operations and rejects shell metacharacters outright. Both the API layer
(create/update connection) and the exec layer (defense in depth) call
:func:`validate_pre_commands`.

Allowed forms::

    export NAME=value            # incl. values like /opt/bin:$PATH
    NAME=value                   # bare variable assignment
    source <path> | . <path>     # load an env file
    cd <path>                    # change working directory

Rejected: command substitution (`` ` ``/``$(``), pipes, redirects, chaining
(``;``, ``&``, ``|``), newlines, and anything not matching the allowlist.
"""

from __future__ import annotations

import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)

#: One warning per process when the hatch is open. A warning on every query is the
#: noise that teaches people to ignore warnings; none at all leaves a disabled screen
#: invisible for as long as the setting survives.
_HATCH_WARNED = False

MAX_PRE_COMMANDS = 20
MAX_PRE_COMMAND_LENGTH = 512

# Shell metacharacters that enable injection regardless of the command shape.
_DANGEROUS = re.compile(r"[;&|<>\n\r`]|\$\(")

# Allowlisted command shapes. Values may contain spaces (e.g. quoted PGOPTIONS)
# because the dangerous-character check above already ran.
_ALLOWED = re.compile(
    r"""^\s*(?:
        export\s+[A-Za-z_][A-Za-z0-9_]*=.*          # export NAME=value
        | [A-Za-z_][A-Za-z0-9_]*=.*                 # NAME=value
        | (?:source|\.)\s+[^\s]+\s*                 # source/. path
        | cd\s+[^\s]+\s*                            # cd path
    )$""",
    re.VERBOSE,
)


class PreCommandValidationError(ValueError):
    """Raised when an ssh_pre_command fails the allowlist (F-SEC-5)."""


def validate_pre_commands(commands: list[str] | None) -> list[str]:
    """Validate pre-commands against the allowlist; return them unchanged.

    Raises :class:`PreCommandValidationError` describing the first offending
    command. A no-op only when the list is empty.

    ``SSH_PRE_COMMAND_ALLOWLIST_ENABLED=false`` relaxes **one** thing: the
    command-shape allowlist. The count cap, length cap, non-empty-string check and
    shell-metacharacter screen apply either way (F-SSH-03) — those are not allowlist
    policy, and a hatch that also opens the injection surface is one nobody can
    safely use.
    """
    global _HATCH_WARNED
    if not commands:
        return commands or []

    # F-SSH-03: the hatch used to `return commands` here, which disabled five
    # protections at once — the count cap, the length cap, the non-empty-string
    # check, the metacharacter screen and the shape allowlist. Only the last is
    # allowlist *policy*; the rest are sanity, and an escape hatch for "my bastion
    # needs an unusual command" is not a request for command substitution. A hatch
    # that silently also opens the injection surface is one nobody can safely open,
    # which makes the documented escape route unusable in practice.
    shapes_enforced = settings.ssh_pre_command_allowlist_enabled
    if not shapes_enforced and not _HATCH_WARNED:
        _HATCH_WARNED = True
        logger.warning(
            "SSH_PRE_COMMAND_ALLOWLIST_ENABLED is false: ssh_pre_commands are no longer "
            "restricted to export/source/cd shapes on this deployment. Shell "
            "metacharacters, the %d-command cap and the %d-character limit are still "
            "enforced. Re-enable it once the connection that needed the hatch is fixed.",
            MAX_PRE_COMMANDS,
            MAX_PRE_COMMAND_LENGTH,
        )

    if len(commands) > MAX_PRE_COMMANDS:
        raise PreCommandValidationError(
            f"Too many ssh_pre_commands ({len(commands)} > {MAX_PRE_COMMANDS})"
        )

    for cmd in commands:
        if not isinstance(cmd, str) or not cmd.strip():
            raise PreCommandValidationError("ssh_pre_commands must be non-empty strings")
        if len(cmd) > MAX_PRE_COMMAND_LENGTH:
            raise PreCommandValidationError(
                f"ssh_pre_command exceeds {MAX_PRE_COMMAND_LENGTH} characters"
            )
        if _DANGEROUS.search(cmd):
            raise PreCommandValidationError(
                f"ssh_pre_command contains forbidden shell metacharacters: {cmd!r}"
            )
        # The only check the hatch actually opens.
        if shapes_enforced and not _ALLOWED.match(cmd):
            raise PreCommandValidationError(
                "ssh_pre_command not allowed (only 'export NAME=value', "
                f"'NAME=value', 'source <path>', '. <path>', 'cd <path>'): {cmd!r}"
            )
    return commands
