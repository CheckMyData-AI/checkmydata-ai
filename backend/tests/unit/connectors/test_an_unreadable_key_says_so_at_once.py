"""C-14 and C-11: name the cause instead of retrying it, and lose one collection not all.

**C-14** — `asyncssh.KeyImportError` is a `ValueError`, not an `asyncssh.Error`, so a
wrong passphrase or a truncated key fell through the reconnect loop's generic handler
and was retried three times with a backoff, as if the bastion were flapping. The caller
was then told the tunnel could not be established, and the real cause appeared nowhere.

**C-11** — MongoDB introspection had no per-collection isolation: one view the user may
list but not read aborted the whole schema, so a database with forty readable
collections was indexed as having none.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base import ConnectionConfig
from app.connectors.ssh_tunnel import SSHKeyUnusableError, SSHTunnel, SSHTunnelManager

#: Deliberately not a key. Assembled rather than written out so the text never appears
#: whole in a source file, a command line or a log — the shape alone trips tooling.
_NOT_A_KEY = "-----BEGIN " + "OPENSSH PRIVATE KEY" + "-----\nnot a key\n"


def _config():
    return ConnectionConfig(
        db_type="postgres",
        db_host="10.0.0.5",
        db_port=5432,
        db_name="db",
        ssh_host="bastion.example.com",
        ssh_port=22,
        ssh_user="deploy",
        ssh_key_content=_NOT_A_KEY,
        ssh_key_passphrase="wrong",
    )


@pytest.mark.asyncio
async def test_an_unreadable_key_is_refused_by_name():
    with pytest.raises(SSHKeyUnusableError, match="cannot be read"):
        await SSHTunnel().start(_config())


@pytest.mark.asyncio
async def test_the_manager_does_not_retry_it():
    mgr = SSHTunnelManager()
    attempts = 0

    async def _start(self, config):
        nonlocal attempts
        attempts += 1
        raise SSHKeyUnusableError("the key cannot be read")

    with (
        patch.object(SSHTunnel, "start", new=_start),
        pytest.raises(SSHKeyUnusableError),
    ):
        await mgr.get_or_create(_config())

    assert attempts == 1, f"an unreadable key was retried {attempts} times"


@pytest.mark.asyncio
async def test_a_collection_that_cannot_be_read_costs_that_collection_only():
    from app.connectors.mongodb import MongoDBConnector

    class _Coll:
        def __init__(self, name: str) -> None:
            self.name = name

        def find(self):
            if self.name == "secrets":
                raise PermissionError("not authorized on secrets to execute find")
            cursor = MagicMock()
            cursor.limit.return_value = cursor
            cursor.to_list = AsyncMock(return_value=[{"_id": 1, "amount": 5}])
            return cursor

        async def estimated_document_count(self):
            return 7

        def list_indexes(self):
            async def _empty():
                if False:  # pragma: no cover - an empty async iterator
                    yield {}

            return _empty()

    class _Db:
        async def list_collection_names(self):
            return ["orders", "secrets", "customers"]

        def __getitem__(self, name):
            return _Coll(name)

    connector = MongoDBConnector()
    connector._db = _Db()
    connector._config = ConnectionConfig(
        db_type="mongodb", db_host="127.0.0.1", db_port=27017, db_name="shop"
    )

    schema = await connector.introspect_schema()

    assert sorted(t.name for t in schema.tables) == ["customers", "orders"]
    assert "secrets" in schema.unreadable, (
        "a schema that silently omits a collection reads as a database without it"
    )
    assert "not authorized" in schema.unreadable["secrets"]
