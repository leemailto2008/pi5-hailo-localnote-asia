"""voice_pipeline.transcribe_pcm_chunk 的 Hailo 失敗訊息：同一種錯誤只印第一次（每個切片都會呼叫，避免洗版 journal）。"""
import sys
import types

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import voice_pipeline as vp  # noqa: E402


def test_same_error_printed_once(monkeypatch, capsys):
    monkeypatch.setattr(vp, "_hailo_chunk_errors_seen", set())
    for _ in range(5):
        vp._report_hailo_chunk_error(ModuleNotFoundError("No module named 'hailo_engine'"))
    vp._report_hailo_chunk_error(RuntimeError("NPU busy"))
    out = capsys.readouterr().out
    assert out.count("hailo_engine") == 1
    assert out.count("NPU busy") == 1


def test_dedupe_set_is_capped(monkeypatch, capsys):
    """11-24 Mac N4：錯誤字串帶變動內容（位址、時間）時，去重集合不能無限長。"""
    monkeypatch.setattr(vp, "_hailo_chunk_errors_seen", set())
    for i in range(100):   # 變動的是字母（數字會被正規化成同一種）
        vp._report_hailo_chunk_error(RuntimeError(f"timeout at {chr(65 + i % 26)}{chr(65 + i // 26)}"))
    assert len(vp._hailo_chunk_errors_seen) == vp._HAILO_CHUNK_ERRORS_MAX
    assert capsys.readouterr().out.count("timeout at") == vp._HAILO_CHUNK_ERRORS_MAX


def test_dedupe_key_ignores_numbers(monkeypatch, capsys):
    """11-24 Mac N6：錯誤訊息只差數字（位址、時間、計數）算同一種。"""
    monkeypatch.setattr(vp, "_hailo_chunk_errors_seen", set())
    for i in range(10):
        vp._report_hailo_chunk_error(RuntimeError(f"timeout after {i * 100} ms at 0x{i}f"))
    assert len(vp._hailo_chunk_errors_seen) == 1
    assert capsys.readouterr().out.count("timeout after") == 1
