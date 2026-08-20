"""F-CONN-04 — where a connection is allowed to point.

`db_host`, `ssh_host` and a DSN's host are user-supplied and reach a socket, so an
authenticated user can aim one at the cloud metadata endpoint or at the app's own Redis
and read the connection-test error text as an oracle for what answered.

**The obvious guard is the wrong one here**, and that is the design decision these tests
exist to hold. `validate_repo_url` refuses every non-public address by default, which is
right for a git remote: a public git host is the normal case. A database is the opposite —
most deployments reach theirs at `10.x`, `192.168.x` or `127.0.0.1`. Refusing private
addresses by default would break the product for the majority to protect the minority who
run it multi-tenant, and a guard that breaks the normal case gets turned off, after which
it protects nobody.

So: metadata endpoints refused always, private addresses refused only when the operator
says so.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import settings
from app.connectors.host_guard import HostNotAllowedError, check_connection_host


def _resolving_to(*addresses: str):
    """Patch DNS so a name resolves to exactly *addresses*."""
    infos = [(2, 1, 6, "", (a, 0)) for a in addresses]
    return patch("app.connectors.host_guard.socket.getaddrinfo", return_value=infos)


@pytest.fixture(autouse=True)
def _permissive_default(monkeypatch):
    """The shipped default. Tests that care about the strict mode set it themselves."""
    monkeypatch.setattr(settings, "connection_allow_private_hosts", True)


class TestMetadataIsRefusedOnEveryDeployment:
    """No database has ever lived at 169.254.169.254, and what does live there hands out
    credentials for the whole cloud account. Refusing it costs nobody anything, which is
    why it is not behind a setting."""

    @pytest.mark.parametrize("host", ["169.254.169.254", "169.254.170.2", "fd00:ec2::254"])
    def test_a_metadata_literal_is_refused(self, host):
        with pytest.raises(HostNotAllowedError, match="metadata"):
            check_connection_host(host)

    @pytest.mark.parametrize(
        "host", ["metadata.google.internal", "METADATA.GOOGLE.INTERNAL", "instance-data"]
    )
    def test_a_metadata_name_is_refused_before_dns(self, host):
        """Refused by name as well as by address: a split-horizon resolver can answer
        differently for us than for whoever checked."""
        with _resolving_to("93.184.216.34"):
            with pytest.raises(HostNotAllowedError, match="metadata"):
                check_connection_host(host)

    def test_a_name_resolving_to_metadata_is_refused(self):
        with _resolving_to("169.254.169.254"):
            with pytest.raises(HostNotAllowedError, match="metadata"):
                check_connection_host("db.attacker.test")

    def test_a_trailing_dot_does_not_evade_the_name_check(self):
        with _resolving_to("93.184.216.34"):
            with pytest.raises(HostNotAllowedError, match="metadata"):
                check_connection_host("metadata.google.internal.")

    def test_metadata_is_refused_even_when_private_hosts_are_allowed(self, monkeypatch):
        monkeypatch.setattr(settings, "connection_allow_private_hosts", True)

        with pytest.raises(HostNotAllowedError, match="metadata"):
            check_connection_host("169.254.169.254")


class TestPrivateAddressesAreAllowedByDefault:
    """The product's normal case. If these ever start failing, the guard has become the
    outage it was written to avoid."""

    @pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "192.168.0.10", "172.16.4.5", "::1"])
    def test_a_private_literal_is_accepted(self, host):
        check_connection_host(host)

    def test_a_name_resolving_privately_is_accepted(self):
        with _resolving_to("10.0.0.7"):
            check_connection_host("db.internal")


class TestTheStrictModeIsThereForMultiTenant:
    @pytest.fixture(autouse=True)
    def _strict(self, monkeypatch):
        monkeypatch.setattr(settings, "connection_allow_private_hosts", False)

    @pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "169.254.1.1", "0.0.0.0"])
    def test_internal_literals_are_refused(self, host):
        with pytest.raises(HostNotAllowedError):
            check_connection_host(host)

    def test_a_public_host_is_still_accepted(self):
        with _resolving_to("93.184.216.34"):
            check_connection_host("db.example.com")

    def test_a_name_resolving_to_both_public_and_private_is_refused(self):
        """Every returned address is checked. One public record must not launder the
        private one beside it."""
        with _resolving_to("93.184.216.34", "10.0.0.7"):
            with pytest.raises(HostNotAllowedError, match="10.0.0.7"):
                check_connection_host("db.attacker.test")


class TestFailureModes:
    def test_an_unresolvable_host_is_accepted_by_default(self):
        """Written fail-closed first, and the existing suite caught it within the hour:
        `test_database_connection_still_creates_with_its_defaults` went 422 on
        `db.internal`.

        A database hostname this process cannot resolve *right now* is ordinary — the
        user configures the connection before the VPN is up, the name resolves only from
        inside the network, or only through the SSH tunnel's far side. The connection
        test is where reachability is decided; refusing here makes the guard an outage at
        configuration time, which is the exact failure this design has a section about.
        """
        with patch("app.connectors.host_guard.socket.getaddrinfo", side_effect=OSError("nxdomain")):
            check_connection_host("db.internal")

    def test_a_resolver_returning_nothing_is_also_accepted_by_default(self):
        with patch("app.connectors.host_guard.socket.getaddrinfo", return_value=[]):
            check_connection_host("db.internal")

    def test_an_unresolvable_host_is_refused_in_strict_mode(self, monkeypatch):
        """The calculus flips where the operator asked for public hosts only: "I could
        not check" is not "public", and failing open there would let a caller choose
        whether the guard runs by choosing a name that does not resolve once."""
        monkeypatch.setattr(settings, "connection_allow_private_hosts", False)

        with patch("app.connectors.host_guard.socket.getaddrinfo", side_effect=OSError("nxdomain")):
            with pytest.raises(HostNotAllowedError, match="could not be resolved"):
                check_connection_host("db.internal")

    def test_a_metadata_name_is_still_refused_when_dns_fails(self):
        """The name check runs before DNS, so an unresolvable metadata name is refused in
        both modes — that rule never depended on the resolver."""
        with patch("app.connectors.host_guard.socket.getaddrinfo", side_effect=OSError("nxdomain")):
            with pytest.raises(HostNotAllowedError, match="metadata"):
                check_connection_host("metadata.google.internal")

    @pytest.mark.parametrize("host", [None, "", "   "])
    def test_a_blank_host_is_not_this_function_s_business(self, host):
        """An MCP or analytics connection has no host. Whether one is *required* is the
        model validators' question, and answering it here would produce two error
        messages for one condition."""
        check_connection_host(host)

    def test_the_field_name_reaches_the_message(self):
        """The same guard runs on db_host and ssh_host; a message that does not say which
        sends the user to the wrong field."""
        with pytest.raises(HostNotAllowedError, match="ssh_host"):
            check_connection_host("169.254.169.254", field="ssh_host")

    def test_a_literal_address_costs_no_dns_lookup(self):
        with patch("app.connectors.host_guard.socket.getaddrinfo") as resolver:
            check_connection_host("93.184.216.34")

        resolver.assert_not_called()
