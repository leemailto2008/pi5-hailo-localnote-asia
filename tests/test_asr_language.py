import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))

import asr_language as al  # noqa: E402


def test_engine_and_languages():
    assert al.live_engine_for("sensevoice", "auto") == "sensevoice"
    assert al.live_engine_for("sensevoice", "zh") == "sensevoice"
    assert al.live_engine_for("sensevoice", "fr") == "whisper" and al.live_engine_for("sensevoice", "es") == "whisper"
    assert al.live_engine_for("whisper", "zh") == "whisper"
    assert al.sv_language("zh") == "zh" and al.sv_language("auto") == "auto" and al.sv_language("fr") == "auto"
    assert al.whisper_language("auto") is None and al.whisper_language("es") == "es"
    assert set(al.ASR_LANG_CHOICES) == {"auto", "zh", "en", "fr", "es"}


def test_preference_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "ASR_LANG_PATH", str(tmp_path / "asr_language.json"))
    assert al.load_asr_language() == "auto"
    al.save_asr_language("fr")
    assert al.load_asr_language() == "fr"
    try:
        al.save_asr_language("hi")
        raise AssertionError("should reject")
    except ValueError:
        pass


def test_refine_reads_saved_language(tmp_path):
    import refine_transcript as rt
    cache = tmp_path / "audio_cache"
    cache.mkdir()
    audio = str(cache / "m_1.ogg")
    assert rt.live_asr_language(audio) == "auto"
    rt.save_live_asr(audio, [{"s": 0, "n": 16000, "wtext": "hola"}], 16000, rt.LIVE_WHISPER_SUFFIX, "es")
    assert rt.live_asr_language(audio) == "es"
