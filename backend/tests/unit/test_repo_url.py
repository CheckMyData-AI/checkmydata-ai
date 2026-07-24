import ipaddress
import socket

import pytest

from app.knowledge.repo_url import GIT_ALLOWED_PROTOCOLS, validate_git_ref, validate_repo_url


@pytest.mark.parametrize(
    "ref",
    ["main", "develop", "feature/new-thing", "release/v1.2.3", "v1.2.3", "a_b.c-d", "  main  "],
)
def test_validate_git_ref_accepts_safe_refs(ref):
    assert validate_git_ref(ref) == ref.strip()


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "   ",
        "-main",  # leading dash -> option injection
        "--upload-pack=evil",
        "feature..main",  # ".." range syntax
        "foo/",  # trailing slash
        "x.lock",  # reserved .lock suffix
        "has space",
        "weird~name",
    ],
)
def test_validate_git_ref_rejects_dangerous_refs(ref):
    with pytest.raises(ValueError):
        validate_git_ref(ref)


# --- Fake DNS ----------------------------------------------------------------
# validate_repo_url DNS-resolves the repo host (FA-004 SSRF guard). Tests must
# never hit the network, so getaddrinfo is faked with a static host -> IP map.
_FAKE_DNS: dict[str, list[str]] = {
    "github.com": ["140.82.112.3"],
    "gitlab.com": ["172.65.251.78"],
    "internal.example.com": ["8.8.8.8"],
    "localhost": ["127.0.0.1", "::1"],
    # Resolves to a public AND a private address — must be rejected (fail closed).
    "dual.example.com": ["140.82.112.3", "192.168.1.1"],
}


def _fake_getaddrinfo(host, port=None, *args, **kwargs):
    try:
        ip = ipaddress.ip_address(str(host))
    except ValueError:
        ip = None
    if ip is not None:  # IP literal: no DNS needed, hand it straight back
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (str(ip), port or 0))]
    name = str(host).lower()
    if name in _FAKE_DNS:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port or 0))
            for addr in _FAKE_DNS[name]
        ]
    raise socket.gaierror(f"name or service not known: {host}")


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/repo.git",
        "http://internal.example.com/acme/repo.git",
        "ssh://git@github.com/acme/repo.git",
        "git@github.com:acme/repo.git",
        "  https://github.com/acme/repo.git  ",  # trimmed
    ],
)
def test_accepts_safe_urls(url):
    assert validate_repo_url(url) == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh -c 'touch /tmp/pwned'",  # git remote-helper RCE
        "ext::sh -c id",
        "fd::17/foo",
        "file:///etc/passwd",
        "/etc/passwd",
        "-oProxyCommand=evil",  # option injection
        "--upload-pack=evil",
        "",
        "   ",
        "git://insecure.example.com/repo.git",  # unauthenticated git daemon — not allowed
        "javascript:alert(1)",
    ],
)
def test_rejects_dangerous_urls(url):
    with pytest.raises(ValueError):
        validate_repo_url(url)


def test_allowed_protocols_excludes_ext_and_file():
    assert "ext" not in GIT_ALLOWED_PROTOCOLS
    assert "file" not in GIT_ALLOWED_PROTOCOLS
    assert "https" in GIT_ALLOWED_PROTOCOLS and "ssh" in GIT_ALLOWED_PROTOCOLS


# --- FA-004: SSRF guard -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/acme/repo.git",
        "https://127.0.0.1/acme/repo.git",
        "https://localhost/acme/repo.git",  # resolves to 127.0.0.1 / ::1
        "http://10.0.0.5/repo.git",  # RFC1918
        "https://172.16.0.9/repo.git",  # RFC1918
        "git@192.168.1.10:acme/repo.git",  # RFC1918, scp syntax
        "https://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "ssh://git@[::1]/repo.git",  # IPv6 loopback
        "https://[fe80::1]/repo.git",  # IPv6 link-local
        "http://dual.example.com/repo.git",  # one resolved IP is private
    ],
)
def test_rejects_internal_hosts(url):
    with pytest.raises(ValueError, match="non-public"):
        validate_repo_url(url)


def test_rejects_unresolvable_host():
    with pytest.raises(ValueError, match="could not be resolved"):
        validate_repo_url("https://no-such-host.invalid/repo.git")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/repo.git",
        "git@gitlab.com:acme/repo.git",
        "https://8.8.8.8/acme/repo.git",  # public IP literal
    ],
)
def test_accepts_public_hosts(url):
    assert validate_repo_url(url) == url


def test_allow_private_hosts_kwarg_bypasses_guard():
    url = "http://192.168.1.10/acme/repo.git"
    assert validate_repo_url(url, allow_private_hosts=True) == url


def test_allow_private_hosts_setting_bypasses_guard(monkeypatch):
    monkeypatch.setattr("app.config.settings.repo_allow_private_hosts", True)
    url = "http://10.0.0.5/acme/repo.git"
    assert validate_repo_url(url) == url


def test_guard_uses_settings_by_default(monkeypatch):
    monkeypatch.setattr("app.config.settings.repo_allow_private_hosts", False)
    with pytest.raises(ValueError, match="non-public"):
        validate_repo_url("http://10.0.0.5/acme/repo.git")
