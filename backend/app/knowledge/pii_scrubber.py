"""Redact PII / secrets from DB-derived context before it reaches an LLM.

Pure functions, no I/O. Used by the DB-index validator and the code↔DB sync
analyzer (the two places raw tenant sample data would otherwise egress to an
LLM provider). See spec §5.2.
"""

from __future__ import annotations

import json
import re

SENSITIVE_COLUMN_TOKENS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "access_key",
    "credential",
    "ssn",
    "social_security",
    "card_number",
    "card_no",
    "cardno",
    "pan",
    "cvv",
    "cvc",
    "iban",
    "swift",
    "auth",
    "session",
    "cookie",
    "salt",
    "hash",
    "email",
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{1,}\.[A-Za-z0-9_-]{1,}\.[A-Za-z0-9_-]{1,}")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(r"\b\+?\d[\d\s().-]{7,}\d\b")
# long hex / base64-ish secrets (>= 24 chars, no spaces)
_SECRETISH = re.compile(r"\b[A-Za-z0-9+/=_-]{24,}\b")


def is_sensitive_column(column_name: str) -> bool:
    name = (column_name or "").lower()
    return any(tok in name for tok in SENSITIVE_COLUMN_TOKENS)


def redact_value(value: str) -> str:
    if not value:
        return value
    s = str(value)
    s = _JWT.sub("[redacted-jwt]", s)
    s = _EMAIL.sub("[redacted-email]", s)
    s = _CARD.sub("[redacted-card]", s)
    s = _PHONE.sub("[redacted-phone]", s)
    s = _SECRETISH.sub("[redacted-secret]", s)
    return s


def scrub_distinct_values(column_name: str, values: list, *, enabled: bool = True) -> list:
    if not enabled:
        return values
    if is_sensitive_column(column_name):
        return [f"[redacted: {len(values)} values]"]
    return [redact_value(str(v)) for v in values]


def scrub_sample_json(sample_json: str, *, enabled: bool = True) -> str:
    if not enabled or not sample_json:
        return sample_json
    try:
        rows = json.loads(sample_json)
    except (json.JSONDecodeError, TypeError):
        return redact_value(sample_json)
    if not isinstance(rows, list):
        return redact_value(sample_json)
    cleaned: list = []
    for row in rows:
        if isinstance(row, dict):
            cleaned.append(
                {
                    k: (
                        "[redacted]"
                        if is_sensitive_column(str(k))
                        else (redact_value(v) if isinstance(v, str) else v)
                    )
                    for k, v in row.items()
                }
            )
        else:
            cleaned.append(redact_value(row) if isinstance(row, str) else row)
    return json.dumps(cleaned, default=str)


def scrub_row_cells(columns: list[str], rows: list[list], *, enabled: bool = True) -> list[list]:
    if not enabled:
        return rows
    sensitive_idx = {i for i, c in enumerate(columns) if is_sensitive_column(str(c))}
    out: list[list] = []
    for row in rows:
        new_row = []
        for i, cell in enumerate(row):
            if i in sensitive_idx:
                new_row.append("[redacted]")
            elif isinstance(cell, str):
                new_row.append(redact_value(cell))
            else:
                new_row.append(cell)
        out.append(new_row)
    return out
