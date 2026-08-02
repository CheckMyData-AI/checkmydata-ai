"""Integration tests for /api/vendor-credentials (spec §5).

The app fixture here builds its **own** FastAPI app that includes the
`vendor_credentials` router directly, rather than importing `app.main`: T7 owns
`main.py` and adds the `include_router` line, so this suite must be green before
that lands.

The load-bearing assertion in this file is the negative one — the plaintext
secret and its ciphertext appear **nowhere** in any serialised response.
"""

from __future__ import annotations

import json
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.project import Project
from app.models.vendor_credential import VendorCredential

GA4_SECRET = json.dumps(
    {
        "type": "service_account",
        "project_id": "demo-project",
        "client_email": "collector@demo-project.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIBVERYSECRET\n-----END PRIVATE KEY-----\n",
    }
)


@pytest_asyncio.fixture()
async def vc_client(engine, db_session: AsyncSession):
    """Client for a minimal app: auth (to mint real tokens) + vendor credentials."""
    from fastapi import FastAPI
    from slowapi.errors import RateLimitExceeded

    from app.api.deps import get_db
    from app.api.routes import auth, vendor_credentials
    from app.core.rate_limit import limiter

    async def _override():
        yield db_session

    test_app = FastAPI()
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, lambda r, e: None)  # type: ignore[arg-type]
    test_app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    test_app.include_router(
        vendor_credentials.router, prefix="/api/vendor-credentials", tags=["vendor-credentials"]
    )
    test_app.dependency_overrides[get_db] = _override

    # Deliberately NOT repointing `app.models.base.async_session_factory` at the
    # test engine (unlike the shared `client` fixture). `audit_log` persists on a
    # background task through that factory; on this StaticPool engine the extra
    # session shares the single DBAPI connection, so its close/rollback discards
    # writes this test has flushed but not yet committed — which silently emptied
    # the connections table and made the FK-RESTRICT case look like a pass.
    # Left alone, audit persistence targets the app engine, fails to find the
    # table and degrades to a warning, exactly as documented in app/core/audit.py.
    limiter.enabled = False

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    test_app.dependency_overrides.clear()
    limiter.enabled = True


async def _register(client: AsyncClient) -> str:
    """Register a fresh user and return their bearer token."""
    resp = await client.post(
        "/api/auth/register",
        json={"email": f"vc-{uuid.uuid4().hex[:8]}@test.com", "password": "testpass123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create(client: AsyncClient, token: str, name: str = "ga4-sa"):
    return await client.post(
        "/api/vendor-credentials",
        headers=_hdr(token),
        json={"name": name, "provider": "ga4", "secret": GA4_SECRET},
    )


async def _ciphertext(db_session: AsyncSession, cred_id: str) -> str:
    row = await db_session.execute(
        select(VendorCredential.secret_encrypted).where(VendorCredential.id == cred_id)
    )
    return row.scalar_one()


async def _count(db_session: AsyncSession) -> int:
    """Total credential rows.

    The integration engine is session-scoped, so other tests' rows are still
    around — "nothing was persisted" is asserted as *unchanged*, not as zero.
    """
    result = await db_session.execute(select(func.count()).select_from(VendorCredential))
    return int(result.scalar_one())


class TestCreateAndList:
    async def test_create_returns_metadata_but_never_the_secret(
        self, vc_client: AsyncClient, db_session: AsyncSession
    ):
        token = await _register(vc_client)
        resp = await _create(vc_client, token)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == "ga4-sa"
        assert body["provider"] == "ga4"
        assert len(body["fingerprint"]) == 16
        assert body["meta"]["client_email"] == "collector@demo-project.iam.gserviceaccount.com"

        ciphertext = await _ciphertext(db_session, body["id"])
        raw = resp.text
        assert GA4_SECRET not in raw
        assert "MIIBVERYSECRET" not in raw  # no fragment of the key either
        assert "private_key" not in raw
        assert ciphertext not in raw
        assert "secret" not in json.dumps(body)

    async def test_list_returns_own_credentials_without_secrets(
        self, vc_client: AsyncClient, db_session: AsyncSession
    ):
        token = await _register(vc_client)
        created = (await _create(vc_client, token)).json()

        resp = await vc_client.get("/api/vendor-credentials", headers=_hdr(token))
        assert resp.status_code == 200
        rows = resp.json()
        assert [r["id"] for r in rows] == [created["id"]]

        ciphertext = await _ciphertext(db_session, created["id"])
        raw = resp.text
        assert GA4_SECRET not in raw
        assert "MIIBVERYSECRET" not in raw
        assert ciphertext not in raw

    async def test_requires_authentication(self, vc_client: AsyncClient):
        assert (await vc_client.get("/api/vendor-credentials")).status_code == 401


class TestValidation:
    async def test_malformed_ga4_json_is_422_and_persists_nothing(
        self, vc_client: AsyncClient, db_session: AsyncSession
    ):
        token = await _register(vc_client)
        before = await _count(db_session)
        resp = await vc_client.post(
            "/api/vendor-credentials",
            headers=_hdr(token),
            json={"name": "broken", "provider": "ga4", "secret": "{not json"},
        )
        assert resp.status_code == 422
        assert "JSON" in resp.json()["detail"]
        assert await _count(db_session) == before
        assert (await vc_client.get("/api/vendor-credentials", headers=_hdr(token))).json() == []

    async def test_ga4_json_missing_client_email_is_422(
        self, vc_client: AsyncClient, db_session: AsyncSession
    ):
        token = await _register(vc_client)
        before = await _count(db_session)
        resp = await vc_client.post(
            "/api/vendor-credentials",
            headers=_hdr(token),
            json={
                "name": "half",
                "provider": "ga4",
                "secret": json.dumps({"private_key": "-----BEGIN PRIVATE KEY-----\nx\n"}),
            },
        )
        assert resp.status_code == 422
        assert "client_email" in resp.json()["detail"]
        assert await _count(db_session) == before

    async def test_unknown_provider_is_422(self, vc_client: AsyncClient, db_session: AsyncSession):
        token = await _register(vc_client)
        before = await _count(db_session)
        resp = await vc_client.post(
            "/api/vendor-credentials",
            headers=_hdr(token),
            json={"name": "x", "provider": "mixpanel", "secret": GA4_SECRET},
        )
        assert resp.status_code == 422
        assert await _count(db_session) == before


class TestTenantIsolation:
    async def test_other_users_credential_is_invisible_and_undeletable(
        self, vc_client: AsyncClient
    ):
        token_a = await _register(vc_client)
        token_b = await _register(vc_client)
        cred_a = (await _create(vc_client, token_a, name="a-cred")).json()

        listing_b = await vc_client.get("/api/vendor-credentials", headers=_hdr(token_b))
        assert listing_b.status_code == 200
        assert cred_a["id"] not in [r["id"] for r in listing_b.json()]

        deleted = await vc_client.delete(
            f"/api/vendor-credentials/{cred_a['id']}", headers=_hdr(token_b)
        )
        assert deleted.status_code == 404

        # …and A's credential is still there.
        listing_a = await vc_client.get("/api/vendor-credentials", headers=_hdr(token_a))
        assert cred_a["id"] in [r["id"] for r in listing_a.json()]


class TestDelete:
    async def test_delete_unreferenced_credential(self, vc_client: AsyncClient):
        token = await _register(vc_client)
        cred = (await _create(vc_client, token)).json()

        resp = await vc_client.delete(f"/api/vendor-credentials/{cred['id']}", headers=_hdr(token))
        assert resp.status_code == 200

        listing = await vc_client.get("/api/vendor-credentials", headers=_hdr(token))
        assert listing.json() == []

    async def test_delete_missing_credential_is_404(self, vc_client: AsyncClient):
        token = await _register(vc_client)
        resp = await vc_client.delete("/api/vendor-credentials/does-not-exist", headers=_hdr(token))
        assert resp.status_code == 404

    async def test_delete_referenced_by_connection_is_409(
        self, vc_client: AsyncClient, db_session: AsyncSession
    ):
        """FK is ON DELETE RESTRICT — the DB refuses, we translate to 409."""
        token = await _register(vc_client)
        me = await vc_client.get("/api/auth/me", headers=_hdr(token))
        owner_id = me.json()["id"]
        cred = (await _create(vc_client, token)).json()

        project_id = str(uuid.uuid4())
        db_session.add(Project(id=project_id, name="analytics-proj", owner_id=owner_id))
        await db_session.flush()
        db_session.add(
            Connection(
                id=str(uuid.uuid4()),
                project_id=project_id,
                name="ga4-conn",
                source_type="ga4",
                vendor_credential_id=cred["id"],
            )
        )
        await db_session.commit()
        # Guard: if the referencing row is not actually there, a 200 below would
        # "pass" a broken FK check for the wrong reason.
        referencing = await db_session.execute(
            select(Connection.id).where(Connection.vendor_credential_id == cred["id"])
        )
        assert referencing.scalars().all(), "seed failed: no connection references the credential"

        resp = await vc_client.delete(f"/api/vendor-credentials/{cred['id']}", headers=_hdr(token))
        assert resp.status_code == 409
        assert "in use" in resp.json()["detail"].lower()

        # The credential survived — no orphaned connection.
        listing = await vc_client.get("/api/vendor-credentials", headers=_hdr(token))
        assert cred["id"] in [r["id"] for r in listing.json()]
