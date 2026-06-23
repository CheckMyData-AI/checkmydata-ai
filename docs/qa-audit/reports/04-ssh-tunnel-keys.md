# Module 04 — SSH Tunnel & Keys — Audit Report

**Round 1** · 2026-06-23 · Scope: `connectors/ssh_exec.py`, `connectors/exec_templates.py`,
`connectors/ssh_known_hosts.py`, `connectors/ssh_pre_commands.py`, `connectors/ssh_tunnel.py`,
`services/ssh_key_service.py`, `routes/ssh_keys.py`.

Documented contract: CLAUDE.md — `SSH_HOST_KEY_POLICY` defaults to `tofu`, **fail-closes** to
`strict` on unknown values; `SSH_PRE_COMMAND_ALLOWLIST_ENABLED` validates pre-commands; these
are flagged security-sensitive. `vision.md §7`: credentials never exposed. This report hunts for
host-key bypasses, command injection, and credential exposure in exec mode.

**Positive notes (verified — several hypotheses ruled out):**
- The SQL query is piped via stdin and `shlex.quote`d (`ssh_exec.py:100`) — the LLM-authored
  query cannot inject shell.
- `format_template` **does** shell-escape `db_name/db_user/db_host/db_password` for both
  double-quote and bare contexts (`exec_templates.py:170-210`) — so config-field command
  injection is mitigated (my initial hypothesis was wrong).
- SSH private keys are Fernet-encrypted at rest; the API response model (`SshKeyResponse`)
  returns only id/name/fingerprint/key_type — **never** the private key; ownership is enforced
  on get/list/delete; `create` always sets `user_id`.
- Unknown host-key policy **fails closed** to strict (`ssh_known_hosts.py:145-152`); key
  deletion checks projects/connections/repositories before allowing removal.
- Pre-command allowlist rejects shell metacharacters and restricts to env-setup shapes
  (obs 19257/21205).

Severity: 🔴 Critical · 🟠 High · 🟡 Medium · 🟢 Low · ⚪ Info

---

## F-SSH-01 — 🟡 Medium — TOFU host-key verification fails *open* when the known_hosts file isn't writable

**Type:** Security (MITM)
**Location:** `connectors/ssh_known_hosts.py:124-132`.

**Description.** The module's stated principle is "fail towards verification" (F-SEC-4), and an
unknown policy correctly fails closed. But the **`tofu`** branch, when the known_hosts path is
not writable, logs a warning and sets `connect_kwargs["known_hosts"] = None` — i.e. **disables
host-key verification entirely** and connects anyway. On a read-only container FS, a wrong-perms
mount, or a path under a non-writable dir, *every* SSH tunnel/exec connection silently becomes
MITM-able while the configured policy still reads `tofu`.

**Impact.** Silent downgrade to no host-key verification in production-plausible filesystem
conditions — exactly the MITM exposure the module was written to remove.

**Proposed fix.** Fail closed: if `tofu` and the file isn't writable, raise (refuse the
connection) rather than connecting unverified — or fall back to in-memory pinning for the process
lifetime instead of `known_hosts=None`. At minimum, gate the unverified fallback behind an
explicit `disabled` policy so it can never happen implicitly.

---

## F-SSH-02 — 🟡 Medium — ClickHouse exec template leaks the DB password onto the remote process command line

**Type:** Security (credential exposure, §7)
**Location:** `connectors/exec_templates.py:126-154` (clickhouse query/introspect/test):
`--password "$CLICKHOUSE_PASSWORD"`.

**Description.** The templates' own docstring says "Password is passed via environment variable
to avoid process-list exposure", and the Postgres/MySQL templates honour that
(`PGPASSWORD=…`/`MYSQL_PWD=…` env assignments — not in argv). But the **ClickHouse** template,
after exporting `CLICKHOUSE_PASSWORD`, *also* passes `--password "$CLICKHOUSE_PASSWORD"`, which
the remote shell expands into an **argv** for `clickhouse-client`. The plaintext password is then
visible in `ps`, `/proc/<pid>/cmdline`, and process accounting to any other user on the tunnel
host — violating the §7 "credentials never exposed" invariant and the templates' stated design.

**Impact.** DB password disclosure to co-tenants/other users on the remote host for ClickHouse
exec-mode connections.

**Proposed fix.** Don't pass `--password` on the command line. Modern `clickhouse-client` reads
`CLICKHOUSE_PASSWORD` from the environment; rely on the already-exported env var, or use a
client config file (`--config-file`) with `0600` perms. If a flag is unavoidable, write the
secret to a temp file and use `--password-file`-style indirection.

---

## F-SSH-03 — 🟢 Low — Pre-command allowlist has a global kill-switch that re-enables arbitrary RCE

**Type:** Security foot-gun
**Location:** `connectors/ssh_pre_commands.py:62-63`
(`if not settings.ssh_pre_command_allowlist_enabled: return commands`).

**Description.** When `SSH_PRE_COMMAND_ALLOWLIST_ENABLED=false`, *all* validation is skipped and
pre-commands (joined with `&&` and prefixed to every exec command, `ssh_exec.py:80-91`) become
arbitrary remote command execution on the tunnel host. The allowlist is the whole control; a
single env flag removes it globally.

**Impact.** A misconfiguration (or an operator following a "it's not working, disable the
allowlist" instinct) converts a stored connection's pre-commands into persistent RCE.

**Proposed fix.** Confirm the default is `true` (and document it loudly). Consider removing the
global off-switch entirely, or restrict the unsafe mode to self-hosted single-tenant builds with
a separate, explicitly-named flag.

---

## F-SSH-04 — 🟢 Low — `db_port` is the one template variable that isn't shell-escaped

**Type:** Defense-in-depth
**Location:** `connectors/exec_templates.py:198` (`_escape_keys` omits `db_port`), `:200-203`.

**Description.** `_escape_keys = {"db_name","db_user","db_host","db_password"}` — `db_port` is
substituted raw. It's currently safe only because `ConnectionConfig.db_port` is typed `int` and
rendered via `str()`. If any path ever stores `db_port` as a free-form string (custom connection
parsing, import), an unescaped value reaches the shell.

**Proposed fix.** Add `db_port` to `_escape_keys`, or assert `db_port` is numeric before
formatting.

---

## F-SSH-05 — 🟢 Low — TOFU check-then-pin is not atomic; concurrent first connections race

**Type:** Bug (race) / inherent TOFU caveat
**Location:** `connectors/ssh_known_hosts.py:134-143`.

**Description.** First-use is `_host_is_pinned()` → connect unverified → `_pin_host_key()` with no
lock. Concurrent first connections to the same host can each see "not pinned" and append the key,
producing duplicate known_hosts lines (and, under a key-mismatch edge, racing pins). Separately,
the first connection is by definition unverified (inherent TOFU MITM window) — acceptable but
worth documenting as a residual risk for high-value hosts (prefer `strict` there).

**Proposed fix.** Guard the check-then-pin with an async lock keyed by host; de-dupe before
appending. Document the first-use window and recommend `strict` for sensitive hosts.

---

## F-SSH-06 — 🟢 Low (latent) — `SshKeyService` treats `user_id IS NULL` keys as shared across all tenants

**Type:** Multi-tenancy (latent)
**Location:** `services/ssh_key_service.py:68-85` (`(SshKey.user_id == user_id) | (SshKey.user_id.is_(None))`).

**Description.** `get`/`list_all`/`get_decrypted` return keys owned by the caller **or** any key
with `user_id IS NULL`. No API path creates NULL-owner keys today (`create` always passes
`user_id`), so this is latent — but any globally-owned key introduced via seed/migration/admin
would be readable and **usable** (to open SSH sessions) by every tenant.

**Proposed fix.** Drop the NULL-sharing branch, or gate "system" keys behind an explicit
admin-only concept rather than implicit NULL ownership.

---

## F-SSH-07 — 🟢 Low — Auto-reconnect re-runs the command, double-executing non-idempotent operations

**Type:** Reliability
**Location:** `connectors/ssh_exec.py:159-184`.

**Description.** On `ConnectionLost`/`DisconnectError`, `_run_command` reconnects and re-runs the
same command. For read-only queries this is safe (and intended), but it assumes idempotency; an
introspection/test re-run is merely wasteful, while any future write path would double-apply.

**Proposed fix.** Restrict auto-retry to statements known to be read-only/idempotent, or make it
opt-in per call.

---

## Test gaps (⚪ Info)

- No test for the TOFU **fail-open** path when known_hosts is non-writable (F-SSH-01).
- No test asserting the ClickHouse password does **not** appear in the rendered command argv
  (F-SSH-02).
- No test that `db_port` with a non-numeric value is rejected/escaped (F-SSH-04).
- No concurrency test for TOFU double-pinning (F-SSH-05).

## Summary

| id | sev | one-line |
|----|-----|----------|
| F-SSH-01 | 🟡 | TOFU fails *open* (no host-key check) when known_hosts isn't writable |
| F-SSH-02 | 🟡 | ClickHouse exec leaks DB password onto remote process command line |
| F-SSH-03 | 🟢 | Pre-command allowlist has a global kill-switch → arbitrary RCE |
| F-SSH-04 | 🟢 | `db_port` template var not shell-escaped (relies on int typing) |
| F-SSH-05 | 🟢 | TOFU check-then-pin race; first-use unverified (inherent) |
| F-SSH-06 | 🟢 | `user_id IS NULL` SSH keys are latently cross-tenant |
| F-SSH-07 | 🟢 | Auto-reconnect re-runs command → double-execute risk |

**Next-round focus:** `ssh_tunnel.py` (shared tunnel manager — port reuse across tenants?
tunnel lifecycle/eviction, local bind address `127.0.0.1` vs `0.0.0.0`), and whether
`connection_service` liveness test routes through `connect_with_policy` consistently.
