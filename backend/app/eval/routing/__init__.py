"""Routing eval — does the orchestrator's router send a question where it belongs? (PRJ-13 T08a)

The router (`app.agents.router.route_request`) makes one LLM decision per request —
`direct | query | knowledge | git | mcp | analytics | explore` plus complexity — and every
later stage runs on the path it picks. This package makes "did routing get better or
worse" a number, per the `agent-evals` doctrine (observable up front, corpus grown later):

* **Observable** — for each case, the set of routes that count as correct, and (where it
  is a claim) whether the case must reach the multi-stage pipeline. Written with the case,
  before any run. Several routes can be correct: "is the status column an enum?" is
  answerable from the index (`knowledge`) or by a query (`query`).
* **Corpus** — `seed_cases.jsonl`, CURATED (provenance on every row) with happy,
  adversarial and failure cases, because production has only 16 labelled traces
  (measured 2026-09-23: 162 of 179 predate route persistence). Production questions are
  customer data and never enter git; they are extracted to a local, git-ignored file by
  `python -m app.eval.routing.run extract` and supplement the seed, never replace it.
* **Two tiers.** `replay` scores RECORDED router responses through the real parser and
  capability guards — deterministic, free, the CI gate. `live` calls the configured model
  `k` times per case and reports accuracy with a Wilson interval; it is opt-in (it costs
  money and is stochastic) and refreshes the recordings.

Docs: `docs/SYSTEM_ARCHITECTURE.md` §eval, `docs/audits/2026-09-13-connections-sync-
orchestrator-audit.md` §PRJ-13.
"""
