"""N8（2026-11-24 localnote@mac）：SingleJob 背景工作不能永遠卡在 running（docstring：「否則前端會永遠停在 running」）。
原本只接 Exception：runner 被取消（CancelledError 是 BaseException；例如它等的內層工作被取消）或回傳的不是 dict 時，
_run 直接結束、state 停在 running，之後每次 start() 都 JobBusyError。"""
import asyncio
import os

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


def test_error_messages_and_busy_message():
    job = SingleJob("t")

    async def cancelled(j):
        raise asyncio.CancelledError()

    async def bad(j):
        return 3
    _run(job, cancelled)
    assert job.snapshot()["error"] == "cancelled"
    _run(job, bad)
    assert job.snapshot()["error"] == "runner returned int"

    async def go():
        j = SingleJob("polish")
        gate = asyncio.Event()

        async def r(_):
            await gate.wait()
            return {}
        j.start(r)
        with pytest.raises(JobBusyError, match=r"^polish is already running$"):
            j.start(r)
        gate.set()
        await j._task
    asyncio.run(go())


def test_elapsed_one_decimal_and_persist_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job = SingleJob("t", persist_path="r.json")                  # 沒有資料夾的相對路徑：存在目前目錄，不另建資料夾

    async def ok(j):
        return {"x": 1}
    _run(job, ok)
    assert sorted(os.listdir(tmp_path)) == ["r.json"]
    job._state.update(started=100.0, finished=101.26)
    assert job.snapshot()["elapsed"] == 1.3
