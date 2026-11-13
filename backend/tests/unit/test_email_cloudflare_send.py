"""How a Cloudflare Email Sending answer becomes a result (Resend retired 2026-11-13).

A send is retried only when nothing can have gone (a 429, a request that never reached
Cloudflare). A 5xx, a malformed answer or a timeout may already have delivered it, so it
is an unknown outcome and the service does not retry it: a retry would be a second email.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.services import email_service as es

PARAMS = {
    "from": "CheckMyData <noreply@mail.checkmydata.ai>",
    "to": ["a@b.com"],
    "subject": "s",
    "html": "<p>x</p>",
}


def _answer(status: int, body: object) -> httpx.Response:
    return httpx.Response(
        status, json=body, request=httpx.Request("POST", "https://api.cloudflare.com")
    )


@pytest.fixture(autouse=True)
def _configured():
    with (
        patch.object(es.settings, "cloudflare_email_api_token", "cf_token"),
        patch.object(es.settings, "cloudflare_email_account_id", "acct1"),
    ):
        yield


def test_success_returns_the_message_id_and_posts_the_account_endpoint():
    with patch(
        "app.services.email_service.httpx.post",
        return_value=_answer(200, {"success": True, "result": {"message_id": "<m1>"}}),
    ) as post:
        assert es._cf_send(PARAMS, {"idempotency_key": "k"}) == {"id": "<m1>"}
    url = post.call_args[0][0]
    body = post.call_args.kwargs["json"]
    assert url.endswith("/accounts/acct1/email/sending/send")
    assert body["from"] == {"address": "noreply@mail.checkmydata.ai", "name": "CheckMyData"}
    assert "idempotency_key" not in body


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (429, {"errors": [{"code": 1, "message": "slow down"}]}, es.EmailNotSentError),
        (
            403,
            {"errors": [{"code": 10203, "message": "email.sending_disabled"}]},
            es.EmailRefusedError,
        ),
        (502, {}, es.EmailOutcomeUnknownError),
        (200, {"success": False, "errors": []}, es.EmailOutcomeUnknownError),
        (200, {"success": True, "result": {}}, es.EmailOutcomeUnknownError),
    ],
)
def test_each_answer_becomes_its_kind(status, body, error):
    with (
        patch("app.services.email_service.httpx.post", return_value=_answer(status, body)),
        pytest.raises(error),
    ):
        es._cf_send(PARAMS)


def test_unreached_is_not_sent_and_a_timeout_is_unknown():
    with (
        patch("app.services.email_service.httpx.post", side_effect=httpx.ConnectError("no route")),
        pytest.raises(es.EmailNotSentError),
    ):
        es._cf_send(PARAMS)
    with (
        patch("app.services.email_service.httpx.post", side_effect=httpx.ReadTimeout("slow")),
        pytest.raises(es.EmailOutcomeUnknownError),
    ):
        es._cf_send(PARAMS)


def test_only_a_send_that_cannot_have_gone_is_retryable():
    assert es._is_retryable(es.EmailNotSentError("x"))
    assert not es._is_retryable(es.EmailOutcomeUnknownError("x"))
    assert not es._is_retryable(es.EmailRefusedError("x"))
