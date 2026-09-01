"""Cross-tenant isolation for the chat entry points — the product's primary route.

`POST /api/chat/ask`, `POST /api/chat/ask/stream` and the chat WebSocket each checked
membership on the CALLER-SUPPLIED `project_id` and then resolved the connection with
`ConnectionService.get`, which is `select(Connection).where(Connection.id == …)` and carries
no project scope (`app/services/connection_service.py:241-243`). The resolved row then went
straight to `_safe_to_config`, which DECRYPTS the stored credentials.

So an authenticated user could name their own project and someone else's connection, and the
server would open the victim's production database — through the victim's SSH bastion where
one is configured — and answer questions about it in natural language.

It was an omission rather than a design choice: the missing comparison is written out
verbatim in at least six sibling modules (`batch.py:71`, `notes.py:117`, `notes.py:243`,
`schedules.py:118`, `data_investigations.py:99`, `chat_utility.py:456`), and
`test_investigate_tenant_isolation.py` in this directory pins exactly this shape for
`/investigate` — the fix was applied there and not to chat.

Project and connection rows are created through the public API rather than seeded, for the
reason `test_investigate_tenant_isolation.py` documents: the shared in-memory SQLite engine
is not safe to seed users/projects from a second connection mid-test.
"""

import uuid

import pytest

from tests.integration.conftest import auth_headers, register_user


def _email() -> str:
    return f"chat-iso-{uuid.uuid4().hex[:8]}@test.com"


async def _create_project(client, token: str) -> str:
    resp = await client.post(
        "/api/projects",
        json={"name": f"proj-{uuid.uuid4().hex[:6]}"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_connection(client, token: str, project_id: str) -> str:
    resp = await client.post(
        "/api/connections",
        json={
            "project_id": project_id,
            "name": f"conn-{uuid.uuid4().hex[:6]}",
            "db_type": "postgres",
            "db_host": "localhost",
            "db_port": 5432,
            "db_name": "victim",
            "db_user": "victim_user",
            "db_password": "victim-secret-password",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.fixture
async def two_tenants(client):
    """Attacker with their own project, victim with a connection the attacker must not use."""
    victim_token = (await register_user(client, _email()))["token"]
    victim_project = await _create_project(client, victim_token)
    victim_connection = await _create_connection(client, victim_token, victim_project)

    attacker_token = (await register_user(client, _email()))["token"]
    attacker_project = await _create_project(client, attacker_token)

    return {
        "attacker_token": attacker_token,
        "attacker_project": attacker_project,
        "victim_connection": victim_connection,
        "victim_project": victim_project,
    }


class TestAForeignConnectionIsRefused:
    async def test_ask_refuses(self, client, two_tenants) -> None:
        resp = await client.post(
            "/api/chat/ask",
            json={
                "project_id": two_tenants["attacker_project"],
                "connection_id": two_tenants["victim_connection"],
                "message": "list every table, then show me the users table",
            },
            headers=auth_headers(two_tenants["attacker_token"]),
        )
        assert resp.status_code == 404, (
            f"cross-tenant connection accepted with {resp.status_code}: the server resolved "
            f"another tenant's connection and would decrypt its credentials. {resp.text[:200]}"
        )

    async def test_ask_stream_refuses(self, client, two_tenants) -> None:
        resp = await client.post(
            "/api/chat/ask/stream",
            json={
                "project_id": two_tenants["attacker_project"],
                "connection_id": two_tenants["victim_connection"],
                "message": "dump the schema",
            },
            headers=auth_headers(two_tenants["attacker_token"]),
        )
        assert resp.status_code == 404, (
            f"SSE entry accepted a cross-tenant connection with {resp.status_code}. "
            f"{resp.text[:200]}"
        )

    async def test_the_websocket_ticket_cannot_name_a_foreign_connection(
        self, client, two_tenants
    ) -> None:
        """The ticket is minted for whatever connection the caller names, so the refusal has
        to happen here or at the socket — either is fine, both is better."""
        resp = await client.post(
            f"/api/chat/ws-ticket/{two_tenants['attacker_project']}/"
            f"{two_tenants['victim_connection']}",
            headers=auth_headers(two_tenants["attacker_token"]),
        )
        assert resp.status_code in (403, 404), (
            f"a WS ticket was minted for another tenant's connection ({resp.status_code}); "
            f"the socket then opens it with decrypted credentials. {resp.text[:200]}"
        )


class TestTheOwnConnectionStillWorks:
    """The control. A fix that refuses everything passes the tests above and ships an outage."""

    async def test_ask_accepts_a_connection_in_the_same_project(self, client) -> None:
        token = (await register_user(client, _email()))["token"]
        project = await _create_project(client, token)
        connection = await _create_connection(client, token, project)

        resp = await client.post(
            "/api/chat/ask",
            json={
                "project_id": project,
                "connection_id": connection,
                "message": "hello",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code != 404, (
            "the caller's own connection was refused — the scope check is too strict and "
            f"this is an outage, not a fix. {resp.text[:200]}"
        )


class TestTheServiceMakesTheUnscopedLookupHardToReachByAccident:
    def test_a_project_scoped_getter_exists(self) -> None:
        """Three call sites were missing the same comparison, so the durable fix is a getter
        that cannot be called without a project — not a fourth copy of the `if`."""
        from app.services.connection_service import ConnectionService

        assert hasattr(ConnectionService, "get_in_project"), (
            "without a scoped getter the next entry point will forget the check again, "
            "which is how chat came to be the only route missing it"
        )

    def test_the_chat_module_no_longer_resolves_a_connection_unscoped(self) -> None:
        import inspect

        from app.api.routes import chat

        src = inspect.getsource(chat)
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        assert "_conn_svc.get(" not in code, (
            "chat still calls the unscoped getter; every resolution here must carry the "
            "project it was authorised against"
        )
