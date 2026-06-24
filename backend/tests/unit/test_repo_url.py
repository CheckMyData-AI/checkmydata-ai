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
