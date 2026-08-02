"""``ConnectionConfig`` must never render its secrets (H5).

A plain ``@dataclass`` repr is not a cosmetic detail here: Sentry's default
``include_local_variables=True`` attaches ``repr()``-ed frame locals to every
captured exception, so any traceback through a frame holding a
``ConnectionConfig`` would ship the DB password, the SSH private key and — since
the analytics work — the decrypted service-account JSON in ``extra`` straight to
a third party. Sentry's ``before_send`` scrubber never sees
``stacktrace.frames[].vars``, so the repr is the only place this can be stopped.

The model is :class:`app.analytics.ga4.config.GA4Credentials`, which already
redacts for exactly this reason.
"""

from __future__ import annotations

from app.connectors.base import ConnectionConfig

PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----\n"
SERVICE_ACCOUNT_JSON = (
    '{"type": "service_account", "client_email": "sa@x.iam.gserviceaccount.com", '
    f'"private_key": "{PRIVATE_KEY}"}}'
)


def _loaded_config() -> ConnectionConfig:
    """A config carrying every secret this class can hold."""
    return ConnectionConfig(
        db_type="postgres",
        db_host="db.internal",
        db_port=5432,
        db_name="analytics",
        db_user="reader",
        db_password="hunter2-super-secret",
        connection_string="postgresql://reader:hunter2-super-secret@db.internal:5432/analytics",
        ssh_host="bastion.internal",
        ssh_user="deploy",
        ssh_key_content=PRIVATE_KEY,
        ssh_key_passphrase="passphrase-of-doom",
        extra={"vendor_credential_secret": SERVICE_ACCOUNT_JSON},
        connection_id="conn-123",
    )


class TestConnectionConfigRepr:
    def test_db_password_is_not_rendered(self) -> None:
        assert "hunter2-super-secret" not in repr(_loaded_config())

    def test_connection_string_is_not_rendered(self) -> None:
        """The DSN embeds the password, so the whole value is withheld."""
        rendered = repr(_loaded_config())
        assert "postgresql://reader:hunter2-super-secret@db.internal" not in rendered

    def test_ssh_key_material_is_not_rendered(self) -> None:
        rendered = repr(_loaded_config())
        assert "BEGIN PRIVATE KEY" not in rendered
        assert "MIIEvQIBADANBg" not in rendered
        assert "passphrase-of-doom" not in rendered

    def test_extra_is_not_rendered(self) -> None:
        """``extra`` carries the decrypted vendor credential on the analytics path."""
        rendered = repr(_loaded_config())
        assert "service_account" not in rendered
        assert "sa@x.iam.gserviceaccount.com" not in rendered
        assert SERVICE_ACCOUNT_JSON not in rendered

    def test_str_is_redacted_too(self) -> None:
        """``"%s" % config`` in a log line must not be a second leak channel."""
        rendered = str(_loaded_config())
        assert "hunter2-super-secret" not in rendered
        assert "BEGIN PRIVATE KEY" not in rendered
        assert SERVICE_ACCOUNT_JSON not in rendered

    def test_f_string_interpolation_is_redacted(self) -> None:
        config = _loaded_config()
        assert "hunter2-super-secret" not in f"{config}"
        assert "hunter2-super-secret" not in f"{config!r}"

    def test_non_secret_fields_stay_visible_for_debugging(self) -> None:
        rendered = repr(_loaded_config())
        for visible in ("postgres", "db.internal", "5432", "analytics", "reader", "conn-123"):
            assert visible in rendered, f"{visible!r} is not a secret and must stay debuggable"

    def test_secret_presence_is_still_visible(self) -> None:
        """ "Is a password set?" is a real debugging question; the value is not."""
        with_secrets = repr(_loaded_config())
        without = repr(ConnectionConfig(db_type="postgres"))
        assert with_secrets != without
        assert "redacted" in with_secrets.lower()

    def test_extra_keys_are_visible_but_values_are_not(self) -> None:
        """Knowing *which* knobs were passed stays useful; their values may be secret."""
        rendered = repr(
            ConnectionConfig(db_type="ga4", extra={"source_config": {"property_ids": ["1"]}})
        )
        assert "source_config" in rendered
        assert "property_ids" not in rendered

    def test_repr_of_an_empty_config_is_still_informative(self) -> None:
        rendered = repr(ConnectionConfig(db_type="ga4"))
        assert "ConnectionConfig" in rendered
        assert "ga4" in rendered
