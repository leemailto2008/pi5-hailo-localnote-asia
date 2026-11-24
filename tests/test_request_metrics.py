"""request_metrics（Task 28）：百分位數、每路由統計、慢請求 JSON log、FastAPI 中介層與 /api/metrics。"""
import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import request_metrics as rm


def test_percentile_nearest_rank():
    vals = list(range(1, 101))            # 1..100
    assert rm.percentile(vals, 50) == 50
    assert rm.percentile(vals, 95) == 95
    assert rm.percentile(vals, 99) == 99
    assert rm.percentile([7.0], 99) == 7.0
    assert rm.percentile([], 50) is None


def test_record_keeps_window_and_counts_errors():
    m = rm.RequestMetrics(keep=3, slow_ms=1e9)
    for ms in (10, 20, 30, 40):
        m.record("/api/x", "GET", 200, ms)
    m.record("/api/x", "GET", 503, 50)
    s = m.summary()["routes"]["GET /api/x"]
    assert s["count"] == 5 and s["window"] == 3 and s["errors_5xx"] == 1
    assert s["max_ms"] == 50 and s["p50_ms"] == 40      # 只看最近 3 筆：30、40、50


def test_slow_request_logs_one_json_line(caplog):
    m = rm.RequestMetrics(slow_ms=100)
    with caplog.at_level(logging.WARNING, logger="request_metrics"):
        m.record("/api/slow", "POST", 200, 150.0)
        m.record("/api/fast", "GET", 200, 5.0)
    lines = [r.getMessage() for r in caplog.records if r.name == "request_metrics"]
    assert len(lines) == 1
    d = json.loads(lines[0])
    assert d == {"event": "slow_request", "method": "POST", "route": "/api/slow", "status": 200, "ms": 150.0}


def test_middleware_uses_route_template_and_serves_metrics():
    app = FastAPI()

    @app.get("/api/item/{iid}")
    def item(iid: str):
        if iid == "bad":
            raise HTTPException(status_code=500, detail="boom")
        return {"iid": iid}

    ticks = iter([0.0, 0.010, 1.0, 1.020, 2.0, 2.005, 3.0, 3.001] + [9.0] * 10)   # 每個請求 (開始, 結束) 秒；之後的請求耗時 0
    store = rm.install(app, store=rm.RequestMetrics(slow_ms=1e9), clock=lambda: next(ticks))
    c = TestClient(app)
    assert c.get("/api/item/a").status_code == 200
    assert c.get("/api/item/b").status_code == 200
    assert c.get("/api/item/bad").status_code == 500
    assert c.get("/nope").status_code == 404
    routes = store.summary()["routes"]
    assert routes["GET /api/item/{iid}"]["count"] == 3          # 不同 iid 算同一條路由
    assert routes["GET /api/item/{iid}"]["errors_5xx"] == 1
    assert routes["GET /api/item/{iid}"]["max_ms"] == 20.0
    assert routes["GET <unmatched>"]["count"] == 1
    body = c.get("/api/metrics").json()                          # 這次請求本身在回應後才記，不在結果裡
    assert "GET /api/item/{iid}" in body["routes"] and body["keep"] == rm.KEEP


def test_metrics_endpoint_includes_stages():
    app = FastAPI()
    stage_store = rm.RequestMetrics(slow_ms=float("inf"))
    stage_store.record("llm_hailo", "LLM", 200, 1234.0)
    rm.install(app, store=rm.RequestMetrics(slow_ms=1e9), stage_store=stage_store)
    body = TestClient(app).get("/api/metrics").json()
    assert body["stages"]["LLM llm_hailo"]["p50_ms"] == 1234.0


def test_llm_activity_records_duration_and_failure(monkeypatch):
    import llm_backend as lb
    store = rm.RequestMetrics(slow_ms=float("inf"))
    monkeypatch.setattr(rm, "stages", store)
    with lb._hailo_activity(True, "hailo"):
        pass
    try:
        with lb._hailo_activity(False, "cpu"):
            raise lb.LLMError("boom")
    except lb.LLMError:
        pass
    with lb._hailo_activity(False):               # 沒給 backend_name：不記
        pass
    routes = store.summary()["routes"]
    assert routes["LLM llm_hailo"]["count"] == 1 and routes["LLM llm_hailo"]["errors_5xx"] == 0
    assert routes["LLM llm_cpu"]["errors_5xx"] == 1
    assert set(routes) == {"LLM llm_hailo", "LLM llm_cpu"}
    assert lb._hailo_inflight == 0


def test_stream_generator_closed_early_is_not_a_failure(monkeypatch):
    import llm_backend as lb
    store = rm.RequestMetrics(slow_ms=float("inf"))
    monkeypatch.setattr(rm, "stages", store)

    def gen():
        with lb._hailo_activity(False, "cpu"):
            yield 1
            yield 2
    g = gen()
    next(g)
    g.close()                                     # 呼叫端拿到要的 token 就停：GeneratorExit
    assert store.summary()["routes"]["LLM llm_cpu"]["errors_5xx"] == 0


def test_unknown_methods_share_one_key():
    app = FastAPI()
    store = rm.install(app, store=rm.RequestMetrics(slow_ms=1e9), stage_store=rm.RequestMetrics(slow_ms=1e9))
    c = TestClient(app)
    for m in ("FOO", "BAR", "XYZZY"):
        c.request(m, "/nope")
    c.get("/nope")
    keys = set(store.summary()["routes"])
    assert keys == {"OTHER <unmatched>", "GET <unmatched>"}
    assert store.summary()["routes"]["OTHER <unmatched>"]["count"] == 3
    assert rm.normalize_method("get") == "GET" and rm.normalize_method("") == "OTHER"


def test_client_disconnect_is_not_5xx():
    import asyncio

    app = FastAPI()
    store = rm.RequestMetrics(slow_ms=1e9)
    rm.install(app, store=store, stage_store=rm.RequestMetrics(slow_ms=1e9))
    timing = [m for m in app.user_middleware if m.kwargs.get("dispatch")][0].kwargs["dispatch"]

    class Req:
        scope = {}
        method = "GET"

    async def gone(_req):
        raise asyncio.CancelledError()

    try:
        asyncio.run(timing(Req(), gone))
    except asyncio.CancelledError:
        pass
    r = store.summary()["routes"]["GET <unmatched>"]
    assert r["count"] == 1 and r["errors_5xx"] == 0


def test_cancelled_llm_call_is_not_a_failure(monkeypatch):
    """11-24 .228：錄音中預先整理遇到 should_stop 會 task.cancel()，CancelledError 不該記成 LLM 失敗。"""
    import asyncio

    import llm_backend as lb
    store = rm.RequestMetrics(slow_ms=float("inf"))
    monkeypatch.setattr(rm, "stages", store)

    async def call():
        async with lb._hailo_activity(True, "hailo"):
            await asyncio.sleep(10)

    async def main():
        t = asyncio.ensure_future(call())
        await asyncio.sleep(0.05)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    asyncio.run(main())
    r = store.summary()["routes"]["LLM llm_hailo"]
    assert r["count"] == 1 and r["errors_5xx"] == 0
