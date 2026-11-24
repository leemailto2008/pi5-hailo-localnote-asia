"""N8（2026-11-24 localnote@mac）：SingleJob 背景工作不能永遠卡在 running（docstring：「否則前端會永遠停在 running」）。
原本只接 Exception：runner 被取消（CancelledError 是 BaseException；例如它等的內層工作被取消）或回傳的不是 dict 時，
_run 直接結束、state 停在 running，之後每次 start() 都 JobBusyError。"""
import asyncio

import pytest

from single_job import JobBusyError, SingleJob


def _run(job, runner):
    async def go():
        job.start(runner)
        try:
            await job._task
        except asyncio.CancelledError:
            pass
    asyncio.run(go())


def test_cancelled_runner_is_not_left_running():
    job = SingleJob("t")

    async def runner(j):
        raise asyncio.CancelledError()
    _run(job, runner)
    assert job.snapshot()["state"] == "stopped" and not job.running


def test_runner_returning_non_dict_is_an_error():
    job = SingleJob("t")

    async def runner(j):
        return None
    _run(job, runner)
    snap = job.snapshot()
    assert snap["state"] == "error" and "NoneType" in snap["error"]


def test_can_start_again_after_cancel():
    job = SingleJob("t")

    async def cancelled(j):
        raise asyncio.CancelledError()

    async def ok(j):
        return {"n": 1}
    _run(job, cancelled)
    _run(job, ok)                                   # 原本 JobBusyError
    assert job.snapshot()["state"] == "done" and job.snapshot()["result"] == {"n": 1}


def test_busy_while_running():
    async def go():
        job = SingleJob("t")
        gate = asyncio.Event()

        async def runner(j):
            await gate.wait()
            return {}
        job.start(runner)
        with pytest.raises(JobBusyError):
            job.start(runner)
        gate.set()
        await job._task
        assert job.snapshot()["state"] == "done"
    asyncio.run(go())
