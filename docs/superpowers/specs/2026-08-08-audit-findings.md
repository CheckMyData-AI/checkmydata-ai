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

---

## AUD-4 — `test_heartbeat_ticks_during_long_step` fails under full-suite load · **medium, deploy-path**

Observed 2026-08-08 on a full `tests/unit` run (20m37s): `1 failed, 5404 passed`. The
same test passes in **3.4 s in isolation**, and the branch under test touches only
`api/routes/{connections,projects,repos}.py` — nothing near `pipeline_runner`.

This is the family recorded in m0 as carry-over **C21**, where the same class of flake
failed a CI run, skipped a deploy, and — this is the part worth keeping — **was
dismissed as noise by the operator of that run before being taken seriously**. It was
then fixed in `c5c6460` (WAL + a 30 s busy timeout, verified 0/30 under load). This
observation says that fix is **not sufficient** under a suite heavier than the one it
was validated against.

**Why it ranks above its apparent size:** a flake on the deploy path is not a flaky
test, it is a gate that fails at random. Every future run pays either a re-run or a
wrong decision, and the wrong decision is silent.

**Sharpened by a second run, same day.** The identical suite, *with* the security fix
applied, passed **5405 / 0 failed in 9m52s**. The failing run took **20m37s** — twice as
long, because other pytest invocations were running concurrently on the same machine.
The variable is not the code under test; it is **contention**. That is precisely what a
CI runner does when jobs share a host, which is why this surfaces there and not on a
quiet laptop, and why "passes locally" has never been evidence for it.

**Next step:** reproduce under load (`-n auto` or a parallel writer), then decide
between a real fix and quarantining it off the deploy gate — quarantine being honest
only if it is recorded, not if the test is simply deleted.

## Method note — a masked exit code

The first full-suite run was reported to me as "exit code 0" while the output said
`1 failed`. The command was piped to `tail`, so the exit code belonged to `tail`.
**Never gate a decision on the exit status of a pipeline whose last command is a
pager.** Worth a standing instruction; added to the retro.

---

## AUD-5 / P2 — `sentence-transformers` is absent by design, and the flags lie about it · **operator decision**

`sentence-transformers` appears in **no** dependency list: not in `dependencies`, not in
the `redis` or `dev` optional groups (`backend/pyproject.toml:56-61`). The code is
correct about it — `vector_store.py:46-78` probes with `importlib.util.find_spec` and
degrades, `reranker.py:88` imports lazily — so nothing crashes. What is wrong is the
**documentation and the defaults**:

- `CHROMA_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5` (768-d) is configured and unreachable;
  every embedding in production is `all-MiniLM-L6-v2` (384-d).
- `reranker_enabled` is documented **default on** and is a no-op in production.

**Why this is not a one-line dependency add.** `sentence-transformers` pulls `torch`
(hundreds of MB installed) plus a cross-encoder model loaded into memory. The worker is
already **over quota** — `Error R14`, `mem=843M (163%)` on a Standard-1X (512 MB) dyno,
recorded as K7. Adding a model to that process makes an existing OOM worse, and the slug
grows toward Heroku's limit.

**So this is a resource decision with a price, not an engineering one**, and it splits:

| Option | What it costs | What it buys |
|---|---|---|
| **A — install it, upsize the dynos** | Standard-2X or larger on web *and* worker; slower builds | The retrieval quality the config already claims: 768-d embeddings + a working reranker. Also requires a full re-index, since 384-d and 768-d vectors are not comparable |
| **B — make the defaults honest** | free | `reranker_enabled` defaults **off**, `CHROMA_EMBEDDING_MODEL` documented as requiring the optional extra, `CLAUDE.md` stops claiming a feature that is off in production. Retrieval quality unchanged from today |

**Recommendation: B now, A as a separate funded piece of work.** B costs nothing and
removes a false claim today; A is worth doing but it is a spend decision plus a re-index,
and pretending otherwise by quietly adding the dependency would push an already-OOMing
worker further over its quota.

**Blocked on the operator.** Not decided unilaterally: it costs money.

---

## AUD-6 — Cross-tenant MCP adapter swap under concurrency · **security, high — new P0**

Found by the P6 sweep (per-request state on singleton agents). Same shape as K10, worse
blast radius: this one crosses tenants *while a request is in flight*.

**Why the instance is shared.** `orchestrator.py:367` builds
`MCPSourceAgent(llm_router=self._llm)` in `__init__`, and the orchestrator itself hangs
off the module-level `ConversationalAgent()` in `chat.py:60`. One instance, every
request, `max_concurrent_agent_calls` at a time.

**The mechanism** (`app/agents/mcp_source_agent.py`):

```
:120   prev_adapter = self._adapter
:121   self._adapter = effective_adapter
:123   return await self._run_with_adapter(...)      # <-- awaits
:128   finally:
:129       self._adapter = prev_adapter
```

`_run_with_adapter` does not take the adapter as an argument. It reads it off `self` —
at `:138` (assert), `:62` and `:94` (tool schemas) and, decisively, at **`:214`
`self._adapter.call_tool(tc.name, tc.arguments)`**, the real call against a tenant's
MCP server.

**Interleaving:**

| | Request A | Request B | `self._adapter` |
|---|---|---|---|
| 1 | `prev_A = None`; sets A | | `adapter_A` |
| 2 | awaits inside `_run_with_adapter` | `prev_B = adapter_A`; sets B | `adapter_B` |
| 3 | resumes → `self._adapter.call_tool(...)` | | **`adapter_B`** |

Request A's question is sent to **tenant B's MCP server**, and B's tool results come back
into A's answer. The `finally` then restores in the wrong order — B writes back
`adapter_A`, A writes back `prev_A` — leaving the shared field pointing at whatever the
loser of the race held.

**Fix shape:** thread the adapter as a parameter through `_run_with_adapter`,
`_build_llm_tools`, `_build_tool_description_text` and the `call_tool` site; delete the
save/restore entirely. `self._adapter` stays only as the constructor-time default.

**Rank: above P2.** P2 is a quality regression with a price tag; this is one tenant's
question reaching another tenant's server. Not exploitable at will — it needs concurrent
MCP requests — but it needs no attacker, only traffic.

**Not yet fixed.** Recorded before attempting the change so the finding does not depend
on the fix landing.
