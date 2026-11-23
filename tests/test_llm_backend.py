"""llm_backend 的同步路徑（requests）：hailo 跳脫、payload、健康檢查快取、後端順序、退避、串流中斷。
requests.get／post 全部換成假的，不連任何 LLM 服務。async（httpx）路徑在 test_llm_stream.py。"""
import json

import pytest
import requests

import llm_backend as lb


# ---------------------------------------------------------------- 純函式

@pytest.mark.parametrize("src,expect", [
    ("a\nb", "a\\nb"),
    ("a\r\nb\rc", "a\\nb\\nc"),
    ("tab\there", "tab\\there"),
    ("C:\\path", "C:\\\\path"),
    ("bell\x07 nul\x00 del\x7f", "bell nul del"),
    ('quote " ok 中文', 'quote " ok 中文'),
])
def test_sanitize_for_hailo(src, expect):
    assert lb._sanitize_for_hailo(src) == expect


def test_sanitize_backslash_before_newline_is_not_double_escaped():
    # 先跳脫反斜線再轉換行：產生的 \n 不能又被變成 \\n
    assert lb._sanitize_for_hailo("x\\\ny") == "x\\\\\\ny"


def test_build_messages_and_extract_token():
    assert lb.build_messages("hi") == [{"role": "user", "content": "hi"}]
    assert lb.build_messages("hi", "sys")[0] == {"role": "system", "content": "sys"}
    assert lb.extract_token({"message": {"content": "A"}}) == "A"
    assert lb.extract_token({"message": {"content": None}}) == ""
    assert lb.extract_token({"response": "B"}) == "B"
    assert lb.extract_token({}) == ""


def test_describe():
    assert lb._describe(None) == "unknown error"
    assert lb._describe(ValueError("bad")) == "ValueError: bad"
    assert lb._describe(TimeoutError()) == "TimeoutError"


def test_backend_label_and_url():
    b = lb.LLMBackend("cpu", "http://h:1", "m", False)
    assert b.chat_url == "http://h:1/api/chat" and b.label == "CPU Ollama m"
    assert lb.LLMBackend("hailo", "http://h:2", "q", True).label == "Hailo-10H NPU q"


def test_cpu_payload(monkeypatch):
    p = lb.CPU_BACKEND.build_chat_payload([{"role": "user", "content": "a\nb"}], stream=True, top_p=0.9)
    assert p["messages"][0]["content"] == "a\nb"           # CPU 不跳脫
    assert p["keep_alive"] == 0 and p["stream"] is True
    assert p["options"] == {"temperature": 0.2, "num_predict": 200, "top_p": 0.9, "num_thread": 4}
    assert "think" not in p


def test_hailo_payload_exclusive_and_shared(monkeypatch):
    monkeypatch.setattr(lb, "shared_group", lambda: None)
    p = lb.HAILO_BACKEND.build_chat_payload([{"role": "user", "content": "a\nb"}], stream=False)
    assert p["messages"][0]["content"] == "a\\nb" and p["think"] is False
    assert p["keep_alive"] == lb.HAILO_KEEP_ALIVE and isinstance(p["keep_alive"], int)
    assert "num_thread" not in p["options"]
    p = lb.HAILO_BACKEND.build_chat_payload([{"role": "user", "content": "x"}], stream=False, hailo_keep_alive="30")
    assert p["keep_alive"] == 30                               # 字串會轉成整數（hailo-ollama 只收整數）
    monkeypatch.setattr(lb, "shared_group", lambda: "G")
    p = lb.HAILO_BACKEND.build_chat_payload([{"role": "user", "content": "x"}], stream=False, hailo_keep_alive=5)
    assert p["keep_alive"] == lb.SHARED_KEEP_ALIVE


def test_hailo_activity_counter():
    lb._hailo_last_activity = 0.0
    assert lb.hailo_idle_seconds() is None
    with lb._hailo_activity(True):
        assert lb.hailo_idle_seconds() == 0.0
    idle = lb.hailo_idle_seconds()
    assert idle is not None and 0 <= idle < 5
    with lb._hailo_activity(False):
        assert lb.hailo_idle_seconds() != 0.0
    with pytest.raises(RuntimeError):
        with lb._hailo_activity(True):
            raise RuntimeError("x")
    assert lb._hailo_inflight == 0                             # 例外時也要減回來


# ---------------------------------------------------------------- 健康檢查

class _Resp:
    def __init__(self, status=200, body=None, lines=None, text=""):
        self.status_code, self._body, self._lines, self.text = status, body, lines or [], text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    def iter_lines(self):
        for ln in self._lines:
            if isinstance(ln, Exception):
                raise ln
            yield ln

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    lb._health_cache.clear()
    monkeypatch.setattr(lb, "_free_npu_for_llm", lambda: None)
    monkeypatch.setattr(lb, "shared_group", lambda: None)
    yield
    lb._health_cache.clear()


def test_probe_backend(monkeypatch):
    b = lb.LLMBackend("cpu", "http://h", "qwen2.5:3b-opt", False)
    monkeypatch.setattr(lb.requests, "get", lambda url, timeout: _Resp(body={"models": [{"name": "qwen2.5:3b-opt"}]}))
    assert lb._probe_backend(b) is True
    monkeypatch.setattr(lb.requests, "get", lambda url, timeout: _Resp(body={"models": [{"name": "other"}]}))
    assert lb._probe_backend(b) is False
    monkeypatch.setattr(lb.requests, "get", lambda url, timeout: _Resp(status=500))
    assert lb._probe_backend(b) is False
    monkeypatch.setattr(lb.requests, "get", lambda url, timeout: _Resp(body=ValueError("not json")))
    assert lb._probe_backend(b) is False

    def boom(url, timeout):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(lb.requests, "get", boom)
    assert lb._probe_backend(b) is False


def test_health_cache_ttl(monkeypatch):
    n = {"probe": 0}
    monkeypatch.setattr(lb, "_probe_backend", lambda b: n.__setitem__("probe", n["probe"] + 1) or True)
    t = {"now": 1000.0}
    monkeypatch.setattr(lb.time, "monotonic", lambda: t["now"])
    assert lb.is_backend_healthy(lb.CPU_BACKEND) and n["probe"] == 1
    t["now"] += lb._HEALTH_TTL_SEC - 1
    assert lb.is_backend_healthy(lb.CPU_BACKEND) and n["probe"] == 1      # 快取內
    assert lb.is_backend_healthy(lb.CPU_BACKEND, force_refresh=True) and n["probe"] == 2
    t["now"] += lb._HEALTH_TTL_SEC + 1
    lb.is_backend_healthy(lb.CPU_BACKEND)
    assert n["probe"] == 3


@pytest.mark.parametrize("pref,healthy,expect,expect_cpu_first", [
    ("hailo", True, ["hailo", "cpu", "cpu"], ["cpu", "cpu", "hailo"]),
    ("hailo", False, ["cpu", "cpu"], ["cpu", "cpu"]),
    ("cpu", True, ["cpu", "cpu"], ["cpu", "cpu"]),
])
def test_backend_order(monkeypatch, pref, healthy, expect, expect_cpu_first):
    monkeypatch.setattr(lb, "PREFERRED_BACKEND", pref)
    monkeypatch.setattr(lb, "is_backend_healthy", lambda b, force_refresh=False: healthy)
    assert [b.name for b in lb.backends_in_order()] == expect
    assert [b.name for b in lb.cpu_first_backends()] == expect_cpu_first
    assert lb.get_backend().name == expect[0]


# ---------------------------------------------------------------- chat_complete／iter_chat_stream

def _order(monkeypatch, *backends):
    monkeypatch.setattr(lb, "backends_in_order", lambda force_refresh=False: list(backends))


H = lb.LLMBackend("hailo", "http://hailo.test", "hm", True)
C = lb.LLMBackend("cpu", "http://cpu.test", "cm", False)


def test_chat_complete_falls_back(monkeypatch):
    _order(monkeypatch, H, C)
    hits = []

    def post(url, json=None, timeout=None):
        hits.append(url)
        if "hailo" in url:
            return _Resp(status=500, text="Failed to render prompt")
        return _Resp(body={"message": {"content": "  ok  "}})
    monkeypatch.setattr(lb.requests, "post", post)
    text, backend = lb.chat_complete("p", system="s")
    assert text == "ok" and backend is C
    assert hits == ["http://hailo.test/api/chat", "http://cpu.test/api/chat"]
    assert lb._hailo_inflight == 0


def test_chat_complete_frees_npu_only_for_hailo(monkeypatch):
    _order(monkeypatch, H, C)
    freed = []
    monkeypatch.setattr(lb, "_free_npu_for_llm", lambda: freed.append(1))
    monkeypatch.setattr(lb.requests, "post", lambda url, json=None, timeout=None: _Resp(body={"message": {"content": "x"}}))
    lb.chat_complete("p")
    assert freed == [1]


def test_chat_complete_all_fail(monkeypatch):
    _order(monkeypatch, H, C)

    def post(url, json=None, timeout=None):
        if "hailo" in url:
            raise requests.ReadTimeout()
        return _Resp(body=ValueError("bad json"))
    monkeypatch.setattr(lb.requests, "post", post)
    with pytest.raises(lb.LLMError, match="all LLM backends failed: ValueError: bad json"):
        lb.chat_complete("p")


def _lines(*chunks):
    return [json.dumps(c).encode() for c in chunks]


def test_stream_yields_tokens_until_done(monkeypatch):
    _order(monkeypatch, C)
    seen_kw = {}

    def post(url, json=None, stream=None, timeout=None):
        seen_kw.update(stream=stream, payload=json)
        return _Resp(lines=_lines({"message": {"content": "A"}}, {"message": {"content": "B"}},
                                  {"message": {"content": ""}, "done": True}, {"message": {"content": "after"}}) + [b""])
    monkeypatch.setattr(lb.requests, "post", post)
    out = [(t, d) for t, d, _ in lb.iter_chat_stream("p", top_p=0.5)]
    assert out == [("A", False), ("B", False), ("", True)]
    assert seen_kw["stream"] is True and seen_kw["payload"]["options"]["top_p"] == 0.5


def test_stream_falls_back_before_first_token(monkeypatch):
    _order(monkeypatch, H, C)

    def post(url, json=None, stream=None, timeout=None):
        if "hailo" in url:
            return _Resp(lines=[requests.ConnectionError("reset")])
        return _Resp(lines=_lines({"message": {"content": "Z"}, "done": True}))
    monkeypatch.setattr(lb.requests, "post", post)
    assert [(t, b.name) for t, _, b in lb.iter_chat_stream("p")] == [("Z", "cpu")]


def test_stream_interrupted_after_token_does_not_fall_back(monkeypatch):
    _order(monkeypatch, H, C)
    hits = []

    def post(url, json=None, stream=None, timeout=None):
        hits.append(url)
        return _Resp(lines=_lines({"message": {"content": "A"}}) + [requests.ConnectionError("reset")])
    monkeypatch.setattr(lb.requests, "post", post)
    got = []
    with pytest.raises(lb.LLMError, match="stream interrupted"):
        for t, _, _ in lb.iter_chat_stream("p"):
            got.append(t)
    assert got == ["A"] and len(hits) == 1                     # 已經吐字就不能換後端重來（會重複輸出）
    assert lb._hailo_inflight == 0


def test_stream_http_error_and_all_fail(monkeypatch):
    _order(monkeypatch, C)
    monkeypatch.setattr(lb.requests, "post", lambda url, json=None, stream=None, timeout=None: _Resp(status=503, text="busy"))
    with pytest.raises(lb.LLMError, match="all LLM backends failed: LLMError: CPU Ollama cm HTTP 503: busy"):
        list(lb.iter_chat_stream("p"))


def test_stream_ends_without_done_flag(monkeypatch):
    _order(monkeypatch, C, C)
    hits = []

    def post(url, json=None, stream=None, timeout=None):
        hits.append(url)
        return _Resp(lines=_lines({"message": {"content": "A"}}))
    monkeypatch.setattr(lb.requests, "post", post)
    assert [t for t, _, _ in lb.iter_chat_stream("p")] == ["A"]
    assert len(hits) == 1


def test_prewarm(monkeypatch):
    monkeypatch.setattr(lb, "chat_complete", lambda *a, **k: ("hi", C))
    assert lb.prewarm() is C

    def fail(*a, **k):
        raise lb.LLMError("x")
    monkeypatch.setattr(lb, "chat_complete", fail)
    assert lb.prewarm() is None


def test_prewarm_hailo(monkeypatch):
    calls = {"health": 0}

    def healthy(b, force_refresh=False):
        calls["health"] += 1
        return calls["health"] >= 2
    monkeypatch.setattr(lb, "is_backend_healthy", healthy)
    monkeypatch.setattr(lb.time, "sleep", lambda s: None)
    posted = []
    monkeypatch.setattr(lb.requests, "post", lambda url, json=None, timeout=None: posted.append(json) or _Resp(status=200))
    assert lb.prewarm_hailo(wait_ready_sec=30) is True
    assert posted[0]["options"]["num_predict"] == 1 and posted[0]["model"] == lb.HAILO_BACKEND.model

    monkeypatch.setattr(lb, "is_backend_healthy", lambda b, force_refresh=False: False)
    assert lb.prewarm_hailo(wait_ready_sec=0) is False
