"""AI_HAT_plus/hailo_engine/whisper_adapter 與 hailo_whisper/benchmark 的離線部分。
faster_whisper／hailo_platform 換成假的模組，不需要模型或 Hailo 硬體。

注意：whisper_adapter.CPUWhisperEngine 以 "".join 串接分段，英文會黏在一起（S4 報告待決，由 PC 本尊決定修或刪，
這裡不測英文串接、也不改它）。
"""
import os
import sys
import threading
import types

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "AI_HAT_plus"))
sys.path.insert(0, ROOT)

from hailo_engine import whisper_adapter as wa  # noqa: E402


def _seg(text, start, end):
    return types.SimpleNamespace(text=text, start=start, end=end)


@pytest.fixture
def fake_fw(monkeypatch):
    fw = types.ModuleType("faster_whisper")
    state = {"segments": [], "made": [], "kw": None}

    class WhisperModel:
        def __init__(self, size, **kw):
            state["made"].append((size, kw))

        def transcribe(self, audio, **kw):
            state["kw"] = kw
            return iter(state["segments"]), types.SimpleNamespace(duration=10.0, language="zh")
    fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    return state


def test_cpu_engine_paragraphs_by_pause_and_length(fake_fw):
    fake_fw["segments"] = [
        _seg("第一句。", 0.0, 1.0), _seg("緊接著。", 1.1, 2.0),       # 停頓 0.1 s：同一段
        _seg("停了很久", 3.0, 4.0),                                  # 停頓 1.0 s ≥ 0.45：新段
        _seg("  ", 4.0, 4.1),                                       # 空白分段略過
        _seg("短停頓但前句沒標點", 4.3, 5.0),                        # 停頓 0.2 s、前句無標點、未滿 45 字：同段
    ]
    e = wa.CPUWhisperEngine(model_size="tiny")
    r = e.transcribe(np.zeros(16000, np.float32), language="zh")
    assert r["text"] == "第一句。緊接著。\n\n停了很久短停頓但前句沒標點"
    assert [s["text"] for s in r["segments"]] == ["第一句。", "緊接著。", "停了很久", "短停頓但前句沒標點"]
    assert r["audio_duration_sec"] == 10.0 and r["rtf"] >= 0 and r["engine"] == e.get_engine_type()
    assert fake_fw["made"] == [("tiny", {"device": "cpu", "compute_type": "int8", "cpu_threads": 4})]
    assert fake_fw["kw"]["language"] == "zh" and fake_fw["kw"]["vad_filter"] is True
    assert e.is_ready() is True


def test_cpu_engine_breaks_long_paragraph(fake_fw):
    fake_fw["segments"] = [_seg("字" * 80, 0.0, 5.0), _seg("下一段", 5.0, 6.0)]   # 段落已 ≥ 75 字：新段
    assert wa.CPUWhisperEngine().transcribe(np.zeros(10, np.float32))["text"] == "字" * 80 + "\n\n下一段"


def test_cpu_engine_cancellation_and_callbacks(fake_fw):
    stop = threading.Event()
    calls = []

    def cb(preview, seg, done):
        calls.append((preview, seg, done))
        if seg == "第二句":
            stop.set()
        if seg == "第一句":
            raise RuntimeError("ws gone")                           # 回呼出錯不影響轉錄
    fake_fw["segments"] = [_seg("第一句", 0, 1), _seg("第二句", 1, 2), _seg("不該出現", 2, 3)]
    r = wa.CPUWhisperEngine().transcribe(np.zeros(10, np.float32), cancellation_event=stop, on_segment_callback=cb)
    assert r["text"] == "第一句第二句"
    assert calls[-1] == ("第一句第二句", "", True) and len(calls) == 3


def test_load_audio_pcm_falls_back_to_ffmpeg(monkeypatch):
    import voice_memory
    monkeypatch.setattr(voice_memory, "audio_to_pcm_array", lambda p: None)
    monkeypatch.setattr("subprocess.check_output", lambda cmd, **kw: np.array([16384, -16384], np.int16).tobytes())
    assert wa.load_audio_pcm("x.ogg").tolist() == [0.5, -0.5]
    monkeypatch.setattr(voice_memory, "audio_to_pcm_array", lambda p: np.ones(3, np.float32))
    assert wa.load_audio_pcm("x.ogg").tolist() == [1.0, 1.0, 1.0]


def test_hailo8_engine_without_hef_falls_back_to_cpu(fake_fw, tmp_path):
    e = wa.HailoWhisperEngine(hef_path=str(tmp_path / "none.hef"))
    assert e.is_ready() is False and "Hailo-8" in e.get_engine_type()
    fake_fw["segments"] = [_seg("好", 0, 1)]
    r = e.transcribe(np.zeros(10, np.float32))                     # 沒有 HEF：改用 CPU
    assert r["text"] == "好" and r["engine"].startswith("ARM")


def test_hailo8_engine_hef_but_no_runtime(fake_fw, tmp_path, monkeypatch):
    hef = tmp_path / "a.hef"
    hef.write_bytes(b"x")
    monkeypatch.setitem(sys.modules, "hailo_platform", None)       # import 失敗
    assert wa.HailoWhisperEngine(hef_path=str(hef)).is_ready() is False


def test_factory(monkeypatch):
    import hailo_engine.device_manager as dm
    monkeypatch.setattr(dm, "is_hailo_available", lambda: False)
    assert isinstance(wa.get_whisper_engine(), wa.CPUWhisperEngine)
    monkeypatch.setattr(dm, "is_hailo_available", lambda: True)

    class NotReady:
        def __init__(self, *a, **k):
            pass

        def is_ready(self):
            return False
    monkeypatch.setattr(wa, "HailoWhisperEngine", NotReady)
    assert isinstance(wa.get_whisper_engine(model_size="tiny"), wa.CPUWhisperEngine)
    assert isinstance(wa.get_whisper_engine(auto_detect=False), wa.CPUWhisperEngine)


def test_benchmark(monkeypatch, capsys):
    from hailo_whisper import benchmark as bm
    st = bm.benchmark_audio_processor(iterations=2)
    assert st["iterations"] == 2 and st["mean_latency_ms"] > 0 and st["p95_latency_ms"] >= st["mean_latency_ms"] * 0.5
    monkeypatch.setattr(bm, "benchmark_audio_processor", lambda: {"iterations": 1, "mean_latency_ms": 1.0, "p95_latency_ms": 1.0})
    monkeypatch.setattr(bm, "get_whisper_engine", lambda preferred_backend: types.SimpleNamespace(is_hardware_accelerated=lambda: False))
    bm.main()
    out = capsys.readouterr().out
    assert "Mean Latency: 1.0 ms" in out and "Hardware Accelerated: False" in out
