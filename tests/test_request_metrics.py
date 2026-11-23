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
