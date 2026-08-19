# UX Audit — 2026-08-16 (ledger redesign)

- **Scope:** the five scenarios the `ledger` redesign touched — SCN-107, SCN-122, SCN-123, SCN-124, SCN-125. Everything else in the base is **out of scope** and unchanged since the 2026-07-19 audit.
- **Depth:** standard — scenario pass + flow/screen conformance. No heuristic, practice or coverage pass.
- **Method:** static code trace of `frontend/src`, evidence-backed with `file:line`. One batch; no subagents.
- **Base version:** `docs/ux/scenarios.md` at `08a5141` (branch `feat/ledger-redesign`).
- **Audited tree:** `4ffc669`.

## Summary

- **Totals: PASS 3 / PARTIAL 2 / FAIL 0 / BLOCKED 0** (5 scenarios)
- **Verdict: REFINE.** One finding, one root cause, two scenarios. Nothing here suggests the structure is wrong — the seal, the theme pair, the table and the transcript all do what the base says. A render guard is narrower than the derivation behind it.
- **Top issue:**
  1. **The seal never appears on a plain text answer** (`AUD-2026-08-16-01`, major). `sealStateFor` derives `unverified` for exactly that case and is tested for it, but the block that renders the chip and the seal is guarded by `responseType !== "text" && responseType !== "error"`. So the state the scenarios call the honest one — *the system cannot say how this was obtained* — is the one state the reader is least likely to see. SCN-122 says every answer carries a seal; SCN-125 says the chip and the seal sit above the answer.
- **Recommended next action:** drop `"text"` from that guard and render the seal (without the type chip, which has nothing to say for a plain answer). Two lines, and it makes the vocabulary's third state reachable in the place it matters most.

**Cross-batch:** single batch, so no cross-batch contradiction is possible. The one finding is deliberately cited on **both** SCN-122 and SCN-125 rather than split into two ids — it is one guard and one fix, and two ids would halve its priority.

## Batch 1: the redesign's five (SCN-107, SCN-122..125)

### SCN-107 — Runs & Errors log tabs — PASS
- **Geometry:** `components/logs/RunsTab.tsx:78-115`, `components/logs/ErrorsTab.tsx:113-170` — both on the shared table primitive, whose 32px rows, 12px `--muted` header over a hairline and `--row-hover` live in `components/shadcn/table.tsx:57-95`.
- **Status is never by colour alone:** `RunsTab.tsx:95-103`, `ErrorsTab.tsx:151-160` — `StatusDot` carries the hue, the word renders in `--ink` beside it.
- **Honesty debt from the 2026-07-19 audit is closed:** `RunsTab.tsx:73`, `ErrorsTab.tsx:108` — a fetch failure renders `ListError` with Retry, distinct from the empty state at `RunsTab.tsx:75` / `ErrorsTab.tsx:110`. The earlier PARTIAL ("shows *no data* on fetch error") no longer reproduces.
- **States:** loading `RunsTab.tsx:71`, empty `:75`, error `:73`, success `:78`.

### SCN-122 — Every answer says how it is known — PARTIAL
- **Derivation is real and tested:** `components/ui/Seal.tsx:64-84` derives from the answer's own evidence — the query, the retrieval count, the staleness the backend reported, the terminal response types. `__tests__/components/Seal.test.tsx:8-60` covers all three states plus the terminal cases, and four planted defects were watched failing.
- **The word always renders:** `Seal.tsx:96,125` — never the glyph alone, which is what the pack requires where the hue sits under AA.
- **Clicking opens the proof:** `ChatMessage.tsx:367-371` — the SQL panel where a query exists, the source list where retrieval does.
- **FINDING `AUD-2026-08-16-01` (major):** `ChatMessage.tsx:335` — the seal and the type chip are inside `{!isUser && responseType !== "text" && responseType !== "error" && (…)}`. A plain text answer therefore carries **no seal at all**, and `sealStateFor({responseType: "text"})` is precisely the `unverified` branch (`Seal.tsx:83`). The state the base calls the honest one is the one a reader will rarely meet. → **Fix:** render the seal for `text` too; keep the type chip suppressed, since it has nothing to add for a plain answer.

### SCN-123 — One design in light and in dark — PASS
- **Both selectors, always together:** `stores/theme-store.ts:23,27` (class + attribute) and the inline pre-hydration script at `app/layout.tsx:97`, which sets both before first paint.
- **The token layer switches on the attribute:** `app/globals.css:55` (the pack's own `[data-theme="dark"]` block, copied verbatim) while Tailwind's dark variant keys off the class at `globals.css:4`.
- **A check fails if either stops:** `__tests__/theme-store.test.ts` — "sets BOTH the .dark class and the pack's data-theme attribute", watched failing against a planted removal.
- **No colour survives from the other theme:** `__tests__/theme-tokens.test.ts` — "resolves every project-authored colour through a token, never a literal", which found and forced the fix of eight stale scrollbar literals.

### SCN-124 — A result reads as a ledger — PASS
- **Geometry:** `components/viz/DataTable.tsx:66,92,104,127-141` — `--panel-2` plane at `--r-card`, 32px header and rows, hairline dividers, `--row-hover`, mono row number dropped by a container query at `:97,129`.
- **Alignment decided from the values, not the name:** `components/viz/table-columns.ts:24-45` + `DataTable.tsx:45,105,137`. `__tests__/components/table-columns.test.ts` covers dates, booleans, all-null columns, one-bad-value columns and structured values; five planted defects watched failing.
- **Absence renders as `NULL`, not as blank:** `DataTable.tsx:142-144`.
- **Empty / capped:** `DataTable.tsx:114-122` ("No data returned") and `:156-165` (the count and a control to show all).
- **Chart ramp and the sixth series:** `components/viz/chart-series.ts:33-45`; unsupported type named rather than silent at `ChartRenderer.tsx:179-183`; legend only for several series at `:120`.
- **Motion:** `ChartRenderer.tsx:115-116` — 300 ms, and off under reduced motion.

### SCN-125 — The answer is the page, not a speech bubble — PARTIAL
- **The bubble split holds:** `ChatMessage.tsx:317-326` — the reader's turn capped at 95%/80% and filled in `--primary` (ink); the answer full width with no fill. `__tests__/components/ChatMessage.test.tsx` asserts both halves and was watched failing against a planted re-bubbling.
- **The caret blinks and stops with the stream:** `ChatPanel.tsx:920` renders `animate-cursor-blink` only inside the streaming branch; the keyframe is `globals.css` `cursor-blink`, `steps(1, end)`.
- **Thinking dots:** `ChatPanel.tsx:716-718,963-966`, stopped by the global reduced-motion rule at `globals.css:29`.
- **FINDING `AUD-2026-08-16-01` (same root cause):** the scenario's "above it sit the response-type chip and the seal" does not hold for a plain text answer — see SCN-122.

## Scope and limits

- **Covered:** the five scenarios above, statically, on `4ffc669`.
- **Left out, deliberately:** the other 120 scenarios in the base. This branch did not touch their behaviour, and their last verdicts are 2026-07-19's. Reading this report as if it covered them would be wrong.
- **Not verified, and it matters:**
  - ~~**The gap-not-zero claim in SCN-124 is verified at the MODEL, not at the pixels.**~~ **CLOSED 2026-08-16.** A throwaway route rendered a line and a bar series with two absent months and was screenshotted headless: the line **breaks** between the last present month and the next, and the two absent bars are **absent** rather than zero-height at the axis. The route came out in the same change.
  - **No live pass.** The dev server runs, but the browser tooling that drove earlier checks (claude-in-chrome, chrome-devtools MCP) is disconnected in this session; the two headless screenshots that did work covered `/login`, not the transcript or the logs tabs. Every verdict here is a static trace.
  - ~~**Contrast is stated, not measured in situ.**~~ **CLOSED 2026-08-16, and it found a defect.** Thirteen composed surfaces were computed from the token layer. Twelve were fine — the badges measure **16–18:1**, exactly because their word sits in `--ink` over a 10–12% tint. **The seal did not:** it painted its WORD in the state's colour, putting `Unverified` at **2.13:1** and `Verified` at **3.63:1** on the light panel — the first under even the 3:1 floor for a mark, on the element this whole design is remembered by, and against the component's own comment saying the word carries the meaning. The word is now `--ink` and the colour rides the glyph; the same words measure 16–18:1. The destructive button's hover was the same class of error at 3.05:1 and its word goes to `--ink` on hover too. `contrast.test.ts` computes all of it from `globals.css` on every run.
  - **No keyboard or screen-reader walk.** The focus contract is now uniform in source (`__tests__/pack-bans.test.ts`), which is not the same as a walk (BP-137).

## Post-audit

`AUD-2026-08-16-01` was fixed in the same session, at `ChatMessage.tsx` — the row
now renders for every assistant answer except an error, and the *type chip*
alone stays suppressed for `text`, because "text" is not a type worth naming.

The check that was missing is the point: `Seal.test.tsx` covered the derivation
thoroughly and stayed green throughout, because the defect was in the render
guard above it. The new check is render-level —
`ChatMessage.test.tsx` "seals a plain text answer as unverified, and names no
type for it" — and it was watched failing against the restored guard.

After the fix: tsc 0 · eslint 0 · vitest 656/656 · build 0. SCN-122 and SCN-125
are recorded in the base as `2026-08-16 PARTIAL → fixed` rather than as PASS:
the audited tree was PARTIAL, and rewriting that to PASS would erase the only
evidence that the gap existed.
