"""The security sweep the 2026-09-09 audit could not finish, made repeatable.

That audit's cross-cutting gap hunter was killed by an account spend limit, and the report
recorded its ground as **not covered**: headers and CSP, cookie flags, secrets hygiene,
webhook replay, the WS ticket lifecycle, the demo path, and key-rotation edges. Row P0-7 was
"run it".

It was run on 2026-09-11 and found **no new hole** — the ground had been covered by the
earlier hardening passes. Two real gaps exist and were already on the board before this
sweep: `AUTH-05` (one global webhook secret for any project id) and `API-05` (rate limiting
keyed on an address that is the proxy's, not the caller's).

**A sweep that finds nothing is worth exactly what not sweeping is worth, unless it leaves
something behind.** These are the four checks that can be made permanent; the rest of the
pass is recorded in `docs/audits/2026-09-11-security-gap-sweep.md` with its evidence. Each
one here failed against a real defect at some point in this repository's history, which is
why it is a test and not a paragraph.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

ROUTES = pathlib.Path(__file__).parents[1].parent / "app" / "api" / "routes"
APP = pathlib.Path(__file__).parents[1].parent / "app"

#: Handlers that answer without a session, each because something else authenticates them.
#: A new entry here is a decision: say which credential stands in for the session.
PUBLIC_HANDLERS: dict[str, str] = {
    "register": "public by design — creates the account",
    "verify_email": "carries its own single-use token",
    "forgot_password": "public by design — the address is the only input",
    "reset_password": "carries its own single-use token",
    "login": "public by design",
    "google_login": "authenticated by Google's id token",
    "logout": "clears cookies; refusing an unauthenticated logout helps nobody",
    "list_plans": "the public price list the pricing page renders",
    "stripe_webhook": "authenticated by the Stripe signature",
    "chat_websocket": "authenticated by a single-use WS ticket",
    "repo_webhook": "authenticated by the shared webhook secret (AUTH-05 narrows it)",
}

#: Substrings that make a logged value worth a second look.
_SECRETY = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "passphrase",
)

#: Log arguments that NAME a secret without being one — a count, an id, a fingerprint, a
#: redacted form. Each is quoted as it appears, so a new one has to be looked at.
_LOGGED_BUT_NOT_SECRET = {
    "credentials.client_email",
    "token_nonce",
    "token_id",
    "_MAX_TOKENS_PER_DOC",
    "tokens_used",
    "_redact_token(api_key)",
    "credential.fingerprint",
    "credential.id",
    "credential.name",
    "history_tokens_est",
    "usage.get('total_tokens', 0) or usage.get('prompt_tokens', 0)"
    " + usage.get('completion_tokens', 0)",
}


def _handlers() -> list[tuple[str, int, str, str]]:
    """(file, line, name, signature) for every HTTP/WS route handler."""
    out = []
    for path in sorted(ROUTES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if not any(
                d.startswith("router.")
                and any(
                    m in d for m in ("get(", "post(", "put(", "patch(", "delete(", "websocket(")
                )
                for d in decorators
            ):
                continue
            out.append((path.name, node.lineno, node.name, ast.unparse(node.args)))
    return out


def test_every_route_is_authenticated_or_named() -> None:
    """The classic sweep, and the one worth keeping: a handler with no session dependency."""
    unauthenticated = [
        (f, line, name)
        for f, line, name, args in _handlers()
        if "get_current_user" not in args and "require_" not in args
    ]
    unexplained = [(f, line, n) for f, line, n in unauthenticated if n not in PUBLIC_HANDLERS]
    assert not unexplained, (
        "these route handlers take no session and are not in the public allowlist — either "
        f"they need authentication or they need a reason written down: {unexplained}"
    )


def test_the_public_allowlist_has_no_dead_entries() -> None:
    """An allowance for a handler that no longer exists is an allowance nobody reviews."""
    live = {name for _, _, name, _ in _handlers()}
    stale = sorted(set(PUBLIC_HANDLERS) - live)
    assert not stale, f"allowlisted handlers that no longer exist: {stale}"


def test_no_secret_value_reaches_a_log_line() -> None:
    """Measured 2026-09-11: eleven candidates, none of them a secret value.

    The check is on the ARGUMENT, not the message, because the message is a format string
    and the argument is what carries the value.
    """
    suspects = []
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a file that does not parse is CI's problem
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in {"debug", "info", "warning", "error", "exception", "critical"}:
                continue
            root = node.func.value
            if getattr(root, "id", "") not in {"logger", "log", "logging"}:
                continue
            for arg in node.args[1:]:
                text = ast.unparse(arg)
                if text in _LOGGED_BUT_NOT_SECRET:
                    continue
                if "[:8]" in text or "[:12]" in text:  # deliberately truncated identifiers
                    continue
                if any(s in text.lower() for s in _SECRETY):
                    suspects.append(f"{path.name}:{node.lineno}: {text[:70]}")
    assert not suspects, (
        "these pass a value whose name suggests a secret into a log line. If it is not one, "
        f"add it to _LOGGED_BUT_NOT_SECRET with its exact text: {suspects}"
    )


def test_csrf_is_compared_in_constant_time() -> None:
    """A `==` here leaks the token one character at a time to a patient caller."""
    from app.api import deps

    source = inspect.getsource(deps)
    assert "compare_digest" in source, "the CSRF double-submit is compared with =="


def test_a_retired_encryption_key_can_never_write() -> None:
    """The rotation's whole safety rests on old keys being read-only."""
    from app.services import encryption

    source = inspect.getsource(encryption.encrypt)
    assert "primary" in source, "encrypt() does not name the primary key"
    assert "reader" not in source, (
        "encrypt() reaches for the multi-key reader, so a retired key could write new "
        "ciphertext — and the rotation could then never finish"
    )
