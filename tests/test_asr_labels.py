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
