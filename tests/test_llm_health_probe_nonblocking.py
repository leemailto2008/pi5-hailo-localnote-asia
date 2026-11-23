"""llm_backend：async 路徑的健康檢查（requests.get，最長 1.5 s）不能卡住 event loop。
2026-11-23 localnote@mac（S17 深度審查）：aiter_chat_stream／achat_complete 原本直接呼叫 backends_in_order()／cpu_first_backends()，
健康快取每 20 s 過期，過期後下一個 LLM 呼叫就在 event loop 上同步 requests.get，整個 API／WebSocket／即時稿 coroutine 停住。
"""
import asyncio
import time

import llm_backend as lb

PROBE_S = 0.6


def _setup(monkeypatch):
    monkeypatch.setattr(lb, "PREFERRED_BACKEND", "hailo")
    lb._health_cache.clear()

    def slow_probe(backend, timeout=1.5):
        time.sleep(PROBE_S)
        return False                                  # Hailo 不健康 → 只剩 CPU，下面的假 CPU 也會失敗
    monkeypatch.setattr(lb, "_probe_backend", slow_probe)
    monkeypatch.setattr(lb, "_free_npu_for_llm", lambda: None)


async def _ticks_while(coro_factory):
    ticks = 0
    stop = False

    async def ticker():
        nonlocal ticks
        while not stop:
            await asyncio.sleep(0.05)
            ticks += 1

    t = asyncio.ensure_future(ticker())
    await asyncio.sleep(0)
    try:
        await coro_factory()
    except lb.LLMError:
        pass
    stop = True
    await t
    return ticks


def _refuse_all(monkeypatch):
    import httpx

    class Refuse(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("refused", request=request)
    real = httpx.AsyncClient
    monkeypatch.setattr(lb.httpx, "AsyncClient", lambda **kw: real(transport=Refuse(), **kw))


def test_stream_probe_does_not_block_loop(monkeypatch):
    _setup(monkeypatch)
    _refuse_all(monkeypatch)

    async def run():
        async for _ in lb.aiter_chat_stream("hi"):
            pass
    ticks = asyncio.run(_ticks_while(run))
    assert ticks >= int(PROBE_S / 0.05) // 2, ticks       # 原本探測期間 0 次


def test_cpu_first_probe_does_not_block_loop(monkeypatch):
    _setup(monkeypatch)
    _refuse_all(monkeypatch)

    async def run():
        async for _ in lb.aiter_chat_stream("hi", cpu_first=True):
            pass
    assert asyncio.run(_ticks_while(run)) >= int(PROBE_S / 0.05) // 2


def test_achat_probe_does_not_block_loop(monkeypatch):
    _setup(monkeypatch)
    _refuse_all(monkeypatch)
    assert asyncio.run(_ticks_while(lambda: lb.achat_complete("hi"))) >= int(PROBE_S / 0.05) // 2


def test_order_unchanged(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(lb, "_probe_backend", lambda b, timeout=1.5: True)
    assert [b.name for b in lb.backends_in_order(force_refresh=True)] == ["hailo", "cpu", "cpu"]
    assert [b.name for b in lb.cpu_first_backends()] == ["cpu", "cpu", "hailo"]
