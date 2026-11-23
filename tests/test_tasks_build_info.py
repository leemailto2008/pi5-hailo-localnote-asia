"""tasks.analyze_code_task（RQ 工作；requests 換成假的，不連 Ollama）與 build_info.version。"""
import pytest
import requests

import build_info
import tasks


class _Resp:
    def __init__(self, body=None, status=200):
        self._body, self.status_code = body or {}, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._body


def test_code_review_prompt_and_metrics(monkeypatch):
    seen = {}

    def post(url, json=None, timeout=None):
        seen.update(url=url, payload=json, timeout=timeout)
        return _Resp({"response": "LGTM", "eval_count": 50, "eval_duration": 2_000_000_000})
    monkeypatch.setattr(tasks.requests, "post", post)
    res = tasks.analyze_code_task({"code": "print(1)", "language": "python", "filename": "a.py",
                                   "model": "m", "temperature": "0.5", "max_tokens": "64"})
    assert res["status"] == "completed" and res["result"] == "LGTM"
    assert res["total_tokens"] == 50 and res["eval_duration_s"] == 2.0 and res["eval_tps"] == 25.0
    p = seen["payload"]
    assert seen["url"].endswith("/api/generate") and p["model"] == "m" and p["stream"] is False
    assert p["options"] == {"temperature": 0.5, "num_predict": 64}
    assert "```python\nprint(1)\n```" in p["prompt"] and "`a.py`" in p["prompt"]


def test_question_without_code(monkeypatch):
    seen = {}
    monkeypatch.setattr(tasks.requests, "post", lambda url, json=None, timeout=None: seen.update(p=json) or _Resp({"response": "A"}))
    res = tasks.analyze_code_task({"prompt": "什麼是 GIL？", "code": "   "})
    assert res["status"] == "completed"
    assert "### Question:\n什麼是 GIL？" in seen["p"]["prompt"] and "```" not in seen["p"]["prompt"]


def test_missing_eval_duration_uses_wall_clock(monkeypatch):
    monkeypatch.setattr(tasks.requests, "post", lambda *a, **k: _Resp({"response": "x", "eval_count": 10, "eval_duration": 0}))
    res = tasks.analyze_code_task({"code": "x"})
    assert res["status"] == "completed" and res["eval_tps"] >= 0


@pytest.mark.parametrize("exc", [requests.ConnectionError("refused"), requests.HTTPError("500")])
def test_failure_is_reported_not_raised(monkeypatch, exc):
    def post(*a, **k):
        if isinstance(exc, requests.HTTPError):
            return _Resp(status=500)
        raise exc
    monkeypatch.setattr(tasks.requests, "post", post)
    res = tasks.analyze_code_task({"code": "x", "model": "m"})
    assert res["status"] != "completed"
    assert res.get("model") == "m"


def test_build_info_version(monkeypatch):
    monkeypatch.setattr(build_info, "COMMIT", "$Format:%h$")
    assert build_info.version() == "dev"
    monkeypatch.setattr(build_info, "COMMIT", "abc1234")
    monkeypatch.setattr(build_info, "COMMIT_DATE", "2026-11-23 18:00:00 +0800")
    assert build_info.version() == "abc1234 (2026-11-23 18:00:00 +0800)"
