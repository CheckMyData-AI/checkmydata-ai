# Retro — checkmydata-ai

What previous runs of the pipeline got wrong **in this project**. Read in full at stage 0;
these bind the run. Hard cap: **ten** standing instructions. Prune before adding.

## Standing instructions

1. **A test that has never run is not a check — whether it skipped, or was simply never
   seen red. And assert on behaviour, not on source text.** Plant the defect it claims
   to catch and watch it fail. *(2026-08-08: a `finalize_trace` test asserted on source
   text; a blanket-overwrite defect preserved the text it looked for and passed green.
   2026-08-12: a worker test would have skipped forever because CI installs only
   `[dev]` and `app/worker.py` imports `arq` from the `redis` extra — check what CI
   actually installs before trusting a green.)*
2. **Before merging, verify the branch contains the docs it owes** — especially
   `docs/ux/scenarios.md`. *(2026-08-08: the branch was green, complete, and had no
   scenario for its own user-facing change; caught one command before the merge. A
   worktree separates documentation from code as thoroughly as it separates code.)*
3. **When a ledger entry names a root cause, re-derive it from the code before
   implementing it.** A deferred entry is a hypothesis written under time pressure.
   *(2026-08-08: K12 said "router signals are not stamped"; the defect was
   `finalize_trace` *erasing* values already written. 2026-08-12: AUD-2 was wrong three
   ways at once — the count, the danger, and the location.)*
4. **Verify against the running application, never against a workflow row or a config
   value.** *(m0 C22: a monitor reported a false success from a stale row. 2026-08-12:
   MCP Host validation was proven by a forged `Host` returning 403 where the correct one
   returns 401 — set is not the same as enforced.)*
5. **Say which claim is unproven.** A clean boot is not proven behaviour. Name the check
   that would prove it and put it in the ledger rather than letting a green stage imply
   more than it measured.
6. **`grep` for a call site is not a survey of call sites.** Follow the value.
   *(2026-08-08: three `classify` sites named, two real, and a fourth `ssh_key_id` write
   site found only after the first sweep declared itself done.)*
7. **Never read an exit code through a pipe.** `pytest … | tail` reports `tail`'s status.
   *(2026-08-08 and twice since: a run with `1 failed` announced as exit code 0.)*
8. **A flake on the deploy path is a gate that fails at random, not noise.** Reproduce it
   under the load that exposed it. *(2026-08-12: CPU contention did not reproduce it —
   concurrent pytest processes did, 1 in 10. The earlier fix hardened SQLite locking
   while the contended resource was the scheduler, and passed its own verification.)*
9. **Set a ratchet from what the check itself measures.** *(2026-08-12: a floor of 13
   came from a script counting raw lines while the test counted distinct triples —
   actual 10. Three of slack silently absorbed a deliberately reintroduced bug during
   the probe. A ratchet with slack is not a ratchet.)*
10. **"Wait for X" is not a task.** If X may never arrive, build the check that replaces
    it. *(2026-08-12: K14 said "verify on the next real timeout in production" — with no
    users there is no next real timeout, so it became a stalled-database test instead.
    K7 was parked behind a spend decision and, once measured, turned out to be that
    decision's precondition.)*

**Retired this prune, with reasons:**

- *"Per-request state never goes on an agent instance"* → **became a check**
  (`tests/unit/test_no_per_request_state_on_singletons.py`, ratchet at 10).
- *"A sweep for long-lived objects must follow construction"* → **became the same
  check**; the reachability walk is implemented inside it.
- *"Never assert on source text"* → **merged into #1**; it was one idea about what makes
  a test a check, split across two entries.

## Run stamps

| Date | Commit | Diverged? |
|---|---|---|
| 2026-08-08 | `b4a6ca0` | yes — entries 1, 2, 3, 4, 7 written from this run |
| 2026-08-12 | `0162e2a` | yes — pruned to 10; #9 and #10 earned here, three entries retired |

## Recent log

**2026-08-12 — audit, re-plan, and ten backlog items.** The operator's answer that the
product is *pre-launch* inverted several rankings: what was justified by "users are
hitting this" lost its place, what makes the product correct before anyone arrives
gained it. Shipped: honest retrieval defaults, the deploy-gate flake fixed at its real
cause, the timeout path exercised against a stalled database, provenance on both halves
of the knowledge layer, prompt-loader failures made visible, a health probe that heals
a dead tunnel instead of watching it, MCP Host validation enabled and proven, and the
singleton-state sweep finished and turned into a ratchet.

**Four findings were disproved rather than fixed**, and that was the more useful
outcome: AUD-2's count, danger and location were all wrong; KL-2's Merkle trees are
already provided by git and by per-table fingerprints; C7 was already done; and C14's
obvious fix was rejected by a test that had never run. Two changes were written, tested
green, and reverted before shipping — the MCP allow-list derivation would have excluded
the API's own host, and the analytics master-switch guard would have let a stale worker
refuse legitimate work.

**2026-08-08 — query-timeout classification.** Four defects fixed (typed timeout,
one-narrowing-repair budget, loop breaker + deadline, trace finalization) plus a
pre-existing cross-request state leak found while crossing that boundary. Deployed as
v202. The run's own failures were more instructive than the code's: a self-approving
test, a branch missing its scenario, and two root causes that only survived because
someone re-read the code instead of trusting the write-up.
