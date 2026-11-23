"""故障注入：LLM 回傳格式錯誤（2026-11-23 localnote@mac，S7）。httpx／requests 換成假的，不連任何 LLM。

找到的問題：
1. Ollama 送出 HTTP 200 之後生成失敗時，串流裡會有一行 {"error": "..."}。原本當成沒有字的 chunk，
   串流安靜結束 → 呼叫端拿到空字串（錯誤被吞掉、也不換下一個後端）。
2. 一行合法 JSON 但不是物件（"oops"、[1]、null）：extract_token 對它 .get() → AttributeError，
   不在 except 清單裡，直接往外拋，只接 LLMError 的呼叫端（潤稿、翻譯）接不到。
同步版 iter_chat_stream／chat_complete 同樣處理。
"""
import asyncio
import json

import httpx
import pytest
import requests

import llm_backend as lb


def _backend(name, is_hailo):
    return lb.LLMBackend(name=name, base_url=f"http://{name}.test", model=f"{name}-model", is_hailo=is_hailo)


H, C = _backend("hailo", True), _backend("cpu", False)


@pytest.fixture
def net(monkeypatch):
    """hailo 回 state['hailo_lines']，cpu 正常回「OK」。"""
    state = {"hailo_lines": [], "hits": []}

    def handler(request):
        host = request.url.host.split(".")[0]
        state["hits"].append(host)
        if host == "hailo":
            body = "\n".join(state["hailo_lines"]) + "\n"
        else:
            body = json.dumps({"message": {"content": "OK"}, "done": True}) + "\n"
        return httpx.Response(200, text=body)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(lb.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(lb, "backends_in_order", lambda *a, **k: [H, C])
    monkeypatch.setattr(lb, "_free_npu_for_llm", lambda: None)
    return state


def _collect(**kw):
    async def run():
        return [(t, b.name) async for t, _d, b in lb.aiter_chat_stream("p", **kw)]
    return asyncio.run(run())


@pytest.mark.parametrize("bad", ['{"error": "model runner has unexpectedly stopped"}', '"oops"', "[1, 2]", "null"])
def test_bad_first_chunk_falls_back_to_next_backend(net, bad):
    net["hailo_lines"] = [bad]
    assert _collect() == [("OK", "cpu")]
    assert net["hits"] == ["hailo", "cpu"]


def test_error_after_tokens_is_raised_not_swallowed(net):
    net["hailo_lines"] = [json.dumps({"message": {"content": "部分"}}), json.dumps({"error": "out of memory"})]

    async def run():
        got = []
        with pytest.raises(lb.LLMError, match="out of memory"):
            async for t, _d, _b in lb.aiter_chat_stream("p"):
                got.append(t)
        return got
    assert asyncio.run(run()) == ["部分"]                    # 已吐字：不換後端（避免重複輸出），但要報錯
    assert net["hits"] == ["hailo"]


def test_all_backends_error_raises_llmerror(net, monkeypatch):
    monkeypatch.setattr(lb, "backends_in_order", lambda *a, **k: [H])
    net["hailo_lines"] = [json.dumps({"error": "no such model"})]
    with pytest.raises(lb.LLMError, match="no such model"):
        _collect()


# ---------------------------------------------------------------- 同步版

class _Resp:
    def __init__(self, lines=None, body=None):
        self.status_code, self._lines, self._body, self.text = 200, lines or [], body, ""

    def iter_lines(self):
        yield from (l.encode() for l in self._lines)

    def json(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def sync_net(monkeypatch):
    monkeypatch.setattr(lb, "backends_in_order", lambda *a, **k: [H, C])
    monkeypatch.setattr(lb, "_free_npu_for_llm", lambda: None)
    monkeypatch.setattr(lb, "shared_group", lambda: None)
    state = {"hailo": None}

    def post(url, json=None, stream=None, timeout=None):
        if "hailo" in url:
            return state["hailo"]
        return _Resp(lines=['{"message": {"content": "OK"}, "done": true}'], body={"message": {"content": "OK"}})
    monkeypatch.setattr(lb.requests, "post", post)
    return state


@pytest.mark.parametrize("bad", ['{"error": "boom"}', '"oops"', "null"])
def test_sync_stream_bad_chunk_falls_back(sync_net, bad):
    sync_net["hailo"] = _Resp(lines=[bad])
    assert [(t, b.name) for t, _d, b in lb.iter_chat_stream("p")] == [("OK", "cpu")]


@pytest.mark.parametrize("body", [{"error": "model not found"}, ["not", "a", "dict"], None])
def test_chat_complete_bad_body_falls_back(sync_net, body):
    sync_net["hailo"] = _Resp(body=body)
    text, backend = lb.chat_complete("p")
    assert (text, backend.name) == ("OK", "cpu")
