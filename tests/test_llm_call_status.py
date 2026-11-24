"""N4 審查 206cf8b／8948507（每次 LLM 呼叫記到 /api/metrics 的 stages）與 355eeba（{"error"} 不吞掉）（2026-11-24 localnote@mac）。

找到的問題：
1. chat_complete 的 _hailo_activity 只包住 requests.post；HTTP 500、{"error": ...} 的檢查在 with 外面 → 失敗的呼叫記成成功 (200)。
   async／串流版的檢查都在 with 裡面，記得對。
2. achat_complete 沒有經過 _check_chunk：HTTP 200＋{"error": ...} 回空字串當成功 (不換下一個後端)；
   非物件 JSON ("oops"、null) 在 extract_token 拋 AttributeError，不在退避的 except 清單裡。同步版 chat_complete 沒有這個問題。
不連任何 LLM：requests／httpx 換成假的。
"""
import asyncio
import json

import httpx
import pytest

import llm_backend as lb
import request_metrics as rm


def _backend(name, is_hailo):
    return lb.LLMBackend(name=name, base_url=f"http://{name}.test", model=f"{name}-model", is_hailo=is_hailo)


H, C = _backend("hailo", True), _backend("cpu", False)
OK = json.dumps({"message": {"content": "OK"}, "done": True})


class _Resp:
    def __init__(self, status, body):
        self.status_code, self.text = status, body

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def stages(monkeypatch):
    store = rm.RequestMetrics(slow_ms=float("inf"))
    monkeypatch.setattr(rm, "stages", store)
    monkeypatch.setattr(lb, "backends_in_order", lambda *a, **k: [H, C])
    monkeypatch.setattr(lb, "_free_npu_for_llm", lambda: None)
    return store


@pytest.fixture
def sync_net(monkeypatch):
    state = {"hailo": (200, OK), "hits": []}

    def post(url, json=None, timeout=None, **kw):
        host = url.split("//")[1].split(".")[0]
        state["hits"].append(host)
        return _Resp(*state["hailo"]) if host == "hailo" else _Resp(200, OK)
    monkeypatch.setattr(lb.requests, "post", post)
    return state


@pytest.fixture
def async_net(monkeypatch):
    state = {"hailo": (200, OK), "hits": []}

    def handler(request):
        host = request.url.host.split(".")[0]
        state["hits"].append(host)
        status, body = state["hailo"] if host == "hailo" else (200, OK)
        return httpx.Response(status, text=body)
    real = httpx.AsyncClient
    monkeypatch.setattr(lb.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return state


@pytest.mark.parametrize("status,body", [(500, "internal error"), (200, '{"error": "model runner has unexpectedly stopped"}'),
                                         (200, '"oops"')])
def test_chat_complete_failed_call_counts_as_failure(stages, sync_net, status, body):
    sync_net["hailo"] = (status, body)
    text, backend = lb.chat_complete("p")
    assert (text, backend.name) == ("OK", "cpu") and sync_net["hits"] == ["hailo", "cpu"]
    routes = stages.summary()["routes"]
    assert routes["LLM llm_hailo"]["errors_5xx"] == 1          # 原本 0：失敗記成成功
    assert routes["LLM llm_cpu"]["errors_5xx"] == 0


def test_chat_complete_success_is_not_a_failure(stages, sync_net):
    assert lb.chat_complete("p")[0] == "OK"
    assert stages.summary()["routes"]["LLM llm_hailo"]["errors_5xx"] == 0


@pytest.mark.parametrize("body", ['{"error": "model runner has unexpectedly stopped"}', '"oops"', "null", "[1]"])
def test_achat_complete_bad_body_falls_back(stages, async_net, body):
    async_net["hailo"] = (200, body)
    text, backend = asyncio.run(lb.achat_complete("p", hailo_retries=0))
    assert (text, backend.name) == ("OK", "cpu")                # 原本：{"error"} 回 ("", hailo)；"oops" 拋 AttributeError
    assert async_net["hits"] == ["hailo", "cpu"]
    assert stages.summary()["routes"]["LLM llm_hailo"]["errors_5xx"] == 1


def test_achat_complete_http_error_counts_as_failure(stages, async_net):
    async_net["hailo"] = (500, "boom")
    assert asyncio.run(lb.achat_complete("p", hailo_retries=0))[0] == "OK"
    assert stages.summary()["routes"]["LLM llm_hailo"]["errors_5xx"] == 1
