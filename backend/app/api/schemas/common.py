"""Common Pydantic response models used across the API surface (T26).

Historically, many endpoints returned plain ``dict`` objects without a
``response_model``, which made the OpenAPI schema sparse and allowed the
shape of responses to drift. These canonical models are the recommended
vocabulary for success / mutation / accept-style responses.

Guidelines:
- Use :class:`OkResponse` for idempotent success acks that carry no extra
  data beyond ``{"ok": true}``.
- Use :class:`OkWithIdResponse` when the response includes the ID of the
  mutated resource.
- Use :class:`AckWithCountResponse` for bulk delete / clear ops that
  report the number of affected rows.
- For anything richer, define a domain-specific ``BaseModel`` inside the
  relevant router (keep response shapes close to their endpoint).
"""

from __future__ import annotations

from pydantic import BaseModel


class OkResponse(BaseModel):
    """Canonical ``{"ok": true}`` ack for mutation endpoints."""

    ok: bool = True


class OkWithIdResponse(OkResponse):
    """``{"ok": true, "id": "..."}`` ack for create/update endpoints."""

    id: str


class AckWithCountResponse(OkResponse):
    """``{"ok": true, "deleted": 5}`` ack for clear/bulk operations."""

    deleted: int = 0
