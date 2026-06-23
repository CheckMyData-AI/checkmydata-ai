# Module 02 — Projects, RBAC & Invites — Audit Report

**Round 1** · 2026-06-23 · Scope: `routes/projects.py`, `routes/invites.py`,
`services/membership_service.py`, `services/invite_service.py`, `services/project_service.py`,
`models/project.py`, `models/project_member.py`, `models/project_invite.py`.

Documented contract (CLAUDE.md "Multi-tenancy & access control"): `Project` is the workspace
boundary; `ProjectMember` carries roles owner/editor/viewer; every project-scoped route must
check membership. RBAC is centralised in `MembershipService.require_role` with
`ROLE_HIERARCHY = {"owner":3,"editor":2,"viewer":1}`. This report verifies the gate is applied
consistently and hunts for privilege-escalation, drift, and data-integrity defects.

Positive notes (verified during the pass): every member/invite-mutating route correctly calls
`require_role(..., "owner")`; `update_member_role`/`remove_member` both refuse to touch an
`owner` row; route bodies use `Literal[...]` role enums; `revoke_invite` is scoped by
`project_id`; the invite email carries no acceptance token (acceptance is in-app via `/pending`
→ `/accept/{id}` with an email-match check) so there is no token-in-email leak.

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-PROJ-01 — 🟠 High — Unverified email registration + auto-accept = invite/access harvesting

**Type:** Security (access control)
**Location:** `services/invite_service.py:208-223` (`auto_accept_for_user`) called from
`routes/auth.py:78` (register) and `:158` (google); registration has **no email verification**
(see Module 01 — `register` creates the account with the typed email and never confirms it).

**Description.** `auto_accept_for_user` accepts **all** pending invites whose `email` matches,
passing `_skip_email_check=True`. For the Google path this is safe (`verify_google_token`
asserts `email_verified`). For the **email/password** path it is not: registration never proves
the registrant owns the address. So if an invite is sent to `victim@corp.com` *before* that
person has an account, an attacker who registers `victim@corp.com` first (no inbox access
needed) is auto-joined to every project that invited that address, at the invited role
(editor/viewer).

**Impact.** Cross-tenant access to private projects (and their connections/credentials/data)
by registering an as-yet-unclaimed invited email. Severity scales with how commonly invites
precede signup.

**Proposed fix.** Require verified email ownership before auto-accepting invites on the
email/password path: either (a) add an email-verification step to registration and only
`auto_accept` after verification, or (b) drop `_skip_email_check` for the password path and
require the user to explicitly accept from `/pending` after a verification click. Track a
`users.email_verified` flag and gate `auto_accept_for_user` on it.

---

## F-PROJ-02 — 🟡 Medium — Owner is tracked in two places that can drift; `require_role` ignores `owner_id`

**Type:** Design / correctness
**Location:** `routes/projects.py:130` (`data["owner_id"]=…`) + `:146`
(`add_member(..., "owner")`); `membership_service.py:30-46` (`require_role` reads only
`ProjectMember`); `:146-158` (`_accessible_filter` reads `owner_id` **or** membership).

**Description.** Project creation writes ownership twice — `Project.owner_id` *and* a
`ProjectMember(role="owner")` row — in two separate commits (`_svc.create` commits, then
`add_member` commits). Read paths disagree on the source of truth: `can_access` /
`list_accessible` honour `owner_id OR membership`, but `require_role` (the gate on nearly every
mutating route) honours **only** the `ProjectMember` row. If the second commit fails, or any
future code sets `owner_id` without a member row, the owner can still *see* the project but gets
`403 "Not a member"` on every editor/owner action — a silent lockout. There is also no
ownership-transfer path, and `_accessible_filter`'s `owner_id` branch means a former owner whose
member row was deleted could retain access.

**Impact.** Latent owner-lockout and inconsistent access decisions between list/can-access and
mutating routes.

**Proposed fix.** Pick one source of truth. Simplest: make `require_role` treat
`Project.owner_id == user_id` as implicit `owner`, OR create the project + owner member row in a
**single transaction** and drop `owner_id` from access logic (keep it only as denormalised
metadata). Add an invariant test: creating a project yields exactly one `owner` member equal to
`owner_id`.

---

## F-PROJ-03 — 🟡 Medium — `accept_invite` commits inside `begin_nested()` on the idempotent path

**Type:** Bug (transaction misuse)
**Location:** `services/invite_service.py:155-189`, specifically the early return at
`:166-168`.

**Description.** The body runs inside `async with db.begin_nested():` (a SAVEPOINT). On the
"already a member" branch it calls `await db.commit()` and `return` **while still inside** the
`begin_nested()` context. Committing the outer transaction inside an open SAVEPOINT block is a
SQLAlchemy footgun: the context manager's `__aexit__` then tries to release/rollback a savepoint
whose transaction is already gone, which can raise (e.g. `ResourceClosedError`/`InvalidRequest`).
The normal new-member branch is fine (it exits the block, then commits at `:178`).

**Impact.** Re-accepting an invite you've already accepted (a legitimate, idempotent action —
and exactly what `auto_accept_for_user` can trigger when an invite was already processed) may
throw a 500 instead of returning the existing membership.

**Proposed fix.** Don't commit inside the nested block. Restructure so the early "already a
member" case returns the existing member *after* the `begin_nested` block closes (or skip the
SAVEPOINT entirely and rely on the outer transaction + the existing `IntegrityError` retry).

---

## F-PROJ-04 — 🟡 Medium — Invites never expire and are auto-accepted indefinitely

**Type:** Security / design
**Location:** `models/project_invite.py` (no `expires_at`); `invite_service.py:191-206`
(`list_pending_for_email` filters only `status=="pending"`).

**Description.** A `ProjectInvite` has no expiry. A pending invite from any time in the past is
still "pending" forever and is auto-accepted on registration (F-PROJ-01) or shown in `/pending`.
There is no TTL, no "expired" status, and no cleanup.

**Impact.** Stale invites become long-lived access grants; compounds the harvesting risk in
F-PROJ-01. Also clutters `/pending` with dead invites.

**Proposed fix.** Add `expires_at` (e.g. now + 14 days) on `create_invite`; treat
`now > expires_at` as expired in `get_pending_invite` / `list_pending_for_email` /
`accept_invite` / `auto_accept_for_user`; add a maintenance sweep to mark expired invites.

---

## F-PROJ-05 — 🟡 Medium — Fire-and-forget `asyncio.create_task` for the sync-now fallback

**Type:** Bug (reliability)
**Location:** `routes/projects.py:560-562` (`sync_now`, ARQ-inactive branch). Matches the
codebase-wide pattern flagged in observation 21208 (fire-and-forget tasks).

**Description.** When ARQ isn't active, the on-demand sync is launched via
`asyncio.create_task(DailyKnowledgeSyncService().run_for_project(...))` and the returned task is
**not retained**. Per the asyncio docs, the event loop keeps only a weak reference to tasks, so a
task with no strong reference can be garbage-collected mid-execution and silently cancelled.
There is also no `.add_done_callback` to log failures, so any exception inside the run is
swallowed. Meanwhile the route returns `202 {"status":"started"}`, telling the user it
succeeded.

**Impact.** In the in-process (non-ARQ / dev / single-dyno) path, a "sync started" can silently
never complete or die partway, with no error surfaced and a run row potentially left `running`
until the reaper times it out.

**Proposed fix.** Retain the task in a module-level set and discard on completion, e.g.:
```python
task = asyncio.create_task(...)
_BG_TASKS.add(task)
task.add_done_callback(lambda t: (_BG_TASKS.discard(t), t.exception() and logger.error(...)))
```
Better: route in-process background work through the existing `app/core/task_queue.py`
abstraction so both ARQ and in-process paths share lifecycle + error handling.

---

## F-PROJ-06 — 🟡 Medium — Membership changes commit, then await email send inline → partial-success 500s

**Type:** Bug (error handling / UX)
**Location:** `routes/invites.py:65-88` (`create_invite`: DB commit in service, then
`await _email_svc.send_invite_email`) and `:188-204` (`accept_invite`: membership committed,
then `send_invite_accepted_email`).

**Description.** The DB mutation is committed inside the service, then the route `await`s an
email send with no `try/except`. If the email provider errors/times out, the route raises 500
even though the invite/membership already persisted. On retry the user hits `409 "Invite
already pending"` / "already a member", a confusing dead-end.

**Impact.** External email-provider flakiness is surfaced as a hard failure of an operation that
actually succeeded; confusing retries.

**Proposed fix.** Send notification emails best-effort: wrap in `try/except` and log, or dispatch
via the task queue, so the API result reflects the DB outcome (which is the source of truth),
not the email side-effect.

---

## F-PROJ-07 — 🟢 Low — Service-layer role methods don't validate role strings

**Type:** Defense-in-depth
**Location:** `membership_service.py:48-73` (`add_member`), `:96-120` (`update_member_role`).

**Description.** Routes constrain roles via `Literal[...]`, but the service methods accept any
string. A future/internal caller passing an unknown role (e.g. `"admin"`) would persist it;
`ROLE_HIERARCHY.get(role, 0)` then returns `0`, silently ranking that member *below* viewer and
locking them out while still appearing as a member. There's no single `is_valid_role` guard.

**Impact.** Low today (routes validate), but a latent foot-gun for any non-route caller.

**Proposed fix.** Validate `role in ROLE_HIERARCHY` in `add_member`/`update_member_role`; raise
`ValueError`/400 otherwise.

---

## F-PROJ-08 — 🟢 Low — `InviteCreate.role` Literal advertises `"owner"` but the route rejects it

**Type:** Inaccuracy (API contract)
**Location:** `routes/invites.py:25` (`Literal["owner","editor","viewer"]`) vs `:63-64`
(`if body.role not in ("editor","viewer"): raise 400`).

**Description.** The request schema says `owner` is a valid role, then the handler rejects it.
The OpenAPI contract is therefore untruthful, and a client that trusts the schema gets a
surprising 400.

**Proposed fix.** Change the model to `Literal["editor","viewer"]` and drop the redundant
runtime check (or document why owner is reserved).

---

## F-PROJ-09 — ⚪ Info — `revoke_invite(_user_id)` ignores the caller id

**Type:** Observation
**Location:** `services/invite_service.py:102-120`.

**Description.** The `_user_id` parameter is unused; authorization depends entirely on the route
gate (`require_role owner`, which is present and correct). The misleading signature could invite
misuse if the service is called from a less-guarded path.

**Proposed fix.** Either drop the param or use it to assert the revoker's relationship for
defense-in-depth.

---

## Test gaps (⚪ Info)

- No test that an unverified email/password registration **cannot** harvest a pending invite
  (F-PROJ-01) — high-value regression test.
- No test for owner_id ↔ owner-member consistency, nor for the owner-lockout drift (F-PROJ-02).
- No test for idempotent re-accept of an already-accepted invite (would currently risk the
  begin_nested commit error, F-PROJ-03).
- No test asserting invite expiry (feature absent, F-PROJ-04).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-PROJ-01 | 🟠 | Unverified registration + auto-accept → invite/access harvesting |
| F-PROJ-02 | 🟡 | Owner tracked in 2 places (owner_id vs member) can drift → owner lockout |
| F-PROJ-03 | 🟡 | `accept_invite` commits inside `begin_nested()` → 500 on idempotent re-accept |
| F-PROJ-04 | 🟡 | Invites never expire; auto-accepted indefinitely |
| F-PROJ-05 | 🟡 | Fire-and-forget `asyncio.create_task` sync-now → silent task death |
| F-PROJ-06 | 🟡 | Commit-then-await-email → partial-success 500s + confusing 409 retries |
| F-PROJ-07 | 🟢 | Service role methods don't validate role strings |
| F-PROJ-08 | 🟢 | `InviteCreate.role` Literal advertises `owner` but route rejects it |
| F-PROJ-09 | ⚪ | `revoke_invite` ignores `_user_id`; authz only at route |

**Next-round focus:** ownership-transfer flow (absent?), the `GET /api/projects` bulk-role path
(`get_roles_bulk`) for owner rows, project `update` whitelist bypass attempts, and concurrency
on `add_member` upsert (race between check and insert — partially covered by the unique
constraint + IntegrityError retry in `accept_invite` but not in `add_member`).

---

# Round 2 — additional findings (2026-06-24)

**Verified clean:** the project `update` route (`projects.py:249-259`, owner-gated) calls
`_svc.update(**model_dump(exclude_unset=True))`, but the service's `UPDATABLE_FIELDS` whitelist
**excludes `owner_id`** — so ownership can't be hijacked via update even if a client sends
`owner_id` (the create path also overwrites it with the authenticated user, `:129`). The owner
can't be removed (`remove_member` refuses `role=="owner"`), preventing orphaning.

## F-PROJ-10 — 🟡 Medium — No ownership transfer / co-owner: the creator is the sole owner forever

**Type:** Design (business continuity)
**Location:** no transfer path exists (grep: no `transfer`/`change_owner`/`reassign`);
`update_member_role` route caps at `Literal["editor","viewer"]` (`invites.py:40`); `add_member
("owner")` only at project create (`projects.py:146`); `create_invite` rejects `owner`
(`invites.py:63`); `delete_account` deletes owned projects (Module 01).

**Description.** A project has exactly one owner — its creator — and there is **no way** to add a
second owner or transfer ownership: you can't promote a member to owner (route role enum excludes
it), can't invite as owner, and can't reassign `owner_id`. If the owner's account is deleted, the
project (and its connections/data) is destroyed with no succession. For a team-workspace product
this is a single point of failure — a departing owner strands or kills the team's workspace.

**Impact.** No business continuity for shared projects; owner departure = data loss or a locked
workspace.

**Proposed fix.** Add an owner-only "transfer ownership" action (set `owner_id` + swap the
`owner` member row in one transaction) and/or support multiple owners; on `delete_account`,
offer to transfer owned projects that have other members instead of deleting them.

## F-PROJ-11 — 🟢 Low — `add_member` upsert isn't `IntegrityError`-guarded → concurrent add → 500

**Type:** Bug (race)
**Location:** `membership_service.py:48-73` (`add_member`: select-then-add/commit, no try/except),
contrast `accept_invite`'s IntegrityError retry (`invite_service.py:177-189`).

**Description.** Two concurrent `add_member(project, user)` calls both see "no existing row" and
both insert; the unique constraint correctly rejects the second, but `add_member` doesn't catch
`IntegrityError`, so the loser gets a 500 instead of the existing membership.

**Proposed fix.** Wrap the insert in `try/except IntegrityError` → rollback → re-select and return
the existing member (mirror `accept_invite`).

## F-PROJ-12 — 🟢 Low — No self-service "leave project" for members

**Type:** UX / access management
**Location:** member removal only via `DELETE /{project_id}/members/{id}` which requires **owner**
(`invites.py:308`).

**Description.** A member can't remove themselves from a project — only an owner can remove them.
Combined with F-PROJ-10 (owner bottleneck), membership churn is entirely owner-gated.

**Proposed fix.** Allow a member to remove their own membership (any role except the sole owner).

## Round 2 summary

| id | sev | one-line |
|----|-----|----------|
| F-PROJ-10 | 🟡 | No ownership transfer/co-owner → owner departure strands or destroys the workspace |
| F-PROJ-11 | 🟢 | `add_member` not IntegrityError-guarded → concurrent add returns 500 |
| F-PROJ-12 | 🟢 | No self-service "leave project" for members |

**Round 3 focus:** `get_roles_bulk` behaviour for an owner whose member row drifted (F-PROJ-02
symptom in `GET /api/projects`); invite-acceptance email mismatch edge cases; project-member
pagination caps on large teams.
