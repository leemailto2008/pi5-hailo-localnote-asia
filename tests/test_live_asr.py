"""即時逐字稿引擎選擇 (2026-11-13「錄音中也用 SenseVoice」)：偏好存檔、依收音來源決定引擎、SenseVoice 失敗改走 Whisper。"""
import sys
import types

import numpy as np

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import voice_pipeline as vp  # noqa: E402
import sv_worker as svw  # noqa: E402

USB = "alsa_input.usb-GeneralPlus_USB_Audio_Device-00.mono-fallback"
BT = "bluez_input_internal.A0_D1_2A_42_12_34.0"


def test_live_engine_uses_sensevoice_only_when_chosen_and_not_bluetooth():
    assert vp.live_asr_engine("sensevoice", USB, sv_on_bt=False) == "sensevoice"
    assert vp.live_asr_engine("sensevoice", "null_sink.monitor", sv_on_bt=False) == "sensevoice"   # e2e 數位直送
    assert vp.live_asr_engine("sensevoice", BT, sv_on_bt=False) == "whisper"     # 藍牙：錄音中不跑 CPU 推論
    assert vp.live_asr_engine("sensevoice", BT, sv_on_bt=True) == "sensevoice"   # 夜間量測用的覆寫
    assert vp.live_asr_engine("whisper", USB, sv_on_bt=True) == "whisper"
    assert vp.live_asr_engine("sensevoice", "", sv_on_bt=False) == "whisper"     # 還不知道來源
    assert vp.live_asr_engine("sensevoice", USB, sv_available=False) == "whisper"   # 這台沒裝 SenseVoice


def test_live_asr_preference_round_trip_and_bad_values(monkeypatch, tmp_path):
    path = tmp_path / "data" / "live_asr.json"
    monkeypatch.setattr(vp, "LIVE_ASR_PATH", str(path))
    assert vp.load_live_asr_preference() == "sensevoice"         # 沒存過：預設 SenseVoice（11-13 使用者決定）
    assert vp.save_live_asr_preference("sensevoice") == "sensevoice"
    assert vp.load_live_asr_preference() == "sensevoice"
    try:
        vp.save_live_asr_preference("gpt")
        raise AssertionError("bad engine accepted")
    except ValueError:
        pass
    assert vp.save_live_asr_preference("whisper") == "whisper"
    assert vp.load_live_asr_preference() == "whisper"            # 使用者選過就照他的
    path.write_text("{not json", encoding="utf-8")
    assert vp.load_live_asr_preference() == "sensevoice"         # 壞檔：用預設
    path.write_text('{"engine": "paraformer"}', encoding="utf-8")
    assert vp.load_live_asr_preference() == "sensevoice"


def test_speech_to_text_live_routes_and_falls_back(monkeypatch):
    audio = np.zeros(16000, dtype=np.float32)
    calls = []
    monkeypatch.setattr(vp, "speech_to_text", lambda a, c=None, info_out=None: calls.append("whisper") or "惠斯珀")
    monkeypatch.setattr(svw.sv_worker, "transcribe", lambda a: {"text": "森斯", "inference_time_ms": 300})
    info = {}
    assert vp.speech_to_text_live(audio, "sensevoice", info_out=info) == "森斯"
    assert info["engine"].startswith("SenseVoiceSmall") and info["post"] == svw.LIVE_POST_LABEL and not calls

    def boom(a):
        raise RuntimeError("sv worker transcribe failed: EOF")
    monkeypatch.setattr(svw.sv_worker, "transcribe", boom)
    assert vp.speech_to_text_live(audio, "sensevoice") == "惠斯珀"   # 這段改走 Hailo Whisper
    assert vp.speech_to_text_live(audio, "whisper") == "惠斯珀"
    assert calls == ["whisper", "whisper"]


def test_sensevoice_noise_outputs_are_dropped_only_when_marked_and_short(monkeypatch):
    assert vp.sv_is_noise("The.", "<|en|>", "<|EMO_UNKNOWN|>")
    assert vp.sv_is_noise("哈。", "<|zh|>", "<|EMO_UNKNOWN|>")
    assert vp.sv_is_noise("그.", "<|ko|>", "<|EMO_UNKNOWN|>")
    assert vp.sv_is_noise("。", "<|nospeech|>", "<|NEUTRAL|>")
    assert not vp.sv_is_noise("好。", "<|zh|>", "<|NEUTRAL|>")                       # 真人短回覆
    assert not vp.sv_is_noise("第一個議題是韌體更新。", "<|zh|>", "<|EMO_UNKNOWN|>")   # 長的照收
    audio = np.zeros(16000, dtype=np.float32)
    monkeypatch.setattr(vp, "speech_to_text", lambda a, c=None, info_out=None: "不該呼叫")
    monkeypatch.setattr(svw.sv_worker, "transcribe",
                        lambda a: {"text": "The.", "lang": "<|en|>", "emotion": "<|EMO_UNKNOWN|>", "inference_time_ms": 300})
    assert vp.speech_to_text_live(audio, "sensevoice") == ""
