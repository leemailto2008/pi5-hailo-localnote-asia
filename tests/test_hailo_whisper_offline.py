"""hailo_whisper 的 tokenizer 與 log-mel（純 NumPy）：tests/ 原本沒有涵蓋（只有 hailo_whisper/test_mock_pipeline.py，CI 不跑）。"""
import json

import numpy as np
import pytest

from hailo_whisper import tokenizer as tk
from hailo_whisper.audio_processor import AudioProcessor
from hailo_whisper.tokenizer import WhisperTokenizer


@pytest.fixture
def no_opencc(monkeypatch):
    monkeypatch.setattr(tk, "_OPENCC", None)


def test_initial_tokens():
    t = WhisperTokenizer()
    S = WhisperTokenizer.SPECIAL_TOKENS
    assert t.get_initial_tokens() == [S["<|startoftranscript|>"], S["<|transcribe|>"], S["<|notimestamps|>"]]
    assert t.get_initial_tokens("ZH", "translate", timestamps=True) == [S["<|startoftranscript|>"], S["<|zh|>"], S["<|translate|>"]]
    assert t.get_initial_tokens("xx", "bogus") == [S["<|startoftranscript|>"], S["<|transcribe|>"], S["<|notimestamps|>"]]


def test_decode_skips_special_and_timestamp_tokens(tmp_path, no_opencc):
    vocab = tmp_path / "vocab.json"
    vocab.write_text(json.dumps({"會議": 100, "開始": 101, "No Hallucination.": 102}), encoding="utf-8")
    t = WhisperTokenizer(str(vocab))
    ids = [50258, 50260, 50359, 50363, 102, 100, 101, 50364, 999999, 50257]
    assert t.decode_tokens(ids) == "會議開始"


def test_decode_filters_known_hallucinations(tmp_path, no_opencc):
    vocab = tmp_path / "v.json"
    vocab.write_text(json.dumps({"好": 1, "謝謝收看": 2, " 請訂閱": 3}), encoding="utf-8")
    t = WhisperTokenizer(str(vocab))
    assert t.decode_tokens([1, 2, 3]) == "好"
    assert t.decode_tokens([2]) == ""


def test_bad_or_missing_vocab_keeps_special_tokens(tmp_path, no_opencc):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    for path in (str(bad), str(tmp_path / "missing.json"), None):
        t = WhisperTokenizer(path)
        assert t.decode_tokens([1, 2, 50257]) == ""         # 不認得的 id 解成空字串、不拋例外
        assert t._token_to_id["<|zh|>"] == 50260


def test_decode_converts_to_traditional_when_opencc(monkeypatch):
    class FakeCC:
        def convert(self, s):
            return s.replace("会议", "會議")
    monkeypatch.setattr(tk, "_OPENCC", FakeCC())
    t = WhisperTokenizer()
    t._id_to_token[5] = "会议"
    assert t.decode_tokens([5]) == "會議"
    assert t.decode_tokens([5], convert_traditional=False) == "会议"


# ---------------------------------------------------------------- AudioProcessor

@pytest.fixture(scope="module")
def ap():
    return AudioProcessor()


def test_mel_filterbank_shape_and_coverage(ap):
    f = ap._mel_filters
    assert f.shape == (80, 201) and f.dtype == np.float32
    assert (f >= 0).all()
    assert (f.sum(axis=1) > 0).sum() >= 75        # 最低頻幾個濾波器可能落在同一個 FFT bin


def test_hz_mel_roundtrip(ap):
    for hz in (0.0, 440.0, 1000.0, 8000.0):
        assert ap._mel_to_hz(ap._hz_to_mel(hz)) == pytest.approx(hz, abs=1e-6)


def test_log_mel_shape_padding_and_range(ap):
    t = np.arange(16000) / 16000
    tone = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    mel = ap.log_mel_spectrogram(tone)
    assert mel.shape == (80, 3000) and mel.dtype == np.float32
    assert np.isfinite(mel).all()
    assert mel.max() - mel.min() <= 8.0 / 4.0 + 1e-5      # Whisper 動態範圍上限 8 個 log10 單位、再 /4
    band = int(np.argmax(mel[:, :50].mean(axis=1)))
    centers = [ap._mel_to_hz(m) for m in np.linspace(ap._hz_to_mel(0), ap._hz_to_mel(8000), 82)[1:-1]]
    assert abs(centers[band] - 1000) < 150                # 1 kHz 純音落在中心約 1 kHz 的 mel 帶


def test_log_mel_truncates_long_audio(ap):
    long = np.zeros(16000 * 35, dtype=np.float32)
    assert ap.log_mel_spectrogram(long).shape == (80, 3000)


def test_log_mel_rejects_2d(ap):
    with pytest.raises(ValueError):
        ap.log_mel_spectrogram(np.zeros((2, 16000), dtype=np.float32))
