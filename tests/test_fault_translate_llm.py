"""故障注入：會後翻譯時 LLM 失敗／逾時／串流中斷（2026-11-23 localnote@mac，S7）。
aiter_chat_stream 換成假的，不連 LLM。確認 translate_transcript 不拋例外、不卡住，翻不成的段落保留原文。"""
import asyncio
import re

import pytest

import transcript_translate as tt
from llm_backend import LLMError

TEXT = "說話人1：第一個議題是預算。\n說話人2：預算是八十萬元。\n說話人1：下週三再確認。"


def _fake_stream(behaviour):
    """behaviour(hailo_only, cpu_first) → 'fail'、'interrupt' 或要回的譯文（逐行編號）。"""
    async def stream(prompt, system=None, temperature=0.2, num_predict=200, timeout=90.0, hailo_retries=0,
                     hailo_only=False, cpu_first=False, **kw):
        b = behaviour(hailo_only, cpu_first)
        if b == "fail":
            raise LLMError("all LLM backends failed: ReadTimeout")
        if b == "interrupt":
            yield "1. Partial", False, None
            raise LLMError("stream interrupted: RemoteProtocolError")
        n = sum(1 for line in prompt.splitlines() if re.match(r"^\d+\|", line))   # 提示詞的編號格式「1| …」
        for i in range(1, n + 1):
            yield f"{i}. Translated line {i}.\n", False, None
        yield "", True, None
    return stream


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


def test_all_backends_fail_keeps_source(monkeypatch):
    monkeypatch.setattr(tt, "aiter_chat_stream", _fake_stream(lambda h, c: "fail"))
    res = _run(tt.translate_transcript(TEXT, "en"))
    assert "第一個議題是預算" in res["text"] and "八十萬" in res["text"]     # 全部保留原文
    assert res["translated_chunks"] == 0 and res["stopped"] is False


def test_hailo_fails_cpu_translates(monkeypatch):
    monkeypatch.setattr(tt, "aiter_chat_stream", _fake_stream(lambda h, c: "fail" if h else "ok"))
    res = _run(tt.translate_transcript(TEXT, "en"))
    assert res["translated_chunks"] == res["chunks"] and res["chunks"] >= 1
    assert "第一個議題" not in res["text"]


def test_stream_interrupted_everywhere_keeps_source(monkeypatch):
    monkeypatch.setattr(tt, "aiter_chat_stream", _fake_stream(lambda h, c: "interrupt"))
    res = _run(tt.translate_transcript(TEXT, "en"))
    assert "預算是八十萬元" in res["text"] and res["translated_chunks"] == 0


def test_hailo_only_when_cpu_not_allowed(monkeypatch):
    calls = []

    def behaviour(h, c):
        calls.append((h, c))
        return "fail"
    monkeypatch.setattr(tt, "aiter_chat_stream", _fake_stream(behaviour))
    _run(tt.translate_transcript(TEXT, "en", use_cpu=False))
    assert calls and all(h is True for h, _c in calls)          # 錄音中禁止 CPU：保底也只試 Hailo


def test_bad_target_raises_valueerror():
    with pytest.raises(ValueError):
        _run(tt.translate_transcript(TEXT, "fr"))
