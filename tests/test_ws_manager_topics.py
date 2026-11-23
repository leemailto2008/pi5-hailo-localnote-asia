"""ws_manager 訂閱主題：bt_hub（藍牙中心詳細狀態，每 1.5 s 一次）只送給開著藍牙中心、明確訂閱的客戶端。

2026-11-23（localnote@mac）找到的 bug：每個連線預設都有 "*"，broadcast 只要看到 "*" 就送，
於是網頁送 subscribe_bt_hub enable=false（main.py → ws_manager.subscribe(ws, "bt_hub", False)）完全沒作用，
所有分頁不管有沒有開藍牙中心都一直收到 bt_hub。
"""
import asyncio
import json

import ws_manager as wm


class FakeWS:
    def __init__(self, fail=False):
        self.sent, self.closed, self.fail = [], False, fail

    async def accept(self):
        pass

    async def send_text(self, payload):
        if self.fail:
            raise RuntimeError("reset")
        self.sent.append(json.loads(payload)["type"])

    async def close(self, code=1000):
        self.closed = True


def _run(coro):
    return asyncio.run(coro)


def test_bt_hub_is_opt_in():
    async def scenario():
        m = wm.ConnectionManager()
        plain, hub = FakeWS(), FakeWS()
        await m.connect(plain)
        await m.connect(hub)
        m.subscribe(hub, "bt_hub")
        await m.broadcast("bt_hub", {"x": 1}, topic="bt_hub")
        m.subscribe(hub, "bt_hub", enable=False)
        await m.broadcast("bt_hub", {"x": 2}, topic="bt_hub")
        return plain, hub

    plain, hub = _run(scenario())
    assert plain.sent == [], "沒開藍牙中心的分頁不應收到 bt_hub"
    assert hub.sent == ["bt_hub"], "取消訂閱後不應再收到"


def test_wildcard_still_covers_ordinary_events():
    """completed、translation_stream 不在預設清單裡，靠 "*" 送達，修正後不能受影響。"""
    async def scenario():
        m = wm.ConnectionManager()
        ws = FakeWS()
        await m.connect(ws)
        for ev in ("completed", "translation_stream", "status", "vu"):
            await m.broadcast(ev, {})
        return ws

    assert _run(scenario()).sent == ["completed", "translation_stream", "status", "vu"]


def test_subscribe_unknown_socket_and_disconnect():
    async def scenario():
        m = wm.ConnectionManager()
        stranger = FakeWS()
        m.subscribe(stranger, "bt_hub")                 # 沒連線過：不建立訂閱
        assert stranger not in m.subscriptions
        ws = FakeWS()
        await m.connect(ws)
        await m.disconnect(ws)
        await m.disconnect(ws)                          # 重複斷線不出錯
        assert not m.active_connections and ws not in m.subscriptions and ws not in m._send_locks
        await m.broadcast("status", {})                 # 沒有連線：直接返回
        await m.send_personal(ws, "status", {})         # 已斷線：不送
        return ws

    assert _run(scenario()).sent == []


def test_send_personal_error_keeps_connection_but_logs():
    async def scenario():
        m = wm.ConnectionManager()
        ws = FakeWS(fail=True)
        await m.connect(ws)
        await m.send_personal(ws, "status", {"a": 1})
        return m, ws

    m, ws = _run(scenario())
    assert ws in m.active_connections                   # 非逾時錯誤只記 log（下一次 broadcast 失敗時才移除）


def test_send_without_lock_and_close_quietly():
    async def scenario():
        m = wm.ConnectionManager()
        ws = FakeWS()
        m.active_connections.add(ws)                    # 沒經過 connect → 沒有送出鎖
        await m._send(ws, json.dumps({"type": "x"}))

        class Boom(FakeWS):
            async def close(self, code=1000):
                raise RuntimeError("already closed")
        await wm.ConnectionManager._close_quietly(Boom())   # 不拋例外
        return ws

    assert _run(scenario()).sent == ["x"]
