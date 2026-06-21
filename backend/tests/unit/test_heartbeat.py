import asyncio

from app.core.heartbeat import heartbeat


async def test_heartbeat_writes_immediately_and_periodically():
    calls: list[float] = []

    async def writer():
        calls.append(asyncio.get_event_loop().time())

    async with heartbeat(writer, interval_seconds=0.05):
        await asyncio.sleep(0.17)
    # immediate write + ~3 periodic
    assert len(calls) >= 3


async def test_heartbeat_swallows_writer_errors():
    count = {"n": 0}

    async def bad_writer():
        count["n"] += 1
        raise RuntimeError("boom")

    async with heartbeat(bad_writer, interval_seconds=0.05):
        await asyncio.sleep(0.12)
    assert count["n"] >= 1  # kept ticking despite errors


async def test_heartbeat_stops_after_exit():
    calls = {"n": 0}

    async def writer():
        calls["n"] += 1

    async with heartbeat(writer, interval_seconds=0.05):
        await asyncio.sleep(0.06)
    after = calls["n"]
    await asyncio.sleep(0.12)
    assert calls["n"] == after  # no writes after exit
