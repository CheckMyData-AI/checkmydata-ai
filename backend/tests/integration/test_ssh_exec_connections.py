"""Integration tests for SSH exec mode connections."""

import pytest


@pytest.mark.asyncio
class TestSSHExecConnectionCrud:
    async def _create_project(self, auth_client) -> str:
        resp = await auth_client.post("/api/projects", json={"name": "SSH Exec Test"})
        return resp.json()["id"]

    async def test_create_exec_mode_connection(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post("/api/connections", json={
            "project_id": pid,
            "name": "MySQL via SSH Exec",
            "db_type": "mysql",
            "db_host": "127.0.0.1",
            "db_port": 3306,
            "db_name": "testdb",
            "db_user": "admin",
            "db_password": "secret",
            "ssh_host": "10.0.0.1",
            "ssh_port": 22,
            "ssh_user": "deploy",
            "ssh_exec_mode": True,
            "ssh_command_template": 'MYSQL_PWD="{db_password}" mysql -h {db_host} -P {db_port} -u {db_user} {db_name} --batch',
            "ssh_pre_commands": ["source ~/.bashrc", "export PATH=/opt/mysql/bin:$PATH"],
        })
        assert resp.status_code == 200
        conn = resp.json()
        assert conn["ssh_exec_mode"] is True
        assert conn["ssh_command_template"] is not None
        assert "mysql" in conn["ssh_command_template"]
        assert conn["ssh_pre_commands"] is not None

    async def test_create_normal_connection_defaults(self, auth_client):
        """Normal connections default to ssh_exec_mode=False."""
        pid = await self._create_project(auth_client)
        resp = await auth_client.post("/api/connections", json={
            "project_id": pid,
            "name": "Normal PG",
            "db_type": "postgres",
            "db_host": "127.0.0.1",
            "db_port": 5432,
            "db_name": "mydb",
        })
        assert resp.status_code == 200
        conn = resp.json()
        assert conn["ssh_exec_mode"] is False
        assert conn["ssh_command_template"] is None

    async def test_update_to_exec_mode(self, auth_client):
        pid = await self._create_project(auth_client)
        resp = await auth_client.post("/api/connections", json={
            "project_id": pid,
            "name": "Will Switch",
            "db_type": "mysql",
            "db_host": "127.0.0.1",
            "db_port": 3306,
            "db_name": "testdb",
        })
        cid = resp.json()["id"]
        assert resp.json()["ssh_exec_mode"] is False

        resp = await auth_client.patch(f"/api/connections/{cid}", json={
            "ssh_exec_mode": True,
            "ssh_host": "jump.example.com",
            "ssh_user": "deployer",
            "ssh_command_template": "mysql -h {db_host} --batch",
        })
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["ssh_exec_mode"] is True
        assert updated["ssh_command_template"] == "mysql -h {db_host} --batch"

    async def test_ssh_user_in_response(self, auth_client):
        """Verify ssh_user is returned in the connection response (Gap 8 fix)."""
        pid = await self._create_project(auth_client)
        resp = await auth_client.post("/api/connections", json={
            "project_id": pid,
            "name": "With SSH User",
            "db_type": "mysql",
            "db_host": "127.0.0.1",
            "db_port": 3306,
            "db_name": "testdb",
            "ssh_host": "10.0.0.1",
            "ssh_user": "my-ssh-user",
        })
        assert resp.status_code == 200
        conn = resp.json()
        assert conn["ssh_user"] == "my-ssh-user"

    async def test_test_ssh_no_host(self, auth_client):
        """Test SSH endpoint should return error when no SSH host configured."""
        pid = await self._create_project(auth_client)
        resp = await auth_client.post("/api/connections", json={
            "project_id": pid,
            "name": "No SSH",
            "db_type": "postgres",
            "db_host": "127.0.0.1",
            "db_port": 5432,
            "db_name": "testdb",
        })
        cid = resp.json()["id"]

        resp = await auth_client.post(f"/api/connections/{cid}/test-ssh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "No SSH host" in data["error"]

    async def test_test_ssh_not_found(self, auth_client):
        resp = await auth_client.post("/api/connections/nonexistent-id/test-ssh")
        assert resp.status_code == 404
