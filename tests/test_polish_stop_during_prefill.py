"""transcript_polish._complete：模型還在預填（還沒有 token）時開始錄音，也要在 POLL_SEC 內關掉串流。
2026-11-23 localnote@mac（S14 深度審查）：原本只在收到 token 時檢查 should_stop。fix 預設走 CPU qwen2.5:3b，
預填一段約 40 s 沒有 token（transcript_translate._complete 的註解），這段期間開始錄音，CPU 推論會一直跑到第一個 token，
違反 CLAUDE.md 重點一（錄音中禁止 CPU 推論）。transcript_translate._complete 已經用每 POLL_SEC 輪詢解決同一個問題。
"""
import asyncio
import time
import types

import transcript_polish as tp

PREFILL_S = 1.5


def _fake_stream(state):
    async def gen(prompt, **kw):
        try:
            await asyncio.sleep(PREFILL_S)          # 預填：沒有 token
            for tok in ("校", "對", "後"):
                yield tok, False, types.SimpleNamespace(label="cpu")
        finally:
            state["closed"] = True
    return gen


def _run(monkeypatch, stop_at):
    state = {"closed": False}
    monkeypatch.setattr(tp, "aiter_chat_stream", _fake_stream(state))
    t0 = time.monotonic()
    stats = {}
    out = asyncio.run(tp._complete("fix", "p", "s", 0.0, 128, stats, lambda: time.monotonic() - t0 >= stop_at))
    return out, time.monotonic() - t0, state


def test_stop_during_prefill_closes_stream_quickly(monkeypatch):
    out, elapsed, state = _run(monkeypatch, stop_at=0.1)
    assert out is None
    assert elapsed < 0.1 + tp.POLL_SEC + 0.4, elapsed     # 原本要等到第一個 token（1.5 s）
    assert state["closed"]


def test_no_stop_returns_full_output(monkeypatch):
    out, _elapsed, state = _run(monkeypatch, stop_at=999)
    assert out == "校對後" and state["closed"]


def test_stop_during_generation_still_returns_none(monkeypatch):
    out, _elapsed, _state = _run(monkeypatch, stop_at=PREFILL_S - 0.05)
    assert out is None
