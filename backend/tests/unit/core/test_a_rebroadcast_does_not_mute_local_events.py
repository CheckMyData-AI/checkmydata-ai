"""B-19 — relaying another process's event must not mute this process's own events.

`_external_rebroadcast` was a process-wide attribute held True across awaits inside
`broadcast_external`. The trace persister and the run coordinator skip an event while it
is True — right for the relayed event, wrong for any LOCAL event that happens to be
delivered in the same window from another task: on the web dyno a chat's
`pipeline_start` arriving while a worker event was being relayed was dropped, and the
whole trace with it. The flag is a ContextVar now: true only in the relaying task.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.workflow_tracker import WorkflowEvent, WorkflowTracker


@pytest.mark.asyncio
async def test_a_local_event_during_a_relay_is_not_seen_as_relayed() -> None:
    tracker = WorkflowTracker()
    seen: dict[str, bool] = {}
    relay_hook_entered = asyncio.Event()
    release_relay = asyncio.Event()

    async def hook(event: WorkflowEvent) -> None:
        seen[event.step] = tracker._external_rebroadcast
        if event.step == "relayed":
            relay_hook_entered.set()
            await release_relay.wait()

    tracker.add_persistence_hook(hook)
    relay = asyncio.create_task(
        tracker.broadcast_external(
            WorkflowEvent(workflow_id="w-worker", step="relayed", status="started")
        )
    )
    await relay_hook_entered.wait()
    # A local event from ANOTHER task, delivered while the relay is still in flight.
    await tracker._broadcast(
        WorkflowEvent(workflow_id="w-chat", step="pipeline_start", status="started")
    )
    release_relay.set()
    await relay

    assert seen["relayed"] is True, "the relayed event must still be recognised as one"
    assert seen["pipeline_start"] is False, "a local event was muted by someone else's relay"
    assert tracker._external_rebroadcast is False
