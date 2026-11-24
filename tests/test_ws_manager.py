"""ws_manager 送出逾時測試：一個不再讀取的客戶端 (凍結的瀏覽器分頁) 不可以卡住 broadcast / 會議紀要流程。

2026-10-28 4 小時 e2e：broadcast() 的 await send_text() 沒有逾時，凍結分頁讓紀要停在第 3/45 段 1 小時。
"""
import asyncio
import sys
import time
import types

try:
    import fastapi  # noqa: F401
except ImportError:   # CI unit job 不裝 fastapi；ws_manager 只拿它當型別
    stub = types.ModuleType("fastapi")
    stub.WebSocket = object
    stub.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})
    sys.modules["fastapi"] = stub

import ws_manager as wm


class FakeWS:
    def __init__(self, hang: bool = False, fail: bool = False):
        self.hang, self.fail = hang, fail
        self.sent, self.closed = [], False

    async def accept(self):
        pass

    async def send_text(self, payload: str):
        if self.fail:
            raise RuntimeError("connection reset")
        if self.hang:
            await asyncio.Event().wait()   # 永遠不完成，模擬 TCP 送出佇列塞滿
        self.sent.append(payload)

    async def close(self, code: int = 1000):
        self.closed = True


def _run(coro):
    return asyncio.run(coro)


def test_hung_client_does_not_block_broadcast(monkeypatch):
    monkeypatch.setattr(wm, "SEND_TIMEOUT_S", 0.3)

    async def scenario():
        m = wm.ConnectionManager()
        good, stuck = FakeWS(), FakeWS(hang=True)
        await m.connect(good)
        await m.connect(stuck)
        t0 = time.monotonic()
        await m.broadcast("summary_stream", {"text": "段 3/45"})
        elapsed = time.monotonic() - t0
        await asyncio.sleep(0.05)   # 讓背景 close 跑完
        return m, good, stuck, elapsed

    m, good, stuck, elapsed = _run(scenario())
    assert elapsed < 1.0                       # 最多拖一個逾時 (並行送出)
    assert len(good.sent) == 1                 # 正常的客戶端照樣收到
    assert stuck not in m.active_connections   # 卡住的連線被移除
    assert stuck not in m.subscriptions and stuck not in m._send_locks
    assert good in m.active_connections


def test_after_drop_next_broadcast_is_fast(monkeypatch):
    monkeypatch.setattr(wm, "SEND_TIMEOUT_S", 0.3)

    async def scenario():
        m = wm.ConnectionManager()
        good = FakeWS()
        await m.connect(good)
        await m.connect(FakeWS(hang=True))
        await m.broadcast("status", {"n": 1})
        t0 = time.monotonic()
        for i in range(20):
            await m.broadcast("status", {"n": i})
        return good, time.monotonic() - t0

    good, elapsed = _run(scenario())
    assert elapsed < 0.2
    assert len(good.sent) == 21


def test_failing_client_is_dropped():
    async def scenario():
        m = wm.ConnectionManager()
        bad = FakeWS(fail=True)
        await m.connect(bad)
        await m.broadcast("status", {})
        return m, bad

    m, bad = _run(scenario())
    assert bad not in m.active_connections


def test_send_personal_times_out_and_drops(monkeypatch):
    monkeypatch.setattr(wm, "SEND_TIMEOUT_S", 0.3)

    async def scenario():
        m = wm.ConnectionManager()
        stuck = FakeWS(hang=True)
        await m.connect(stuck)
        t0 = time.monotonic()
        await m.send_personal(stuck, "status", {})
        return m, stuck, time.monotonic() - t0

    m, stuck, elapsed = _run(scenario())
    assert elapsed < 1.0
    assert stuck not in m.active_connections


def test_dropped_client_is_skipped_afterwards(monkeypatch):
    monkeypatch.setattr(wm, "SEND_TIMEOUT_S", 0.3)
    drops = []

    async def scenario():
        m = wm.ConnectionManager()
        orig = m._drop

        async def counting_drop(conns, reason=""):
            drops.append(len([c for c in conns if c in m.active_connections]))
            await orig(conns, reason)
        m._drop = counting_drop
        stuck = FakeWS(hang=True)
        await m.connect(stuck)
        await m.send_personal(stuck, "status", {})          # 逾時 → 移除
        t0 = time.monotonic()
        for _ in range(5):
            await m.send_personal(stuck, "status", {})      # 已移除：立即返回
        await m.broadcast("status", {})
        return time.monotonic() - t0

    elapsed = _run(scenario())
    assert elapsed < 0.1
    assert drops == [1]


def test_unsubscribed_topic_not_sent():
    async def scenario():
        m = wm.ConnectionManager()
        ws = FakeWS()
        await m.connect(ws)
        m.subscriptions[ws] = {"status"}
        await m.broadcast("vu", {"db": -20})
        await m.broadcast("status", {"ok": True})
        return ws

    ws = _run(scenario())
    assert len(ws.sent) == 1


def test_close_tasks_are_kept_until_done():
    """N8：_drop 建的關閉 task 要留住參照（event loop 只有弱參照，可能還沒關完就被回收），關完自動移除。"""
    import asyncio
    from ws_manager import ConnectionManager

    class _WS:
        closed = False

        async def accept(self):
            pass

        async def close(self, code=1000):
            await asyncio.sleep(0.05)
            self.closed = True

    async def go():
        m = ConnectionManager()
        ws = _WS()
        await m.connect(ws)
        await m._drop([ws], "test")
        assert len(m._closing) == 1                      # 還在關：參照留著
        await asyncio.sleep(0.2)
        assert ws.closed and not m._closing              # 關完：自動移除
    asyncio.run(go())


def test_payload_shape_subscribe_toggle_defaults_and_close_code():
    """N11：網頁靠 {"type", "data"} 這兩個鍵分派訊息；預設訂閱的主題；取消訂閱；逾時關閉用 1011。"""
    import asyncio
    import json
    from ws_manager import ConnectionManager

    class _WS:
        def __init__(self):
            self.sent, self.code = [], None

        async def accept(self):
            pass

        async def send_text(self, t):
            self.sent.append(json.loads(t))

        async def close(self, code=1000):
            self.code = code

    async def go():
        m = ConnectionManager()
        ws = _WS()
        await m.connect(ws)
        assert m.subscriptions[ws] == {"*", "system", "status", "bt", "vu", "audio_ready", "transcript_stream",
                                       "transcript_ready", "summary_stream"}
        await m.broadcast("status", {"a": 1})
        await m.send_personal(ws, "bt", {"b": 2})
        assert ws.sent == [{"type": "status", "data": {"a": 1}}, {"type": "bt", "data": {"b": 2}}]
        m.subscribe(ws, "bt_hub")
        assert "bt_hub" in m.subscriptions[ws]
        m.subscribe(ws, "bt_hub", enable=False)
        assert "bt_hub" not in m.subscriptions[ws]
        await m._drop([ws], "test")
        await asyncio.sleep(0.05)
        assert ws.code == 1011
    asyncio.run(go())
