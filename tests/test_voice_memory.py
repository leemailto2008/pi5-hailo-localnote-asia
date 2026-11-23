"""voice_memory：記憶體磁碟環狀緩衝區的清除規則、快取統計、ffmpeg 解碼（ffmpeg 以假的 Popen 代替，不需要 ffmpeg）。"""
import os
import time

import numpy as np
import pytest

import voice_memory as vm


@pytest.fixture
def cache(tmp_path, monkeypatch):
    d = tmp_path / "audio_cache"
    d.mkdir()
    monkeypatch.setattr(vm, "get_in_memory_cache_dir", lambda: str(d))
    return d


def _file(d, name, size, age_s):
    p = d / name
    p.write_bytes(b"\0" * size)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def _session_dir(d, name, sizes, age_s):
    p = d / name
    p.mkdir()
    for i, s in enumerate(sizes):
        (p / f"chunk_{i}.ogg").write_bytes(b"\0" * s)
    t = time.time() - age_s
    os.utime(p, (t, t))
    return p


def test_evict_oldest_first_until_under_quota(cache):
    _file(cache, "a.ogg", 400, 3000)
    _file(cache, "b.ogg", 400, 2000)
    _file(cache, "c.ogg", 400, 1000)
    res = vm.evict_audio_ring_buffer(max_bytes=900, max_sessions=99)
    assert res["evicted_count"] == 1 and res["reclaimed_bytes"] == 400
    assert sorted(os.listdir(cache)) == ["b.ogg", "c.ogg"]
    assert res["remaining_bytes"] == 800 and res["remaining_count"] == 2
    assert res["is_ramfs"] is False


def test_evict_by_session_count(cache):
    for i in range(5):
        _file(cache, f"{i}.ogg", 10, 5000 - i * 100)
    res = vm.evict_audio_ring_buffer(max_bytes=10**9, max_sessions=3)
    assert res["evicted_count"] == 2
    assert sorted(os.listdir(cache)) == ["2.ogg", "3.ogg", "4.ogg"]


def test_evict_counts_directory_sizes_and_removes_whole_session(cache):
    _session_dir(cache, "job_old", [300, 300], 4000)
    _file(cache, "new.ogg", 100, 3000)
    res = vm.evict_audio_ring_buffer(max_bytes=500, max_sessions=99)
    assert res["reclaimed_bytes"] == 600
    assert os.listdir(cache) == ["new.ogg"]


def test_never_evicts_recent_or_newest(cache, monkeypatch):
    """錄音中（最近 ACTIVE_WRITE_GRACE_SEC 內改過）與最新一筆一律保留，即使超過配額。"""
    _file(cache, "old.ogg", 1000, 5000)
    _file(cache, "recording.ogg", 1000, 5)
    res = vm.evict_audio_ring_buffer(max_bytes=10, max_sessions=0)
    assert os.listdir(cache) == ["recording.ogg"]
    assert res["evicted_count"] == 1

    only = cache.parent / "only"
    only.mkdir()
    _file(only, "single_old.ogg", 1000, 9999)
    monkeypatch.setattr(vm, "get_in_memory_cache_dir", lambda: str(only))
    assert vm.evict_audio_ring_buffer(max_bytes=0, max_sessions=0)["evicted_count"] == 0
    assert os.listdir(only) == ["single_old.ogg"]


def test_evict_empty_and_missing_dir(cache, monkeypatch, tmp_path):
    assert vm.evict_audio_ring_buffer()["evicted_count"] == 0
    monkeypatch.setattr(vm, "get_in_memory_cache_dir", lambda: str(tmp_path / "nope"))
    assert vm.evict_audio_ring_buffer() == {"evicted_count": 0, "reclaimed_bytes": 0}


def test_cache_stats_walks_subdirs(cache):
    _file(cache, "a.ogg", 1024 * 1024, 10)
    _session_dir(cache, "s", [10, 20], 10)
    st = vm.get_cache_stats()
    assert st["item_count"] == 3
    assert st["total_bytes"] == 1024 * 1024 + 30
    assert st["total_mb"] == 1.0
    assert st["is_ramfs"] is False and st["storage_type"] == "Physical Storage"
    assert st["quota_mb"] == round(vm.MAX_RAM_CACHE_BYTES / 1024 / 1024, 1)


def test_cache_dir_falls_back_when_no_dev_shm(monkeypatch, tmp_path):
    monkeypatch.setattr(vm.os.path, "exists", lambda p: False if p == "/dev/shm" else os.path.lexists(p))
    monkeypatch.setattr(vm, "__file__", str(tmp_path / "voice_memory.py"))
    d = vm.get_in_memory_cache_dir()
    assert d == str(tmp_path / "audio_cache") and os.path.isdir(d)


class _FakeProc:
    def __init__(self, out, rc=0):
        self._out, self.returncode = out, rc
        self.stdin_seen = None

    def communicate(self, input=None):
        self.stdin_seen = input
        return self._out, b""


def _patch_popen(monkeypatch, proc):
    calls = []

    def fake(cmd, **kw):
        calls.append((cmd, kw))
        return proc
    monkeypatch.setattr(vm.subprocess, "Popen", fake)
    return calls


def test_pcm_decode_from_file(monkeypatch, tmp_path):
    src = tmp_path / "x.ogg"
    src.write_bytes(b"\1" * 600)
    pcm = np.array([0, 16384, -32768, 32767], dtype=np.int16).tobytes()
    calls = _patch_popen(monkeypatch, _FakeProc(pcm))
    out = vm.audio_to_pcm_array(str(src))
    np.testing.assert_allclose(out, [0.0, 0.5, -1.0, 32767 / 32768], rtol=0, atol=1e-6)
    assert out.dtype == np.float32
    cmd, kw = calls[0]
    assert cmd[:4] == ["ffmpeg", "-y", "-i", str(src)] and cmd[-5:] == ["-ac", "1", "-ar", "16000", "-"]
    assert kw["stdin"] == vm.subprocess.DEVNULL


def test_pcm_decode_from_bytes_uses_stdin(monkeypatch):
    proc = _FakeProc(np.zeros(8, dtype=np.int16).tobytes())
    calls = _patch_popen(monkeypatch, proc)
    data = b"\2" * 800
    out = vm.audio_to_pcm_array(data)
    assert out is not None and len(out) == 8
    assert calls[0][0][3] == "pipe:0" and proc.stdin_seen == data
    assert calls[0][1]["stdin"] == vm.subprocess.PIPE


@pytest.mark.parametrize("src", [b"short", 12345, None])
def test_pcm_decode_rejects_tiny_or_wrong_type(monkeypatch, src):
    calls = _patch_popen(monkeypatch, _FakeProc(b"\0\0"))
    assert vm.audio_to_pcm_array(src) is None
    assert calls == []


def test_pcm_decode_missing_or_small_file(monkeypatch, tmp_path):
    calls = _patch_popen(monkeypatch, _FakeProc(b"\0\0"))
    assert vm.audio_to_pcm_array(str(tmp_path / "missing.ogg")) is None
    small = tmp_path / "small.ogg"
    small.write_bytes(b"\0" * 100)
    assert vm.audio_to_pcm_array(str(small)) is None
    assert calls == []


@pytest.mark.parametrize("out,rc", [(b"", 0), (b"\0\0\0\0", 1)])
def test_pcm_decode_ffmpeg_failure(monkeypatch, out, rc):
    _patch_popen(monkeypatch, _FakeProc(out, rc))
    assert vm.audio_to_pcm_array(b"\3" * 600) is None


def test_pcm_decode_ffmpeg_missing(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(vm.subprocess, "Popen", boom)
    assert vm.audio_to_pcm_array(b"\3" * 600) is None
