# Audit — first pass, 2026-08-08

Scope of **this** pass: mechanical defect classes across `backend/app/` (39 711
statements), plus one deep thread on resource ownership. Coverage is stated honestly
below — this is a first pass, not a full audit.

## What came back clean (negative results, recorded so nobody re-runs them)

Each is a command, re-runnable:

| Class | Result | Check |
|---|---|---|
| Bare `except:` | **0** | `grep -rnE "^\s+except:\s*$" app/` |
| f-string / concatenated SQL | **0** | `grep -rnE 'execute\(f"\|text\(f"' app/` |
| Mutable default arguments | **0** | `grep -rnE "def .*=\s*(\[\]\|\{\})" app/` |
| `datetime.utcnow()` (naive, deprecated) | **0** | `grep -rn "datetime.utcnow()" app/` |
| Fire-and-forget `create_task` (GC hazard) | **0** | both hits hold references and `gather`/store them |
| Unauthenticated route modules | **0** | every module under `api/routes/` imports an auth dep |
| Blocking I/O on the async request path | **0** | `time.sleep` / `requests.*` / bare `open()` in `api/`, `agents/`, `services/` |

**That is itself the headline finding: the mechanical layer is in good shape.** The
defects worth hunting here are semantic, which is why the rest of this pass went deep on
one thread instead of wide on many.

## AUD-1 — Cross-tenant SSH private-key use · **security, high**

**The chain is closed, not hypothetical.**

1. `ssh_key_id` is accepted as a plain string on connection create/update
   (`app/api/routes/connections.py:319`, `:418`) and on project create/update
   (`app/api/routes/projects.py:48`, `:93`) with **no check that the caller owns that
   key** — only `max_length`.
2. `SshKeyService.get()` filters by owner **only when `user_id` is truthy**
   (`app/services/ssh_key_service.py:86-92`).
3. `git_agent.py:165` and `knowledge/pipeline_runner.py:214` call
   `get_decrypted(session, project.ssh_key_id)` with **no `user_id`** — documented as a
   "trusted internal lookup", and that trust rests entirely on step 1 being safe. It is not.
4. `connection_service.py:495,615` do pass `user_id`, but the parameter defaults to
   `None` (`:481`, `:579`), so any caller that omits it silently becomes unfiltered.

**Impact:** a tenant who learns another tenant's SSH key id attaches it to their own
connection or project and has the server open a tunnel — or clone a repository — using
someone else's private key. The key is never exposed to the attacker, but its *use* is.

**Where the fix belongs:** validate ownership at **write** time (the pattern already
exists and is done correctly at `app/api/routes/repos.py:114`), and make `user_id`
required rather than defaulted on the internal path so a future caller cannot re-open it.

**Provenance:** inherited from the m0 run as carry-over C13, re-recorded as K4, named
"recommended next" and not taken. This pass confirms it by tracing every call site.

## AUD-2 — 52 `except → pass` blocks, untriaged · **medium**

`grep -rn --include='*.py' -A1 -E "except [A-Za-z]*.*:$" app/ | grep -c "pass$"` → **52**.

Many are legitimate best-effort (telemetry, cleanup). Some are not, and the two classes
are indistinguishable without reading each one. This is a finding about *auditability*:
a swallowed exception with no log line cannot be investigated after the fact, and this
codebase's own incident — a six-minute timeout storm — was only diagnosable because the
spans were persisted.

**Proposed rule:** every `except: pass` either logs at debug with the exception, or
carries a one-line comment saying why silence is correct. Enforceable as a ratchet
(count may shrink, never grow).

## AUD-3 — Per-request state on process-wide singletons, unaudited · **medium**

`chat.py:60` builds `ConversationalAgent()` at module level; one `OrchestratorAgent` and
one `SQLAgent` live beneath it for the process lifetime, serving up to
`max_concurrent_agent_calls` requests concurrently. One instance of this bug was found
and fixed on 2026-08-08 (`SQLAgent._wall_clock_remaining`, carry-over K10) **only because
a change had to cross that boundary**. Nothing has audited the rest.

**Check:** every `self.<attr> = ` inside a request-scoped method on `SQLAgent`,
`OrchestratorAgent`, `VizAgent`, `KnowledgeAgent`, `GitAgent`, `McpSourceAgent`.

## Coverage of this pass — stated, not implied

**Audited:** the seven mechanical classes above (repository-wide), and the ownership
thread end-to-end.

**Not audited:** concurrency beyond the singleton thread · N+1 and query-plan behaviour ·
frontend entirely · migration reversibility · rate-limit and quota edges · the MCP
surface · error paths of the analytics collector · dependency CVEs.

A second pass should take one thread at a time, the way this one took ownership — the
mechanical sweep is cheap and now done, and repeating it adds nothing.
