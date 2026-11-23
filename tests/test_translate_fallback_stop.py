"""transcript_translate._translate_flat：兩路都失敗後的保底迴圈要遵守 should_stop。
2026-11-23 localnote@mac（S13 深度審查）：原本保底迴圈不看 should_stop，開始錄音後仍對剩下每一段各送一次 Hailo 請求
（_complete 每次等 POLL_SEC 才取消），而且回傳 stopped=False → SingleJob 記成 done 而不是 stopped，前端不會提示重跑。
"""
import asyncio

import transcript_translate as tt
from llm_backend import LLMError


def _run(monkeypatch, *, stop_after_error):
    state = {"stop": False, "calls": 0}

    async def fake_complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        state["calls"] += 1
        if state["calls"] == 1:
            if stop_after_error:
                state["stop"] = True          # 第一個請求失敗的同時開始錄音
            raise LLMError("hailo down")
        if should_stop():
            return None
        n = prompt.count("\n")
        return "\n".join(f"{k}| translated" for k in range(1, n + 1))

    monkeypatch.setattr(tt, "_complete", fake_complete)
    flat = ["這是第%d句會議內容，需要翻譯成英文。" % i * 6 for i in range(6)]
    res = asyncio.run(tt._translate_flat(flat, "en", None, lambda: state["stop"], use_cpu=False))
    return res, state["calls"]


def test_fallback_respects_stop(monkeypatch):
    res, calls = _run(monkeypatch, stop_after_error=True)
    assert res["chunks"] >= 2
    assert res["stopped"] is True
    assert calls == 1                         # 停止後不再送任何請求


def test_fallback_still_runs_without_stop(monkeypatch):
    res, calls = _run(monkeypatch, stop_after_error=False)
    assert res["stopped"] is False
    assert res["translated_chunks"] == res["chunks"]
