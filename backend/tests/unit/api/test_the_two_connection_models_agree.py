"""C-13: what a PATCH may say is what a POST may say.

`ConnectionUpdate` was looser than `ConnectionCreate` in two ways, and the first is the
one that matters: `db_type` was a free `str`, so a value the create route refuses could
be written by updating an existing row. The caps also disagreed — name 200 vs 255,
`ssh_user` 100 vs 255, `ssh_key_id` 64 vs 255, the command template 2000 vs 2048 — which
is a connection that can be created and then fails to save again unchanged.
"""

from __future__ import annotations

import pytest

from app.api.routes.connections import ConnectionCreate, ConnectionUpdate

#: Fields whose shape is deliberately different, with the reason.
_BY_DESIGN = {
    "project_id": "a PATCH cannot move a connection to another project",
    "source_type": "create defaults it to `database`; a PATCH leaves it alone",
    "ssh_port": "create defaults to 22; a PATCH means 'unchanged' by omission",
    "db_host": "create defaults to 127.0.0.1",
    "db_port": "create defaults to the engine's port",
    "db_name": "create defaults to the empty string",
}


def _cap(model, name: str) -> int | None:
    field = model.model_fields[name]
    for meta in field.metadata:
        if hasattr(meta, "max_length"):
            return meta.max_length
    return None


def test_every_shared_field_has_the_same_cap():
    shared = set(ConnectionCreate.model_fields) & set(ConnectionUpdate.model_fields)
    mismatched = {
        name: (_cap(ConnectionCreate, name), _cap(ConnectionUpdate, name))
        for name in sorted(shared)
        if name not in _BY_DESIGN and _cap(ConnectionCreate, name) != _cap(ConnectionUpdate, name)
    }
    assert mismatched == {}, f"a PATCH would refuse what a POST accepts: {mismatched}"


def test_an_engine_a_post_refuses_cannot_arrive_by_patch():
    with pytest.raises(ValueError):
        ConnectionUpdate(db_type="oracle")

    with pytest.raises(ValueError):
        ConnectionCreate(project_id="p", name="n", db_type="oracle")


def test_the_engines_both_accept_are_the_same_set():
    def engines(model) -> set[str]:
        accepted = set()
        for candidate in ("postgres", "mysql", "mongodb", "clickhouse", "mcp", "sqlite"):
            try:
                model.model_validate(
                    {"project_id": "p", "name": "n", "db_type": candidate, "db_name": "d"}
                )
            except ValueError as exc:
                if "db_type" in str(exc):
                    continue
            accepted.add(candidate)
        return accepted

    assert engines(ConnectionCreate) == engines(ConnectionUpdate)
