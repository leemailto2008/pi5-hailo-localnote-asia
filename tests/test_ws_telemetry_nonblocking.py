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


def test_bt_status_refresh_is_serialized(monkeypatch):
    """11-24 Mac N4：get_bt_status 從 to_thread 與 threadpool 同時被叫時，同時只有一個執行緒去跑 bluetoothctl。"""
    import threading
    import voice_streaming
    monkeypatch.setattr(voice_streaming, "is_any_recording_active", lambda: False)
    state = {"now": 0, "max": 0}
    guard = threading.Lock()

    def slow_impl():
        with guard:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.2)
        with guard:
            state["now"] -= 1
        return {"connected": False}
    monkeypatch.setattr(main_mod, "_get_bt_status_impl", slow_impl)
    ts = [threading.Thread(target=main_mod.get_bt_status) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert state["max"] == 1


def test_bt_status_while_recording_returns_cache_without_lock(monkeypatch):
    import voice_streaming
    monkeypatch.setattr(voice_streaming, "is_any_recording_active", lambda: True)
    monkeypatch.setattr(main_mod, "_last_bt_status_cache", {"connected": True, "cached": True})
    monkeypatch.setattr(main_mod, "_get_bt_status_impl", lambda: (_ for _ in ()).throw(AssertionError("不該刷新")))
    assert main_mod._bt_status_lock.acquire(timeout=1)       # 鎖被別人拿著也不等
    try:
        assert main_mod.get_bt_status() == {"connected": True, "cached": True}
    finally:
        main_mod._bt_status_lock.release()
