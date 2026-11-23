"""two_layer_audio：波形峰值（WaveSurfer 用）、16 kHz WAV 標頭、CPU 綁核。ffmpeg 以假的 Popen 代替，不需要 ffmpeg。"""
import wave

import numpy as np
import pytest

import two_layer_audio as tla


class _FakeProc:
    def __init__(self, out):
        self._out = out

    def communicate(self):
        return self._out, b""


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "m.ogg"
    p.write_bytes(b"\1" * 100)
    return str(p)


def _feed(monkeypatch, samples):
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        return _FakeProc(np.asarray(samples, dtype=np.int16).tobytes())
    monkeypatch.setattr(tla.subprocess, "Popen", fake)
    return calls


def test_peaks_missing_or_empty_file(tmp_path):
    assert tla.extract_waveform_peaks(str(tmp_path / "nope.ogg"), num_peaks=5) == [0.0] * 5
    empty = tmp_path / "e.ogg"
    empty.write_bytes(b"")
    assert tla.extract_waveform_peaks(str(empty), num_peaks=3) == [0.0] * 3


def test_peaks_block_max_abs(monkeypatch, audio_file):
    # 8 個樣本分成 4 塊：每塊取絕對值最大
    calls = _feed(monkeypatch, [0, 16384, -32768, 0, 3277, -3277, 0, 0])
    assert tla.extract_waveform_peaks(audio_file, num_peaks=4) == [0.5, 1.0, 0.1, 0.0]
    assert calls[0][calls[0].index("-ar") + 1] == "2000"


def test_peaks_short_audio_returns_each_sample(monkeypatch, audio_file):
    """樣本數 <= num_peaks（2 kHz 下不到 0.1 s）：逐樣本回傳絕對值，長度就是樣本數。"""
    _feed(monkeypatch, [16384, -16384, 0])
    assert tla.extract_waveform_peaks(audio_file, num_peaks=6) == [0.5, 0.5, 0.0]


def test_peaks_length_is_num_peaks_for_long_audio(monkeypatch, audio_file):
    _feed(monkeypatch, [1000] * 2001)
    assert len(tla.extract_waveform_peaks(audio_file, num_peaks=200)) == 200


def test_peaks_ffmpeg_failure(monkeypatch, audio_file):
    def boom(*a, **k):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(tla.subprocess, "Popen", boom)
    assert tla.extract_waveform_peaks(audio_file, num_peaks=4) == [0.0] * 4
    _feed(monkeypatch, [])
    assert tla.extract_waveform_peaks(audio_file, num_peaks=4) == [0.0] * 4


def test_write_pcm_wav_header_is_valid(tmp_path):
    pipe = tla.TwoLayerAudioPipe.__new__(tla.TwoLayerAudioPipe)   # 不需要 asyncio 物件
    pcm = np.arange(-800, 800, dtype=np.int16).tobytes()
    out = tmp_path / "c.wav"
    pipe._write_pcm_wav(str(out), pcm)
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.getnframes() == 1600
        assert w.readframes(1600) == pcm
    assert out.stat().st_size == 44 + len(pcm)


def test_affinity_uses_sched_setaffinity_or_taskset(monkeypatch):
    seen = []
    monkeypatch.setattr(tla.os, "sched_setaffinity", lambda pid, cores: seen.append((pid, cores)), raising=False)
    assert tla.set_process_core_affinity(123, [2, 3]) is True
    assert seen == [(123, {2, 3})]

    monkeypatch.delattr(tla.os, "sched_setaffinity")

    class R:
        returncode = 0
    runs = []
    monkeypatch.setattr(tla.subprocess, "run", lambda cmd, **kw: runs.append(cmd) or R())
    assert tla.set_process_core_affinity(7, [0, 1]) is True
    assert runs == [["taskset", "-cp", "0,1", "7"]]

    def boom(*a, **k):
        raise FileNotFoundError("taskset")
    monkeypatch.setattr(tla.subprocess, "run", boom)
    assert tla.set_process_core_affinity(7, [0]) is False


def test_transcribe_chunk_isolated_skips_tiny_file(tmp_path):
    p = tmp_path / "tiny.wav"
    p.write_bytes(b"\0" * 10)
    assert tla.transcribe_chunk_isolated(str(p)) == ""
    assert tla.transcribe_chunk_isolated(str(tmp_path / "none.wav")) == ""
