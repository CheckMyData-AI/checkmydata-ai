# ADR-0002 — Where pinned SSH host keys live

- **Status:** proposed
- **Date:** 2026-08-19
- **Context finding:** AUD-0819-06 (`docs/audits/2026-08-19-full-stack-audit.md`)

## Context

`ssh_host_key_policy` defaults to `tofu`, and `config.py` described it as a secure
default that rejects a changed host key. The rejection depends on the pin from the
previous connect still being readable. It is not, on the platform this product
actually deploys to:

- `ssh_known_hosts_path` defaults to `/tmp/checkmydata_known_hosts` (`app/config.py`).
- Heroku empties the dyno filesystem on every restart, and restarts are routine —
  AUD-0819-01 records a `SIGKILL` and restart in the middle of an index run.
- Production duly re-pins across a restart:
  `2026-08-19T00:00:15.995 app[worker.1]: TOFU: pinned host key for 64.188.10.62 into /tmp/checkmydata_known_hosts`

So "trust on first use" re-runs first use on every boot and accepts whatever key is
offered — which is the property TOFU exists to deny. The window is small and needs an
active man-in-the-middle to exploit, which is why this is major rather than critical.

Shipped in the same change as this ADR: `warn_if_known_hosts_ephemeral()` says it once
per process, and `config.py` no longer claims a guarantee the host cannot keep. That
removes the false claim. It does not restore the protection.

## Decision

**Deferred, deliberately.** Persisting host keys is a security-relevant, hard-to-reverse
schema decision, and it was found during a 16-item remediation sweep. Improvising the
store inside that sweep would ship an unreviewed trust anchor. It gets its own change.

## Options considered

| Option | Durable | Cost | Verdict |
|---|---|---|---|
| A different filesystem path | **No** — every path on a Heroku dyno is ephemeral | none | Does not solve it |
| Redis (`REDIS_URL`, already present) | **No** — an eviction-policy cache; a pinned key can be evicted, and `maxmemory-policy` is not ours to guarantee | low | Wrong store for a security fact of record |
| Postgres table `ssh_host_keys` | **Yes** — survives restarts and is shared across dynos | migration + load/merge per connect | **Recommended** |
| Operator-managed `SSH_KNOWN_HOSTS` env var holding the pins | Yes | manual, per host | Viable stopgap; documented below |

## Recommended shape, when it is built

- Table `ssh_host_keys(id, host, port, key_type, key_base64, first_seen_at, owner_id)`
  with a UNIQUE constraint on `(host, port, key_type)` so a concurrent first-connect
  race resolves to one winner instead of two competing pins.
- On connect under `tofu`: load this host's rows, materialise a temporary known_hosts
  file, pass it as `known_hosts`. No rows → connect unverified, then insert.
- A *different* key for an existing `(host, port, key_type)` is rejected, and the
  rejection is the point — it must be an error the operator sees, not a re-pin.
- Tenancy: the tunnel cache key already carries a credential discriminator (F-SSH-08,
  closed in R3). A shared host-key table is deliberately global — a host's identity is
  a property of the host, not of the tenant reaching it — but the insert path must not
  let one tenant pin a key that silently governs another's connections without a log.

## Stopgap available today

Set `SSH_KNOWN_HOSTS_PATH` to a mounted durable volume where the platform offers one,
or run `ssh_host_key_policy=strict` against a known_hosts file baked into the image at
build time. Both restore rejection-on-change; neither is zero-touch.

## Consequences

Until this is built, host-key verification on Heroku is worth exactly one dyno
lifetime, the log says so once per process, and `CLAUDE.md` no longer presents `tofu`
as a secure default without that qualification.
