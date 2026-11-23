"""transcript_translate._complete：外層被取消時，內層串流 task 也要跟著取消、關掉串流。
2026-11-23 localnote@mac（S16；PC 在 346b611 補 transcript_polish 同一個洞後提醒）：原本外層被 cancel 時
asyncio.wait 丟 CancelledError，內層 consume() 繼續跑，Hailo 串流變孤兒（NPU 一直生成到 num_predict）。
即時翻譯會被取消：meeting_minutes._stop_live_translate 在取消錄音、尾端翻譯逾時（call_later(task.cancel)）時 cancel run()。
"""
import asyncio

import transcript_translate as tt


def test_outer_cancel_also_closes_stream(monkeypatch):
    state = {"closed": False, "tokens": 0}

    async def fake_stream(prompt, **kw):
        try:
            while True:
                await asyncio.sleep(0.05)
                state["tokens"] += 1
                yield "x", False, None
        finally:
            state["closed"] = True

    monkeypatch.setattr(tt, "aiter_chat_stream", fake_stream)

    async def main():
        outer = asyncio.ensure_future(tt._complete("p", "en", 100, hailo_only=True, cpu_first=False,
                                                  should_stop=lambda: False))
        await asyncio.sleep(0.3)
        outer.cancel()
        try:
            await outer
        except asyncio.CancelledError:
            pass
        n = state["tokens"]
        await asyncio.sleep(0.3)
        return n

    n_at_cancel = asyncio.run(main())
    assert state["closed"]
    assert state["tokens"] == n_at_cancel          # 取消後不再收 token
