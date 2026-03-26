"""Transactional email service powered by Resend."""

import asyncio
import logging

import resend

from app.config import settings

logger = logging.getLogger(__name__)

_BRAND_COLOR = "#2563eb"
_BG_COLOR = "#f8fafc"


_FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,"
    "'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)
_CARD_STYLE = (
    "background:#ffffff;border-radius:8px;"
    "overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)"
)
_FOOTER_STYLE = (
    "padding:16px 32px;border-top:1px solid #e2e8f0;"
    "color:#94a3b8;font-size:12px;text-align:center"
)


def _base_html(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport"'
        ' content="width=device-width,initial-scale=1">'
        f"<title>{title}</title>"
        "</head>"
        f'<body style="margin:0;padding:0;'
        f"background:{_BG_COLOR};"
        f'font-family:{_FONT_STACK}">'
        '<table width="100%" cellpadding="0" cellspacing="0"'
        f' style="background:{_BG_COLOR};padding:40px 0">'
        '<tr><td align="center">'
        '<table width="560" cellpadding="0" cellspacing="0"'
        f' style="{_CARD_STYLE}">'
        f'<tr><td style="background:{_BRAND_COLOR};padding:24px 32px">'
        '<span style="color:#ffffff;font-size:20px;'
        'font-weight:700;letter-spacing:-.3px">'
        "CheckMyData.ai</span>"
        "</td></tr>"
        f'<tr><td style="padding:32px">{body}</td></tr>'
        f'<tr><td style="{_FOOTER_STYLE}">'
        "&copy; CheckMyData.ai &mdash;"
        " Intelligence layer for your databases"
        "</td></tr>"
        "</table>"
        "</td></tr>"
        "</table>"
        "</body></html>"
    )


class EmailService:
    """Fire-and-forget transactional emails via Resend.

    All public methods silently no-op when RESEND_API_KEY is not configured.
    Exceptions are caught and logged so email failures never break the main flow.
    """

    def _is_configured(self) -> bool:
        return bool(settings.resend_api_key)

    async def _send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        idempotency_key: str | None = None,
    ) -> None:
        if not self._is_configured():
            return
        resend.api_key = settings.resend_api_key
        params: resend.Emails.SendParams = {
            "from": settings.resend_from_email,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        try:
            if idempotency_key:
                await asyncio.to_thread(
                    resend.Emails.send, params, {"idempotency_key": idempotency_key}
                )
            else:
                await asyncio.to_thread(resend.Emails.send, params)
            logger.info("Email sent to=%s subject=%r", to, subject)
        except Exception:
            logger.exception("Failed to send email to=%s subject=%r", to, subject)

    # ------------------------------------------------------------------
    # Public email methods
    # ------------------------------------------------------------------

    async def send_welcome_email(self, *, user_id: str, email: str, display_name: str) -> None:
        name = display_name or email.split("@")[0]
        app_link = settings.app_url

        body = f"""\
<h2 style="margin:0 0 16px;color:#1e293b;font-size:22px">Welcome, {name}!</h2>
<p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 16px">
  Your account on <strong>CheckMyData.ai</strong> is ready.
  Connect your databases, ask questions in plain language, and let the system
  learn the context behind your data.
</p>
<p style="margin:0 0 24px">
  <a href="{app_link}" style="display:inline-block;background:{_BRAND_COLOR};color:#fff;
     padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">
    Open CheckMyData
  </a>
</p>
<p style="color:#94a3b8;font-size:13px;margin:0">
  If you did not create this account you can safely ignore this email.
</p>"""

        await self._send(
            to=email,
            subject="Welcome to CheckMyData.ai",
            html=_base_html("Welcome to CheckMyData.ai", body),
            idempotency_key=f"welcome/{user_id}",
        )

    async def send_invite_email(
        self,
        *,
        invite_id: str,
        to_email: str,
        project_name: str,
        inviter_name: str,
        role: str,
    ) -> None:
        app_link = settings.app_url

        body = f"""\
<h2 style="margin:0 0 16px;color:#1e293b;font-size:22px">You&rsquo;re invited!</h2>
<p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 16px">
  <strong>{inviter_name}</strong> invited you to join the project
  <strong>{project_name}</strong> as <strong>{role}</strong> on CheckMyData.ai.
</p>
<p style="margin:0 0 24px">
  <a href="{app_link}" style="display:inline-block;background:{_BRAND_COLOR};color:#fff;
     padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">
    Accept Invite
  </a>
</p>
<p style="color:#94a3b8;font-size:13px;margin:0">
  Sign up or log in with <strong>{to_email}</strong> to accept automatically.
</p>"""

        await self._send(
            to=to_email,
            subject=f"{inviter_name} invited you to {project_name} — CheckMyData.ai",
            html=_base_html("Project Invite", body),
            idempotency_key=f"invite/{invite_id}",
        )

    async def send_invite_accepted_email(
        self,
        *,
        invite_id: str,
        inviter_email: str,
        inviter_name: str,
        accepted_user_email: str,
        accepted_user_name: str,
        project_name: str,
    ) -> None:
        who = accepted_user_name or accepted_user_email
        greeting = inviter_name or inviter_email.split("@")[0]
        app_link = settings.app_url

        body = f"""\
<h2 style="margin:0 0 16px;color:#1e293b;font-size:22px">\
Hi {greeting}, your invite was accepted!</h2>
<p style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 16px">
  <strong>{who}</strong> ({accepted_user_email}) has joined your project
  <strong>{project_name}</strong> on CheckMyData.ai.
</p>
<p style="margin:0 0 24px">
  <a href="{app_link}" style="display:inline-block;background:{_BRAND_COLOR};color:#fff;
     padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">
    Open Project
  </a>
</p>"""

        await self._send(
            to=inviter_email,
            subject=f"{who} joined {project_name} — CheckMyData.ai",
            html=_base_html("Invite Accepted", body),
            idempotency_key=f"invite-accepted/{invite_id}",
        )
