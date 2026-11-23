"""hailo_whisper.engine 補測：NPU 輸出後處理、音訊載入、開頭靜音修剪、HEF 探測、CPU 備援、引擎工廠。
hailo_platform／faster_whisper 都換成假的模組，不需要 Hailo 硬體、模型或 ffmpeg。

2026-11-23（localnote@mac）找到的 bug：
  1. 雜訊清理 re.sub(r"([,\\-\\s]{2,})+", "，") 把數字範圍「3 - 5」變成「3，5」（英文再轉回「3, 5」）：範圍變兩個數。
  2. 重複字清理 \\b(\\w)\\1{3,}\\b 連數字也縮：「分機 1111」→「分機 1」、「room 2222」→「room 2」。
  3. WAV 路徑不看取樣率／位元深度：8 kHz WAV 被當 16 kHz 送進模型（1 秒變 0.5 秒、音調錯）。
"""
import enum
import os
import sys
import types
import wave

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hailo_whisper import engine as eng   # noqa: E402


class _FakeS2T:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def generate_all_text(self, **kw):
        self.calls.append(kw)
        return self.reply


@pytest.fixture
def genai(monkeypatch):
    mod = types.ModuleType("hailo_platform.genai")
    mod.Speech2TextTask = enum.Enum("Speech2TextTask", {"TRANSCRIBE": "transcribe"})
    monkeypatch.setitem(sys.modules, "hailo_platform", types.ModuleType("hailo_platform"))
    monkeypatch.setitem(sys.modules, "hailo_platform.genai", mod)
    monkeypatch.setattr(eng, "speech_seconds", lambda audio, sr=16000: 1.0)
    monkeypatch.setattr(eng, "_OPENCC", None)
    return mod


def _engine(reply=""):
    e = object.__new__(eng.HailoWhisperEngine)
    e.hef_path, e.group_id, e._vdevice, e._initialized = "/m/Whisper-Small.hef", None, None, True
    e._s2t = _FakeS2T(reply)
    return e


def _speech(sec=2.0):
    t = np.arange(int(16000 * sec)) / 16000.0
    return (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _post(reply, language):
    return _engine(reply).transcribe(_speech(), language=language)["text"]


# ---------------------------------------------------------------- 後處理（bug 1、2）

@pytest.mark.parametrize("reply,lang,expect", [
    ("The budget is between 3 - 5 million dollars, and we agreed to proceed.", "en", "3-5 million"),
    ("預算在 3 - 5 萬之間", "zh", "3-5 萬"),
    ("第 10 - 12 頁", "zh", "10-12 頁"),
])
def test_numeric_range_is_kept(genai, reply, lang, expect):
    assert expect in _post(reply, lang)


@pytest.mark.parametrize("reply,lang,expect", [
    ("Please call extension 1111 tomorrow, the room is 2222 on the second floor.", "en", "extension 1111"),
    ("分機 1111 找我", "zh", "分機 1111"),
    ("預算 9999 元", "zh", "9999 元"),
])
def test_repeated_digits_are_kept(genai, reply, lang, expect):
    assert expect in _post(reply, lang)


@pytest.mark.parametrize("reply,lang,expect", [
    ("哈哈哈哈，好", "zh", "哈，好"),             # 重複字幻覺仍要縮
    ("aaaa yes", "en", "a yes"),
    ("嗯，，，好", "zh", "嗯，好"),               # 連續逗號縮成一個
    ("好 - - - 那就這樣", "zh", "好，那就這樣"),   # 停頓雜訊
    ("—— ，開始吧", "zh", "—— ，開始吧"),        # 不在清理範圍的符號不動
])
def test_noise_cleanup_still_works(genai, reply, lang, expect):
    assert _post(reply, lang) == expect


def test_prompt_bleed_and_replacement_chars_removed(genai):
    assert _post("No Hallucination. 今天�開會", "zh") == "今天開會"
    assert _post("--, 開始", "zh") == "開始"                # 開頭的標點殘渣


def test_result_fields(genai):
    r = _engine("好").transcribe(_speech(), language="zh")
    assert r["backend"] == "hailo-10h" and r["model"] == "Whisper-Small" and r["language"] == "zh"
    assert r["inference_time_ms"] >= 0 and eng.is_hailo_inference_active() is False


def test_not_initialized_raises():
    e = _engine()
    e._initialized = False
    with pytest.raises(RuntimeError, match="not initialized"):
        e.transcribe(_speech())


def test_short_or_unloadable_audio_returns_empty(genai):
    e = _engine("不該呼叫")
    assert e.transcribe(np.zeros(100, np.float32), language="zh")["text"] == ""
    assert e.transcribe(12345, language="zh")["text"] == ""      # 不支援的型別 → None → 空字串
    assert e._s2t.calls == []


def test_dynamic_timeout(genai):
    e = _engine("好")
    e.transcribe(_speech(40.0), language="zh")
    assert e._s2t.calls[0]["timeout_ms"] == int((40 * 1.5 + 10) * 1000)
    e.transcribe(_speech(2.0), language="zh")
    assert e._s2t.calls[1]["timeout_ms"] == 30000


# ---------------------------------------------------------------- 音訊載入（bug 3）

def _wav(path, rate, data, width=2, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(data)
    return str(path)


def test_load_16k_wav_mono_and_stereo(tmp_path):
    e = _engine()
    pcm = (np.ones(1600, np.int16) * 16384).tobytes()
    out = e._load_audio_to_pcm_float(_wav(tmp_path / "a.wav", 16000, pcm))
    assert len(out) == 1600 and np.allclose(out, 0.5)
    stereo = np.column_stack([np.full(800, 16384, np.int16), np.zeros(800, np.int16)]).tobytes()
    out = e._load_audio_to_pcm_float(_wav(tmp_path / "s.wav", 16000, stereo, channels=2))
    assert len(out) == 800 and np.allclose(out, 0.5)          # 取左聲道


def test_non_16k_wav_goes_through_ffmpeg_resample(tmp_path, monkeypatch):
    """8 kHz／44.1 kHz WAV 不能直接當 16 kHz：要交給 ffmpeg 重新取樣（-ar 16000）。"""
    e = _engine()
    seen = []

    def check_output(cmd, **kw):
        seen.append(cmd)
        return np.zeros(16000, np.int16).tobytes()           # ffmpeg 重新取樣後 1 秒 = 16000 樣本
    monkeypatch.setattr("subprocess.check_output", check_output)
    path = _wav(tmp_path / "8k.wav", 8000, np.zeros(8000, np.int16).tobytes())
    out = e._load_audio_to_pcm_float(path)
    assert seen and seen[0][seen[0].index("-ar") + 1] == "16000"
    assert len(out) == 16000


def test_8bit_wav_goes_through_ffmpeg(tmp_path, monkeypatch):
    e = _engine()
    seen = []
    monkeypatch.setattr("subprocess.check_output", lambda cmd, **kw: seen.append(cmd) or np.zeros(4, np.int16).tobytes())
    e._load_audio_to_pcm_float(_wav(tmp_path / "u8.wav", 16000, bytes([128] * 160), width=1))
    assert seen


def test_load_bytes_ndarray_and_failures(tmp_path, monkeypatch):
    e = _engine()
    out = e._load_audio_to_pcm_float(np.array([[2.0], [-3.0], [0.5]]))
    assert out.dtype == np.float32 and out.tolist() == [pytest.approx(0.999999), -1.0, 0.5]
    out = e._load_audio_to_pcm_float(np.array([16384, -32768], np.int16).tobytes())
    assert out.tolist() == [0.5, -1.0]
    assert e._load_audio_to_pcm_float(str(tmp_path / "missing.ogg")) is None

    def fail(cmd, **kw):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr("subprocess.check_output", fail)
    ogg = tmp_path / "a.ogg"
    ogg.write_bytes(b"OggS....")
    assert e._load_audio_to_pcm_float(str(ogg)) is None


# ---------------------------------------------------------------- 開頭靜音修剪

def test_trim_leading_silence_rules():
    e = _engine()
    sr = 16000
    tone = _speech(1.0)
    short = np.concatenate([np.zeros(sr), tone])                # 開頭 1 s 靜音 < 1.5 s：不剪
    assert len(e._trim_leading_silence(short)) == len(short)
    long = np.concatenate([np.zeros(3 * sr), tone])             # 3 s 靜音：剪到剩 0.5 s 前導
    assert len(e._trim_leading_silence(long)) == len(long) - int(2.5 * sr)
    silent = np.zeros(4 * sr, np.float32)                       # 全靜音：不動
    assert len(e._trim_leading_silence(silent)) == len(silent)
    tiny = np.zeros(100, np.float32)
    assert e._trim_leading_silence(tiny) is tiny and e._trim_leading_silence(None) is None


# ---------------------------------------------------------------- HEF 探測／引擎工廠／CPU 備援

class _VDevice:
    made = []

    def __init__(self, params=None):
        _VDevice.made.append(params)

    @staticmethod
    def create_params():
        return types.SimpleNamespace(group_id=None)


@pytest.fixture
def platform(monkeypatch):
    _VDevice.made = []
    hp = types.ModuleType("hailo_platform")
    hp.VDevice = _VDevice
    ga = types.ModuleType("hailo_platform.genai")
    state = {"fail": set()}

    class Speech2Text:
        def __init__(self, vdev, path):
            if path in state["fail"]:
                raise RuntimeError("bad hef")
            self.path = path
    ga.Speech2Text = Speech2Text
    monkeypatch.setitem(sys.modules, "hailo_platform", hp)
    monkeypatch.setitem(sys.modules, "hailo_platform.genai", ga)
    return state


def test_probe_picks_first_working_candidate_and_group_id(platform, tmp_path, monkeypatch):
    a, b = tmp_path / "Whisper-Small.hef", tmp_path / "Whisper-Base.hef"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    monkeypatch.setattr(eng.HailoWhisperEngine, "CANDIDATE_HEF_PATHS", [str(tmp_path / "none.hef"), str(a), str(b)])
    platform["fail"] = {str(a)}
    e = eng.HailoWhisperEngine(group_id="G")
    assert e.is_hardware_accelerated() and e.hef_path == str(b) and e.model_name() == "Whisper-Base"
    assert _VDevice.made[0].group_id == "G"
    e2 = eng.HailoWhisperEngine()
    assert _VDevice.made[-1] is None and e2.hef_path == str(b)


def test_probe_no_hef_or_all_fail(platform, tmp_path, monkeypatch):
    monkeypatch.setattr(eng.HailoWhisperEngine, "CANDIDATE_HEF_PATHS", [str(tmp_path / "none.hef")])
    assert not eng.HailoWhisperEngine().is_hardware_accelerated()
    h = tmp_path / "x.hef"
    h.write_bytes(b"x")
    platform["fail"] = {str(h)}
    assert not eng.HailoWhisperEngine(hef_path=str(h)).is_hardware_accelerated()


def test_probe_without_hailo_platform(monkeypatch):
    monkeypatch.setitem(sys.modules, "hailo_platform", None)    # import 會 ImportError
    e = eng.HailoWhisperEngine()
    assert not e.is_hardware_accelerated() and e.model_name() == "Whisper"


def test_resolve_hef_path(tmp_path, monkeypatch):
    h = tmp_path / "W.hef"
    h.write_bytes(b"x")
    e = object.__new__(eng.HailoWhisperEngine)
    e.hef_path = str(h)
    assert e._resolve_hef_path() == str(h)
    e.hef_path = None
    monkeypatch.setattr(eng.HailoWhisperEngine, "CANDIDATE_HEF_PATHS", [str(tmp_path / "no.hef"), str(h)])
    assert e._resolve_hef_path() == str(h)
    monkeypatch.setattr(eng.HailoWhisperEngine, "CANDIDATE_HEF_PATHS", [])
    assert e._resolve_hef_path() is None


def test_factory(monkeypatch):
    class Ready:
        def __init__(self, hef_path=None):
            pass

        def is_hardware_accelerated(self):
            return True
    monkeypatch.setattr(eng, "HailoWhisperEngine", Ready)
    assert isinstance(eng.get_whisper_engine("auto"), Ready)
    assert isinstance(eng.get_whisper_engine("cpu"), eng.CpuFallbackWhisperEngine)

    class Boom:
        def __init__(self, hef_path=None):
            raise RuntimeError("no npu")
    monkeypatch.setattr(eng, "HailoWhisperEngine", Boom)
    assert isinstance(eng.get_whisper_engine("hailo"), eng.CpuFallbackWhisperEngine)


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    fw = types.ModuleType("faster_whisper")
    made = []

    class WhisperModel:
        def __init__(self, size, **kw):
            made.append((size, kw))

        def transcribe(self, path, **kw):
            self.kw = kw
            return iter([types.SimpleNamespace(text=" 今天"), types.SimpleNamespace(text="開會 ")]), \
                types.SimpleNamespace(language="zh")
    fw.WhisperModel = WhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    return made


def test_cpu_fallback_transcribe(fake_faster_whisper, monkeypatch):
    class CC:
        def convert(self, s):
            return s + "（繁）"
    monkeypatch.setattr(eng, "_OPENCC", CC())
    e = eng.CpuFallbackWhisperEngine(model_size="base")
    r = e.transcribe("x.wav", language="zh")
    assert r["text"] == "今天開會（繁）" and r["language"] == "zh" and r["backend"] == "cpu-faster-whisper"
    assert fake_faster_whisper == [("base", {"device": "cpu", "compute_type": "int8", "cpu_threads": 4})]
    e.transcribe("y.wav")
    assert len(fake_faster_whisper) == 1                       # 模型只載入一次
    assert e.is_hardware_accelerated() is False


def test_cpu_fallback_without_faster_whisper(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(RuntimeError, match="could not be loaded"):
        eng.CpuFallbackWhisperEngine().transcribe("x.wav")


def test_vad_label_and_speech_seconds(monkeypatch):
    monkeypatch.setattr(eng, "WHISPER_VAD", False)
    assert "關閉" in eng.vad_label() and eng.speech_seconds(np.zeros(16000)) is None
    monkeypatch.setattr(eng, "WHISPER_VAD", True)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", None)
    assert "未安裝" in eng.vad_label() and eng.speech_seconds(np.zeros(16000)) is None
