# -*- coding: utf-8 -*-
"""網頁顯示的 ASR／VAD 組合 (2026-11-11 使用者要求：每一區都要標出實際用了哪個 ASR、串了什麼 VAD)。"""
import sys
import types

import meeting_minutes as mm
import refine_transcript as rt
import voice_pipeline as vp


def test_stt_combo_single_engine_and_slicing():
    combo = mm.SttCombo(slicing=mm.live_slicing_label(8.0))
    for _ in range(3):
        combo.add({"engine": "Hailo-10H Whisper-Small（NPU）", "vad": "Silero VAD 語音閘門", "post": "OpenCC s2twp"})
    d = combo.describe()
    assert d["stt_engine"] == "Hailo-10H Whisper-Small（NPU）"
    assert d["stt_vad"].startswith("Silero VAD 語音閘門；停頓處切片 4–9.5 秒")
    assert d["stt_post"] == "OpenCC s2twp"


def test_stt_combo_lists_counts_when_engines_mixed():
    combo = mm.SttCombo()
    combo.add({"engine": "Hailo-10H Whisper-Small（NPU）"})
    combo.add({"engine": "Hailo-10H Whisper-Small（NPU）"})
    combo.add({"engine": "faster-whisper small int8（CPU，beam 1）"})
    combo.add({})
    assert combo.describe()["stt_engine"] == "Hailo-10H Whisper-Small（NPU） 2 段、faster-whisper small int8（CPU，beam 1） 1 段"


def test_slice_bounds_match_recorder_formula():
    assert vp.slice_bounds(8.0) == (4.0, 9.5)
    assert vp.slice_bounds(5.0) == (3.0, 6.5)
    assert vp.slice_bounds(8.0, first=True) == (5.0, 7.0)       # 第一片 5–7 s：首字不必等 9.5 s 緩衝
    assert vp.slice_bounds(9.0, first=True) == (5.0, 7.0)
    assert vp.slice_bounds(3.0, first=True) == (3.0, 4.5)       # 本來就比第一片上限短：不變


def test_speech_to_text_reports_hailo_engine(monkeypatch):
    class FakeWorker:
        def transcribe(self, audio, language=None):
            return {"text": "大家好", "model": "Whisper-Small", "vad": "Silero VAD 語音閘門"}

    monkeypatch.setitem(sys.modules, "stt_worker", types.SimpleNamespace(stt_worker=FakeWorker()))
    info = {}
    import numpy as np
    assert vp.speech_to_text(np.zeros(16000, dtype=np.float32), info_out=info) == "大家好"
    assert info == {"engine": "Hailo-10H Whisper-Small（NPU）", "vad": "Silero VAD 語音閘門", "post": vp.HAILO_POST_LABEL}


def test_refine_labels_follow_module_settings(monkeypatch):
    labels = rt.pipeline_labels()
    assert labels["asr"].startswith("SenseVoiceSmall int8")
    assert f"最短靜音 {rt.VAD_MIN_SILENCE_S:g} s" in labels["vad"]
    assert "CAM++ 逐句分群" in labels["diarize"]
    monkeypatch.setattr(rt, "DIARIZE_METHOD", "pyannote")
    assert rt.pipeline_labels()["diarize"].startswith("pyannote-3.0")


def test_hailo_vad_label_reports_disabled_gate(monkeypatch):
    from hailo_whisper import engine
    monkeypatch.setattr(engine, "WHISPER_VAD", False)
    assert "關閉" in engine.vad_label()


def _slice(peak_db: float, rms_db: float, seconds: float = 6.0):
    """指定峰值與 RMS (dBFS) 的 6 秒切片：隨機訊號調到 RMS，再放一個峰值樣本 (快篩只看這兩個數)。"""
    import numpy as np
    x = np.random.default_rng(1).standard_normal(int(16000 * seconds))
    x *= 10 ** (rms_db / 20) / np.sqrt(np.mean(x ** 2))
    x = np.clip(x, -10 ** (peak_db / 20), 10 ** (peak_db / 20))
    x[len(x) // 2] = 10 ** (peak_db / 20)
    return x.astype(np.float32)


def test_live_gate_skips_room_noise_but_keeps_quiet_speech():
    """2026-11-14 sim_gate.py：GS3 房間底噪 (峰值 ≤ -47 dB、RMS ≤ -78 dB) 照樣擋；
    說話聲小 30 dB 的切片 (中位數峰值 -35 dB、RMS -60 dB，SenseVoice 聽得懂) 舊門檻整片丟掉，不能再擋。"""
    import numpy as np
    assert mm.live_slice_is_quiet(_slice(-47.0, -78.0))
    assert mm.live_slice_is_quiet(np.zeros(0, dtype=np.float32))
    assert not mm.live_slice_is_quiet(_slice(-35.0, -60.0))
    assert not mm.live_slice_is_quiet(_slice(-43.0, -66.0))     # 小 35 dB 的 p10 切片
    assert not mm.live_slice_is_quiet(_slice(-5.0, -30.0))      # 一般音量


def test_pcm16_gate_matches_float_gate():
    """切片器用 16-bit PCM 判斷剛切下的是不是靜音片（是 → 下一片用短切片）。"""
    import numpy as np
    for peak_db, rms_db in ((-47.0, -78.0), (-35.0, -60.0), (-5.0, -30.0)):
        x = _slice(peak_db, rms_db)
        pcm = (x * 32768).astype("<i2").tobytes()
        assert vp.pcm16_is_quiet(pcm) == mm.live_slice_is_quiet(x)
    assert vp.pcm16_is_quiet(np.zeros(16000, dtype="<i2").tobytes())


def test_live_slicing_label_shows_current_gate():
    label = mm.live_slicing_label(8.0)
    assert f"峰值 < {mm.LIVE_SKIP_PEAK:g}" in label and f"RMS < {mm.LIVE_SKIP_RMS:g}" in label
