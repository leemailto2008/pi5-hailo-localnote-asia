"""main.ws_telemetry_loop：get_bt_status 會同步跑 bluetoothctl（沒在錄音、快取 3 s 過期時），要放執行緒，不能卡住 event loop。
2026-11-23 localnote@pc：照 S17（llm_backend 健康檢查）的思路審 async 路徑找到；網頁開著時每 ~3 s 卡一次，SSE／API 都跟著頓。
"""
import asyncio
import os
import time

os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")

import main as main_mod  # noqa: E402
from ws_manager import ws_manager  # noqa: E402

BLOCK_S = 0.8


def test_bt_status_runs_off_the_event_loop(monkeypatch):
    def slow_bt():
        time.sleep(BLOCK_S)              # 模擬 bluetoothctl 子行程
        return {"connected": False, "connected_name": ""}

    async def no_broadcast(*_a, **_k):
        return None

    monkeypatch.setattr(main_mod, "get_bt_status", slow_bt)
    monkeypatch.setattr(main_mod, "get_system_telemetry_payload", lambda: {})
    monkeypatch.setattr(ws_manager, "broadcast", no_broadcast)
    monkeypatch.setattr(ws_manager, "active_connections", {object()})

    async def run():
        loop_task = asyncio.ensure_future(main_mod.ws_telemetry_loop())
        worst, last = 0.0, time.monotonic()
        end = last + 1.5 + BLOCK_S + 0.6     # 第一次 1.5 s sleep 之後會呼叫一次 get_bt_status
        while time.monotonic() < end:
            await asyncio.sleep(0.02)
            now = time.monotonic()
            worst, last = max(worst, now - last), now
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        return worst
    worst = asyncio.run(run())
    assert worst < BLOCK_S / 2, f"event loop blocked {worst:.2f} s"


def test_tts_endpoint_runs_off_the_event_loop(monkeypatch, tmp_path):
    import voice_pipeline as vp

    def slow_tts(text, out, voice="x"):
        time.sleep(BLOCK_S)              # 模擬 gTTS 網路請求＋ffmpeg 轉檔
        with open(out, "wb") as f:
            f.write(b"ogg")
        return True

    monkeypatch.setattr(vp, "text_to_speech", slow_tts)
    monkeypatch.setattr(main_mod, "AUDIO_CACHE_DIR", str(tmp_path))

    async def run():
        task = asyncio.ensure_future(main_mod.text_to_speech_endpoint(
            main_mod.VoiceTTSRequest(text="你好", voice="zh-TW-HsiaoChenNeural", play_on_speaker=False)))
        worst, last = 0.0, time.monotonic()
        while not task.done():
            await asyncio.sleep(0.02)
            now = time.monotonic()
            worst, last = max(worst, now - last), now
        return worst, task.result()
    worst, res = asyncio.run(run())
    assert res.get("status") == "success"
    assert worst < BLOCK_S / 2, f"event loop blocked {worst:.2f} s"
