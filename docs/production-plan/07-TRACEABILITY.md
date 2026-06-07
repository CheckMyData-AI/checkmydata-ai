# 07 — Traceability & Consistency

This document closes the loop: it cross-links findings → backlog → modules → roadmap,
records the verified doc/reality mismatches the plan must fix, and states the internal
consistency checks performed on this package.

## 1. Master traceability matrix

Each row connects an audit finding to the task(s) that close it, the owning module, the
roadmap phase, and the QA case that verifies it.

| Finding | Sev | Backlog task(s) | Module | Phase | Verified by |
| --- | --- | --- | --- | --- | --- |
| F-SEC-1 MCP auth/tenancy | S1 | T-SEC-1 | M1 | P0-MVP | TC-AUTH-4 |
| F-SEC-2 WS token in URL | S1 | T-SEC-2 | M1 | P0-MVP | TC-AUTH-3 |
| F-SEC-3 JWT in localStorage | S1 | T-SEC-3 | M1 | P0-MVP | TC-AUTH-2 |
| F-SEC-4 SSH host-key default | S1 | T-SEC-4 | M2 | P0-MVP | TC-CONN-1 |
| F-SEC-5 SSH pre-commands | S2 | T-SEC-5 | M2 | P1-BETA | TC-CONN-2 |
| F-SEC-6 CSP/HSTS | S2 | T-SEC-6 | M1 | P0-MVP | §6 security scan |
| F-SEC-7 Rate limit shared store | S2 | T-SEC-7 | M11 | P1-BETA | LT-2 |
| F-SEC-8 Error tracking | S2 | T-OBS-1 | M11 | P0-MVP | TC-OBS-1 |
| F-SEC-9 SAST/dep scan | S3 | T-QA-4 | M11 | P1-BETA | §6 SAST |
| F-BIZ-1 No billing layer | S1 | T-BILL-1..7 | M9 | P0-MVP | TC-BILL-1..8 |
| F-BIZ-2 Budgets dead code | S2 | T-BILL-6 | M9/M11 | P0-MVP | TC-BILL-5 |
| F-BIZ-3 No pricing/plans | S2 | T-BILL-2, T-BILL-8, T-GROW-1 | M9/M12 | P0-MVP | TC-BILL-6 |
| F-ARCH-1 In-memory state | S2 | T-SCALE-1 | M11 | P1-BETA | LT-2 |
| F-ARCH-2 God-files | S2 | T-ARCH-1, T-ARCH-2 | M3/M7 | P1-BETA | unit tests post-split |
| F-ARCH-3 Dual orchestration | S3 | T-ARCH-3 | M3 | P1-BETA | parity tests |
| F-ARCH-4 Deprecated modules | S3 | T-ARCH-4 | M3 | P1-BETA | CI import check |
| F-ARCH-5 MySQL OOM | S2 | T-ARCH-5 | M2 | P0-MVP | TC-CONN-3 / LT-3 |
| F-ARCH-6 Features default-off | S3 | T-ARCH-6, T-ADMIN-3 | M4/M10 | P1-BETA | benchmark report |
| F-QA-1 Coverage 40 vs 72 | S2 | T-QA-1, T-DOC-1 | M11 | P0-MVP | §9 CI gate |
| F-QA-2 No E2E | S2 | T-QA-2 | M11 | P1-BETA | E2E suite |
| F-QA-3 No load tests | S2 | T-QA-3 | M11 | P1-BETA | LT-1..5 |
| F-QA-4 Doc/reality mismatch | S3 | T-QA-1, T-DOC-1 | M11 | P0-MVP | docs-consistency check |
| F-UX-1 Dashboard auth gate | S2 | T-UX-1 | M7 | P0-MVP | TC-AUTH-1 |
| F-UX-2 Unwired components | S3 | T-UX-2 | M7 | P1-BETA | component tests |
| F-UX-3 Title/a11y | S3 | T-UX-3, T-QA-5, T-GROW-2 | M7/M12 | P1-BETA | axe checks |
| F-LEGAL-1 DPA/retention | S2 | T-LEGAL-1, T-LEGAL-2 | M9/M11 | P1-BETA | TC (deletion) |
| F-FIN-1 Cost guardrails | S2 | T-BILL-6, T-SEC-7, T-OBS-2 | M9/M11 | P0/P1 | TC-BILL-5, LT-4 |
| F-OPS-1 No admin console | S3 | T-ADMIN-1, T-ADMIN-2, T-ADMIN-3 | M10 | P1-BETA | TC-ADMIN-1/2 |

## 2. Backlog → module → phase index

Every `T-*` task maps to exactly one owning module and one delivery phase.

| Task | Module | Phase | Task | Module | Phase |
| --- | --- | --- | --- | --- | --- |
| T-SEC-1 | M1 | P0 | T-BILL-6 | M9/M11 | P0 |
| T-SEC-2 | M1 | P0 | T-BILL-7 | M9 | P0 |
| T-SEC-3 | M1 | P0 | T-BILL-8 | M9 | P1 |
| T-SEC-4 | M2 | P0 | T-BILL-9 | M9 | P1 |
| T-SEC-5 | M2 | P1 | T-OBS-1 | M11 | P0 |
| T-SEC-6 | M1 | P0 | T-OBS-2 | M11 | P1 |
| T-SEC-7 | M11 | P1 | T-UX-1 | M7 | P0 |
| T-ARCH-1 | M3 | P1 | T-UX-2 | M7 | P1 |
| T-ARCH-2 | M3/M7 | P1 | T-UX-3 | M7 | P1 |
| T-ARCH-3 | M3 | P1 | T-ADMIN-1 | M10 | P1 |
| T-ARCH-4 | M3 | P1 | T-ADMIN-2 | M10 | P1 |
| T-ARCH-5 | M2 | P0 | T-ADMIN-3 | M10 | P2 |
| T-ARCH-6 | M4 | P1 | T-LEGAL-1 | M9/M11 | P1 |
| T-SCALE-1 | M11 | P1 | T-LEGAL-2 | M11 | P1 |
| T-BILL-1 | M9 | P0 | T-GROW-1 | M12 | P0 |
| T-BILL-2 | M9 | P0 | T-GROW-2 | M12 | P1 |
| T-BILL-3 | M9 | P0 | T-GROW-3 | M12 | P2 |
| T-BILL-4 | M9 | P0 | T-GROW-4 | M12 | P2 |
| T-BILL-5 | M9 | P0 | T-QA-1 | M11 | P0 |
| T-QA-2 | M11 | P1 | T-QA-3 | M11 | P1 |
| T-QA-4 | M11 | P1 | T-QA-5 | M11 | P1 |
| T-DOC-1 | M11 | P1 | | | |

## 3. Verified doc/reality mismatches to fix (F-QA-1, F-QA-4)

These were confirmed by reading the repository. They are the concrete list `T-QA-1` and
`T-DOC-1` must resolve.

| # | Claim in docs | Reality in code | Action |
| --- | --- | --- | --- |
| 1 | `README.md:226` — "72%+ backend coverage (CI-enforced minimum)" | `.github/workflows/ci.yml:96` enforces `--fail-under=40` | Set CI to the real target and update README to match |
| 2 | `CONTRIBUTING.md:138` — "Backend CI enforces ≥72% coverage" | CI enforces 40% | Update to the agreed number once CI is changed |
| 3 | `docs/agent-changelog.md:42` — "72.00%, meeting the CI `cov-fail-under=72` threshold" | No 72% threshold in CI; gate is 40% | Mark as historical or correct |
| 4 | `docs/agent-changelog.md:121` — "`--cov-fail-under` increased from 68% to 69%" | Current gate is 40% (different mechanism/value) | Reconcile historical narrative with current gate |
| 5 | `docs/DEPLOYMENT.md:28` — documents 40% gate | Matches CI (`--fail-under=40`) | Keep in sync when target changes |
| 6 | Feature docs imply advanced retrieval is active | `hybrid_retrieval_enabled`, `schema_retrieval_enabled`, `code_graph_enabled`, `lineage_enabled` default OFF | Align docs to actual defaults (T-ARCH-6) |

Net: the single most misleading claim is that **CI enforces 72% coverage when it actually
enforces 40%**. Until `T-QA-1` lands, reviewers should treat 40% as the only enforced floor.

## 4. Internal consistency checks performed on this package

- Every finding ID in `00-AUDIT-FINDINGS.md` has at least one backlog task in
  `04-BACKLOG.md`, and vice versa every `T-*` task references a finding or a PRD/Tech-Spec
  requirement.
- Every backlog task names an owning module that exists in `03-MODULES.md` (M1–M12).
- Every finding/task is placed in a roadmap phase in `05-ROADMAP.md`; all S1 findings land
  in P0-MVP and all S1/S2 are closed by end of P1-BETA.
- Every Critical scenario in `06-QA-PLAN.md` maps to a finding it protects.
- Priority counts: P0 set in `04-BACKLOG.md` matches the P0-MVP scope in `05-ROADMAP.md`.

## 5. Open items carried forward (Needs validation)

The decisions in `00-AUDIT-FINDINGS.md` §8 (pricing, deployment/Redis, mobile, coverage
target, LLM data handling, MCP auth model, session model, default-on features) are
prerequisites for finalizing parts of the PRD/Tech-Spec/Roadmap. They are intentionally
left as proposed defaults and must be signed off before the corresponding build tasks start.
