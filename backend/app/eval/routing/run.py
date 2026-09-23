"""Routing eval CLI (PRJ-13 T08a).

    python -m app.eval.routing.run replay            # CI tier: recordings vs baseline
    python -m app.eval.routing.run live --k 3        # opt-in: the configured model, k runs
    python -m app.eval.routing.run live --k 3 --record --set-baseline

`live` needs an LLM key and costs money (the cases x k router calls, each bounded at
512 completion tokens). `--record` rewrites `recordings.jsonl` with the raw replies, which
is how the replay tier learns a new model's behaviour; `--set-baseline` writes the live
accuracy as the new `baseline.json`. Both are deliberate acts, reviewed in the diff.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from app.llm.router import LLMRouter

from app.eval.routing.harness import (
    BASELINE,
    RECORDINGS,
    CaseError,
    Report,
    gate,
    load_cases,
    replay,
    score,
)


class _Recorder:
    """An `LLMRouter` stand-in that forwards and keeps the raw text of each reply."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.last: str | None = None

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        resp = await self._inner.complete(*args, **kwargs)
        self.last = resp.content
        return resp


async def _live(k: int, model: str | None) -> tuple[Report, list[dict]]:
    from app.agents.router import route_request
    from app.llm.router import LLMRouter

    cases = load_cases()
    recorder = _Recorder(LLMRouter())
    report = Report()
    recordings: list[dict] = []
    for case in cases:
        for _ in range(k):
            recorder.last = None
            flags = case.capability_flags
            result = await route_request(
                case.question,
                # Duck-typed: route_request only awaits `.complete`, which the recorder
                # forwards unchanged. A subclass would construct a second router.
                cast("LLMRouter", recorder),
                model=model,
                has_connection=flags["has_connection"],
                has_knowledge_base=flags["has_knowledge_base"],
                has_mcp_sources=flags["has_mcp_sources"],
                has_repo=flags["has_repo"],
                has_analytics_sources=flags["has_analytics_sources"],
            )
            report.outcomes.append(score(case, result))
            if recorder.last is not None:
                recordings.append({"case_id": case.id, "raw": recorder.last})
            else:
                report.errors.append(f"{case.id}: the router call failed (no reply to record)")
    return report, recordings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.eval.routing.run")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("replay")
    live = sub.add_parser("live")
    live.add_argument("--k", type=int, default=3)
    # The model production routes on. The router runs on `ROUTER_MODEL` when set, else
    # on the model the CALLER passes — in chat, the project's `agent_llm_model` — so an
    # eval that passes nothing measures the background default instead.
    live.add_argument("--model", default=None)
    live.add_argument("--record", action="store_true")
    live.add_argument("--set-baseline", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.mode == "replay":
            report = replay(load_cases())
            baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
            print(json.dumps({"tier": "replay", **report.to_dict()}, ensure_ascii=False))
            reasons = gate(report, baseline)
            for reason in reasons:
                print(f"GATE: {reason}", file=sys.stderr)
            return 1 if reasons else 0

        report, recordings = asyncio.run(_live(args.k, args.model))
    except CaseError as exc:
        print(f"TEST_ERROR: {exc}", file=sys.stderr)
        return 2

    from app.config import settings

    model = settings.router_model or args.model or settings.default_llm_model or "(default)"
    summary = {"tier": "live", "k": args.k, "model": model, **report.to_dict()}
    print(json.dumps(summary, ensure_ascii=False))
    if args.record:
        RECORDINGS.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recordings),
            encoding="utf-8",
        )
    if args.set_baseline:
        BASELINE.write_text(
            json.dumps(
                {
                    "accuracy": round(report.accuracy, 2),
                    "interval_95": summary["interval_95"],
                    "n": report.n,
                    "k": args.k,
                    "model": model,
                    "measured": datetime.now(UTC).date().isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
