# Retro — checkmydata-ai

What previous runs of the pipeline got wrong **in this project**. Read in full at stage 0;
these bind the run. Hard cap: **ten** standing instructions. Prune before adding.

## Standing instructions

1. **A test written after its implementation is not a check until it has been seen red.**
   Plant the defect it claims to catch and watch it fail. *(2026-08-08: the first
   `finalize_trace` no-clobber test asserted on source text; a blanket-overwrite defect
   preserved the text it looked for and the test passed green.)*
2. **Never assert on source text when you can assert on behaviour.** Intercept the
   statement, the call, the result. Source-text checks pass for the wrong reasons.
3. **A worktree separates documentation from code as thoroughly as it separates code.**
   Before merging, verify the branch contains the *docs* the change owes — especially
   `docs/ux/scenarios.md`. *(2026-08-08: the branch was green, complete, and had no
   scenario for its own user-facing change; caught one command before the merge.)*
4. **When a ledger entry names a root cause, re-derive it from the code before
   implementing it.** A deferred entry is a hypothesis written under time pressure.
   *(2026-08-08: K12 said "router signals are not stamped"; the defect was
   `finalize_trace` *erasing* values the buffer had already written. Building what the
   ledger said would have produced a green test and no production change.)*
5. **Verify the deploy against the running application, never against a workflow row.**
   Health, the migration revision in the boot log, and the artefact the change was
   supposed to alter. *(m0, C22: a workflow-status monitor reported a false success by
   matching a stale row, then missed a real deploy.)*
6. **Say which claim is unproven.** A clean boot is not proven behaviour. If the path
   cannot be exercised, name the check that would prove it and put it in the ledger
   rather than letting a green stage imply more than it measured.
7. **`grep` for a call site is not a survey of call sites.** Follow the value.
   *(2026-08-08: the plan named three `classify` call sites; one classified `str(exc)`
   where no `QueryResult` exists, and a fourth path would have stayed half-wired.)*
8. **Per-request state never goes on an agent instance in this codebase.**
   `chat.py:60` builds `ConversationalAgent()` at module level, so one `SQLAgent` serves
   every request in the process. Use the call frame or the existing `run_state`.

## Run stamps

| Date | Commit | Diverged? |
|---|---|---|
| 2026-08-08 | `b4a6ca0` | yes — entries 1, 2, 3, 4, 7 written from this run |

## Recent log

**2026-08-08 — query-timeout classification.** Four defects fixed (typed timeout,
one-narrowing-repair budget, loop breaker + deadline, trace finalization) plus a
pre-existing cross-request state leak found while crossing that boundary. Deployed as
v202. The run's own failures were more instructive than the code's: a self-approving
test, a branch missing its scenario, and two root causes that only survived because
someone re-read the code instead of trusting the write-up.
