"""request_metrics.py — Task 28：API 回應時間的 P50／P95／P99 與慢請求的結構化 (JSON) 日誌。

- 每條路由 (用 FastAPI 的路由樣板，例如 /api/feedback/{rid}，不是實際網址) 在記憶體保留最近 KEEP 筆耗時，不寫磁碟。
- GET /api/metrics 回傳各路由的次數、p50／p95／p99／最大值 (毫秒)。
- 超過 SLOW_MS 的請求寫一行 JSON 到 log (logger "request_metrics")，journalctl 撈出來就能統計。
- 每個請求只多一次 time.perf_counter() 與一次 deque.append，不做推論，錄音中照常記 (CLAUDE.md 重點一)。
"""

import json
import logging
import math
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

KEEP = 500          # 每條路由保留最近幾筆
SLOW_MS = 2000.0    # 超過這個毫秒數寫一行 JSON log

_log = logging.getLogger("request_metrics")


def percentile(values: List[float], q: float) -> Optional[float]:
    """最近排名法 (nearest-rank) 的百分位數；沒有資料回傳 None。q 介於 0–100。"""
    if not values:
        return None
    s = sorted(values)
    k = max(1, math.ceil(q / 100.0 * len(s)))
    return s[min(k, len(s)) - 1]


class RequestMetrics:
    def __init__(self, keep: int = KEEP, slow_ms: float = SLOW_MS):
        self.keep = keep
        self.slow_ms = slow_ms
        self._lock = threading.Lock()
        self._durations: Dict[str, Deque[float]] = {}
        self._counts: Dict[str, int] = {}
        self._errors: Dict[str, int] = {}

    def record(self, route: str, method: str, status: int, ms: float) -> None:
        key = f"{method} {route}"
        with self._lock:
            self._durations.setdefault(key, deque(maxlen=self.keep)).append(ms)
            self._counts[key] = self._counts.get(key, 0) + 1
            if status >= 500:
                self._errors[key] = self._errors.get(key, 0) + 1
        if ms >= self.slow_ms:
            _log.warning(json.dumps({"event": "slow_request", "method": method, "route": route,
                                     "status": status, "ms": round(ms, 1)}, ensure_ascii=False))

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            items = {k: list(v) for k, v in self._durations.items()}
            counts, errors = dict(self._counts), dict(self._errors)
        routes = {}
        for key, vals in sorted(items.items()):
            routes[key] = {"count": counts.get(key, 0), "errors_5xx": errors.get(key, 0), "window": len(vals),
                           "p50_ms": _round(percentile(vals, 50)), "p95_ms": _round(percentile(vals, 95)),
                           "p99_ms": _round(percentile(vals, 99)), "max_ms": _round(max(vals) if vals else None)}
        return {"keep": self.keep, "slow_ms": self.slow_ms, "routes": routes}

    def reset(self) -> None:
        with self._lock:
            self._durations.clear()
            self._counts.clear()
            self._errors.clear()


def _round(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 1)


def route_template(scope: Dict[str, Any]) -> str:
    """FastAPI 比對到的路由樣板 (/api/feedback/{rid})；沒比對到 (404、靜態檔) 用 '<unmatched>'，避免每個網址各佔一格。"""
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if path else "<unmatched>"


metrics = RequestMetrics()
# 非 HTTP 的處理階段 (目前：每次 LLM 呼叫，key「LLM llm_hailo」／「LLM llm_cpu」，含串流生成全程；errors_5xx＝呼叫失敗)。
# 不寫慢請求 log：一段紀要本來就要數十秒。
stages = RequestMetrics(slow_ms=float("inf"))


def install(app: Any, store: Optional[RequestMetrics] = None, clock: Callable[[], float] = time.perf_counter,
            stage_store: Optional[RequestMetrics] = None) -> RequestMetrics:
    """把計時中介層與 GET /api/metrics 掛到 FastAPI app 上，回傳使用中的 RequestMetrics。"""
    store = store or metrics
    stage_store = stage_store or stages

    @app.middleware("http")
    async def _timing(request, call_next):
        t0 = clock()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            store.record(route_template(request.scope), request.method, status, (clock() - t0) * 1000.0)

    @app.get("/api/metrics", tags=["System"])
    def get_request_metrics() -> Dict[str, Any]:
        """各 API 路由的請求次數與耗時百分位數 (毫秒)，最近 KEEP 筆；stages＝LLM 等非 HTTP 階段。"""
        out = store.summary()
        out["stages"] = stage_store.summary()["routes"]
        return out

    return store
