# Spec — Release R3: Cross-tenant isolation & IDOR

**Date:** 2026-06-24 · **Source:** `docs/qa-audit/issues.md` §8 R3
**Bugs:** F-RULE-01 (🟠), F-SSH-08 (🟠), F-RULE-05, F-DG-07, F-DG-09, F-GRAPH-01, F-LEARN-07, F-SSH-06
**Branch:** `fix/security-audit-2026-06-24`

## Theme
"Resource loaded/mutated by a bare id (or shared cache key) without tenant scoping." Each fix
re-scopes the operation to the caller's project/owner. Independent files → parallel.

## Locked contracts

### C1 — F-RULE-01: global-rule create/update/delete require admin (`routes/rules.py`)
- `create_rule` (~line 69): when `body.project_id` is falsy (global), require admin —
  `if not settings.is_admin_email(user.get("email")): raise HTTPException(403, "Admin required to manage global rules")`.
- `update_rule` (~122) and `delete_rule`: when `rule.project_id` is None, same admin check (replace
  the `is_default`-only guard with: globals require admin; default rules still blocked).
- Import `settings` from `app.config`. Keep existing project-scoped `require_role(editor)`.

### C2 — F-RULE-05: agent `manage_rules` scoped to its project (`agents/tool_dispatcher.py`)
In `_handle_manage_rules`, for `update` and `delete`: load the rule first
(`rule = await rule_svc.get(session, rule_id)`); if `rule is None` → "not found"; if
`rule.project_id != ctx.project_id` → return "Permission denied: that rule belongs to another
project." (also rejects globals, `project_id=None`). Only then call `rule_svc.update/delete`.

### C3 — F-DG-07/09: `/investigate` verifies resource ownership (`routes/data_investigations.py`)
`start_investigation` currently `require_role(body.project_id, viewer)` then trusts
`connection_id`/`session_id`/`message_id`. Add, after the role check:
- connection: `conn = await _conn_svc.get(db, body.connection_id); if not conn or conn.project_id != body.project_id: raise 404` (mirror `get_investigation` at ~176-177).
- chat session: load the `ChatSession` for `body.session_id`; require it exists and
  `session.project_id == body.project_id` → else 404.
- chat message: the `ChatMessageModel` loaded by `body.message_id` must belong to `body.session_id`
  (`msg.session_id == body.session_id`) → else 404.
Apply the same verification to any sibling endpoint that trusts caller ids (`confirm_investigation_fix`
already checks the connection; add session/message checks if it reads them).

### C4 — F-GRAPH-01: metric delete scoped to project (`routes/data_graph.py` + `services/data_graph_service.py`)
`delete_metric` route (~232) calls `_graph_svc.delete_metric(db, metric_id)` with no project scope.
Change `DataGraphService.delete_metric(db, metric_id, project_id)` to delete
`WHERE id == metric_id AND project_id == project_id` (return False when the metric isn't in that
project). Route passes `project_id`. Same scoping for any `update_metric`/`get_metric` by bare id.

### C5 — F-SSH-08: tunnel cache key includes a credential discriminator (`connectors/ssh_tunnel.py`)
`_key` (~212) is `ssh_host:ssh_port:ssh_user:db_host:db_port` — omits the credential, so two tenants
sharing a bastion user but different keys share a tunnel. Append a discriminator, preferring
`connection_id` else a short SHA-256 of credential material (mirror `connectors/base.py::connector_key`):
```python
disc = f"cid={config.connection_id}" if getattr(config, "connection_id", None) else (
    "cred=" + hashlib.sha256("|".join([config.ssh_key_content or "", config.ssh_key_passphrase or "",
        config.db_user or "", config.db_password or ""]).encode()).hexdigest()[:16])
return f"{config.ssh_host}:{config.ssh_port}:{config.ssh_user}:{config.db_host}:{config.db_port}:{disc}"
```
Import `hashlib`. Never put the raw secret in the key.

### C6 — F-SSH-06: SSH-key lookups strictly owner-scoped (`services/ssh_key_service.py`)
`get`/`list_all` union `SshKey.user_id.is_(None)` into a user's view (~71, ~83), so a NULL-owner key
leaks to every tenant. Drop the `| (SshKey.user_id.is_(None))` clause so a user only sees/uses keys
where `user_id == <their id>`. (Investigate `create` call-sites first: routes always pass the real
`user_id`, so no orphaning in practice. If a legitimate system-key path exists, keep it behind an
explicit non-user-facing accessor; do NOT widen the user path.)

### C7 — F-LEARN-07: cross-connection/global patterns stay within tenant (`services/agent_learning_service.py`)
`get_global_patterns` / `_get_cross_connection_learnings` (gated by `cross_connection_learnings_enabled`,
default off) aggregate patterns across **all** connections — i.e. across tenants. Scope the query to
connections owned by the **same project's owner** (or same project set the caller can access).
Concretely: thread the caller's `project_id`/`user_id` and join to `Connection`→`Project` so only
patterns from connections under projects owned by the same user are promoted. When the owner can't be
resolved, return nothing (fail closed). Keep the feature flag behavior.

## Test plan (TDD per task)
- rules: non-admin global create/update/delete → 403; admin → ok; project create still works.
- manage_rules: agent update/delete of a rule in another project / a global rule → "Permission denied".
- investigate: mismatched connection/session/message ids (belonging to another project/session) → 404.
- graph: deleting a metric_id that belongs to another project → not deleted / 404.
- ssh_tunnel: two configs same host/user, different `ssh_key_content` → different `_key`.
- ssh_key: a NULL-owner key is not returned to a user via `get`/`list_all`.
- learnings: a cross-connection promotion test asserts patterns from another owner's connection are excluded.

## DOC
`CLAUDE.md` "Multi-tenancy & access control": one line that resource mutations are project-scoped and
global rules / tunnels / SSH keys are owner-scoped (no bare-id cross-tenant access).

## Parallelization (disjoint files)
T1 `routes/rules.py` · T2 `agents/tool_dispatcher.py` · T3 `routes/data_investigations.py` ·
T4 `routes/data_graph.py`+`services/data_graph_service.py` · T5 `connectors/ssh_tunnel.py` ·
T6 `services/ssh_key_service.py` · T7 `services/agent_learning_service.py`. All independent → 7
parallel subagents; integration = scoped tests + ruff/mypy + atomic commit.
