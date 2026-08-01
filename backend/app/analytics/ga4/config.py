"""GA4 connection settings — knobs and secret, deliberately kept apart.

Two types, and the split between them is the point:

* :class:`GA4Config` — the **knobs**. Which properties to collect, how far back,
  which events to track, which currency to report in. Stored in the clear in
  ``Connection.source_config_json``, safe to log, safe to show in the UI.
* :class:`GA4Credentials` — the **secret**. The service-account JSON, which lives
  Fernet-encrypted on a ``VendorCredential`` row and is handed to this module
  already decrypted by the caller. It never reaches a log line, a repr, or a
  response model: ``__repr__`` is overridden precisely because a dataclass default
  would print the private key the first time anything logged an adapter.

Neither type reads a database and neither performs I/O, so both are cheap to build
in a test and impossible to accidentally point at production.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.analytics.errors import AnalyticsAuthError, AnalyticsError
from app.connectors.base import ConnectionConfig

#: ``ConnectionConfig.extra`` key holding the parsed ``source_config_json`` dict.
SOURCE_CONFIG_KEY = "source_config"

#: ``ConnectionConfig.extra`` key holding the **decrypted** service-account JSON
#: text, put there by the caller that resolved the ``VendorCredential``.
CREDENTIAL_SECRET_KEY = "vendor_credential_secret"

#: Read-only GA4 Data API scope. Read-only by construction, per vision §7 #1.
GA4_SCOPES = ("https://www.googleapis.com/auth/analytics.readonly",)

#: Backfill window used when the connection does not pin one (spec §4).
DEFAULT_BACKFILL_DAYS = 30

#: Service-account JSON keys without which authentication cannot possibly work.
_REQUIRED_SA_FIELDS = ("client_email", "private_key", "token_uri")


def _normalise_property_id(raw: Any) -> str:
    """Return the bare numeric property id.

    Users paste both ``294380179`` and ``properties/294380179`` (the form the API
    docs and the GA4 UI show). Normalising here means every downstream comparison —
    fact-table ``property_id``, journal keys, request paths — sees one spelling.
    """
    text = str(raw).strip()
    if text.startswith("properties/"):
        text = text[len("properties/") :]
    return text.strip()


@dataclass(frozen=True)
class GA4Config:
    """Non-secret GA4 collection knobs.

    Attributes:
        property_ids: Bare numeric GA4 property ids, at least one.
        backfill_days: How many days back a fresh connection collects.
        event_names: Events the ``events`` report is restricted to. Empty means
            "every event", which on a busy property is a lot of rows — the UI
            nudges users to name the ones they care about.
        currency_code: ISO-4217 code the vendor converts revenue into. ``None``
            leaves the property's own currency in place.
    """

    property_ids: tuple[str, ...]
    backfill_days: int = DEFAULT_BACKFILL_DAYS
    event_names: tuple[str, ...] = ()
    currency_code: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> GA4Config:
        """Build from a decoded ``source_config_json`` mapping.

        Raises:
            AnalyticsError: no usable property id, or a non-positive backfill —
                both are misconfigurations that must fail loudly at connect time
                rather than silently collecting nothing.
        """
        data: Mapping[str, Any] = raw or {}

        raw_ids = data.get("property_ids") or []
        if isinstance(raw_ids, (str, bytes)):
            raw_ids = [raw_ids]
        property_ids = tuple(
            pid for pid in (_normalise_property_id(item) for item in raw_ids) if pid
        )
        if not property_ids:
            raise AnalyticsError(
                "GA4 connection is missing property_ids — add at least one GA4 property id"
            )

        raw_backfill: Any = data.get("backfill_days")
        try:
            # ``or`` would swallow an explicit 0 into the default; only a genuinely
            # absent/blank value falls back.
            backfill_days = (
                DEFAULT_BACKFILL_DAYS if raw_backfill in (None, "") else int(raw_backfill)
            )
        except (TypeError, ValueError) as exc:
            raise AnalyticsError(f"GA4 backfill_days is not a number: {raw_backfill!r}") from exc
        if backfill_days <= 0:
            raise AnalyticsError(f"GA4 backfill_days must be positive, got {backfill_days}")

        raw_events = data.get("event_names") or []
        if isinstance(raw_events, (str, bytes)):
            raw_events = [raw_events]
        event_names = tuple(str(name).strip() for name in raw_events if str(name).strip())

        currency = data.get("currency_code")
        currency_code = str(currency).strip().upper() if currency else None

        return cls(
            property_ids=property_ids,
            backfill_days=backfill_days,
            event_names=event_names,
            currency_code=currency_code,
        )

    @classmethod
    def from_connection_config(cls, config: ConnectionConfig) -> GA4Config:
        """Build from a :class:`ConnectionConfig`.

        Accepts the knobs either nested under ``extra["source_config"]`` (how the
        connection service passes a decoded ``source_config_json``) or flat in
        ``extra`` (how ad-hoc callers and tests build one). Nested wins when both
        are present.
        """
        extra = config.extra or {}
        nested = extra.get(SOURCE_CONFIG_KEY)
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except json.JSONDecodeError as exc:
                raise AnalyticsError(f"GA4 source_config is not valid JSON: {exc}") from exc
        if isinstance(nested, Mapping):
            return cls.from_mapping(nested)
        return cls.from_mapping(extra)


@dataclass(frozen=True)
class GA4Credentials:
    """A parsed GA4 service account. **Holds secret material.**

    ``info`` is the full service-account mapping, including ``private_key``. The
    repr is overridden so the key cannot leak through a log line, an exception
    message, or a debugger transcript; ``client_email`` is exposed on purpose
    because it is the non-secret bit the UI shows ("share your property with this
    address").
    """

    info: Mapping[str, Any]

    @property
    def client_email(self) -> str:
        return str(self.info.get("client_email", ""))

    @classmethod
    def from_json(cls, raw: str | bytes | Mapping[str, Any]) -> GA4Credentials:
        """Parse and validate a service-account JSON document.

        Raises:
            AnalyticsAuthError: the document is not JSON, is not an object, or is
                missing a field authentication cannot work without. This is a
                configuration error — the caller must fix the credential, never
                retry it.
        """
        if isinstance(raw, Mapping):
            info: Any = dict(raw)
        else:
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            try:
                info = json.loads(text)
            except (TypeError, ValueError) as exc:
                raise AnalyticsAuthError(
                    f"GA4 service-account credential is not valid JSON: {exc}"
                ) from exc

        if not isinstance(info, dict):
            raise AnalyticsAuthError(
                f"GA4 service-account credential must be a JSON object, got {type(info).__name__}"
            )

        missing = [key for key in _REQUIRED_SA_FIELDS if not info.get(key)]
        if missing:
            raise AnalyticsAuthError(
                "GA4 service-account credential is missing required field(s): " + ", ".join(missing)
            )
        return cls(info=info)

    def build_credentials(self) -> Any:
        """Return google-auth credentials scoped for read-only GA4 access.

        Imported lazily so importing this module (and therefore the whole
        analytics package) does not pull in google-auth.
        """
        from google.oauth2 import service_account

        try:
            creds = service_account.Credentials.from_service_account_info(dict(self.info))
        except (TypeError, ValueError) as exc:
            raise AnalyticsAuthError(f"GA4 service-account credential is unusable: {exc}") from exc
        return creds.with_scopes(list(GA4_SCOPES))

    def __repr__(self) -> str:  # pragma: no cover - trivial, but load-bearing
        return f"GA4Credentials(client_email={self.client_email!r}, secret=<redacted>)"

    __str__ = __repr__
