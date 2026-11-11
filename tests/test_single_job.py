# -*- coding: utf-8 -*-
import asyncio

import pytest

from single_job import JobBusyError, SingleJob


async def _wait_finished(job, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if not job.running:
            return job.snapshot()
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish")


def test_idle_snapshot():
    assert SingleJob("x").snapshot() == {"state": "idle"}


def test_runs_to_done_with_progress_and_elapsed():
    async def scenario():
        job = SingleJob("x")
        gate = asyncio.Event()

        async def runner(j):
            j.update(done=1, total=2)
            await gate.wait()
            return {"value": 42}

        snap = job.start(runner, mode="fix", total=2)
        assert snap["state"] == "running" and snap["mode"] == "fix" and "elapsed" in snap
        await asyncio.sleep(0)
        assert job.snapshot()["done"] == 1
        with pytest.raises(JobBusyError):
            job.start(runner)
        gate.set()
        final = await _wait_finished(job)
        assert final["state"] == "done" and final["result"] == {"value": 42} and final["elapsed"] >= 0

    asyncio.run(scenario())


def test_stopped_result_is_reported_as_stopped():
    async def scenario():
        job = SingleJob("x")

        async def runner(j):
            return {"stopped": True}

        job.start(runner)
        assert (await _wait_finished(job))["state"] == "stopped"

    asyncio.run(scenario())


def test_runner_exception_becomes_error_state_and_job_can_restart():
    async def scenario():
        job = SingleJob("x")

        async def bad(j):
            raise RuntimeError("boom")

        job.start(bad)
        final = await _wait_finished(job)
        assert final["state"] == "error" and final["error"] == "boom"

        async def good(j):
            return {}

        job.start(good)
        assert (await _wait_finished(job))["state"] == "done"

    asyncio.run(scenario())


def test_meeting_busy_reason_blocks_recording_and_processing():
    from single_job import meeting_busy_reason

    assert meeting_busy_reason(True, "done") is not None
    assert meeting_busy_reason(False, "recording") is not None
    assert "紀要" in meeting_busy_reason(False, "processing")
    for state in ("idle", "done", "completed", "error", None):
        assert meeting_busy_reason(False, state) is None
