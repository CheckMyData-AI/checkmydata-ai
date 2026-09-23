"""Online, reference-free evaluation of production traces (PRJ-13 T08c).

The offline tiers (`app/eval/routing`, `app/eval/gates`) prove a change did not break
what already worked; they cannot see what nobody put in a dataset. This tier reads what
production actually did — `request_traces` and `trace_spans` — and reports only what
needs no expected answer: outcome and failure taxonomy, latency against the request
budget, where the time went (LLM vs database), and the route distribution. It is never a
release gate (agent-evals §3: online is definitionally reference-free); it is how the next
fixtures are found, and a number a nightly job can trend.

Run: `python -m app.eval.online.trace_report --days 30` (read-only; prints JSON).
"""
