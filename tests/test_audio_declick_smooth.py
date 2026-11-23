"""audio_declick.make_smooth_ogg：解碼 → 分段修平 → 編碼的串流接線、失敗時不留半成品。ffmpeg 換成假的行程。"""
import io
import os

import numpy as np
import pytest

import audio_declick as ad


class _Dec:
    """假的 ffmpeg 解碼：stdout 是 PCM。"""
    def __init__(self, pcm: bytes, rc=0):
        self.stdout = io.BytesIO(pcm)
        self.rc, self.killed, self._done = rc, False, False

    def wait(self, timeout=None):
        self._done = True
        return self.rc

    def poll(self):
        return self.rc if self._done else None

    def kill(self):
        self.killed = True
        self._done = True


class _Enc:
    """假的 ffmpeg 編碼：收 stdin，wait() 時把收到的樣本寫進輸出檔（最後一個參數）。"""
    def __init__(self, argv, rc=0, write=True):
        self.out_path, self.rc, self.write = argv[-1], rc, write
        self.stdin = io.BytesIO()
        self.stdin.close = lambda: None           # 保留內容給 wait() 用
        self.killed, self._done = False, False

    def wait(self, timeout=None):
        if self.write:
            with open(self.out_path, "wb") as f:
                f.write(self.stdin.getvalue())
        self._done = True
        return self.rc

    def poll(self):
        return self.rc if self._done else None

    def kill(self):
        self.killed = True
        self._done = True


@pytest.fixture
def procs(monkeypatch):
    state = {"dec_rc": 0, "enc_rc": 0, "pcm": b"", "made": []}

    def popen(argv, **kw):
        if "-i" in argv and argv[argv.index("-i") + 1] == "-":
            p = _Enc(argv, rc=state["enc_rc"])
        else:
            p = _Dec(state["pcm"], rc=state["dec_rc"])
        state["made"].append((argv, p))
        return p
    monkeypatch.setattr(ad.subprocess, "Popen", popen)
    return state


def _pcm_with_step(n=16000 * 3):
    rng = np.random.default_rng(0)
    x = (rng.standard_normal(n) * 200).astype(np.int16)
    x[n // 2:] += 12000                          # 掉封包造成的階梯跳變
    return x


def test_make_smooth_ogg_streams_and_replaces_atomically(procs, tmp_path):
    pcm = _pcm_with_step()
    procs["pcm"] = pcm.tobytes()
    src = tmp_path / "m_1.ogg"
    ok, n = ad.make_smooth_ogg(str(src))
    dst = tmp_path / "m_1.smooth.ogg"
    assert ok is True and n >= 1
    assert dst.exists() and not (tmp_path / "m_1.smooth.ogg.part").exists()
    out = np.frombuffer(dst.read_bytes(), dtype="<i2")
    assert len(out) == len(pcm)                   # 樣本數不變（只修平、不增減）
    expect, _ = ad.declick(pcm)
    np.testing.assert_array_equal(out, expect)    # 串流結果與整段 declick 相同
    dec_argv, enc_argv = procs["made"][0][0], procs["made"][1][0]
    assert dec_argv[:3] == ["nice", "-n", "10"] and enc_argv[:3] == ["nice", "-n", "10"]
    assert enc_argv[enc_argv.index("-b:a") + 1] == "64k" and enc_argv[-1].endswith(".part")


@pytest.mark.parametrize("dec_rc,enc_rc", [(1, 0), (0, 1)])
def test_make_smooth_ogg_ffmpeg_failure_leaves_no_files(procs, tmp_path, dec_rc, enc_rc):
    procs.update(pcm=_pcm_with_step().tobytes(), dec_rc=dec_rc, enc_rc=enc_rc)
    ok, n = ad.make_smooth_ogg(str(tmp_path / "m.ogg"))
    assert (ok, n) == (False, 0)
    assert os.listdir(tmp_path) == []             # .part 與 .smooth.ogg 都不留


def test_make_smooth_ogg_timeout_kills_both(procs, tmp_path, monkeypatch):
    procs["pcm"] = _pcm_with_step().tobytes()
    monkeypatch.setattr(ad, "SMOOTH_TIMEOUT_S", -1)    # 一開始就超過期限
    ok, _ = ad.make_smooth_ogg(str(tmp_path / "m.ogg"), dst=str(tmp_path / "out.ogg"))
    assert ok is False
    assert all(p.killed for _, p in procs["made"])
    assert os.listdir(tmp_path) == []


def test_make_smooth_ogg_cannot_start_ffmpeg(monkeypatch, tmp_path):
    def missing(argv, **kw):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(ad.subprocess, "Popen", missing)
    assert ad.make_smooth_ogg(str(tmp_path / "m.ogg")) == (False, 0)


def test_start_smooth_job_failure_resets_state(monkeypatch):
    def missing(argv, **kw):
        raise OSError("no python3")
    monkeypatch.setattr(ad.subprocess, "Popen", missing)
    ad.start_smooth_job("/tmp/none.ogg")
    assert ad._bg_proc is None and ad._bg_src == ""
    ad.stop_smooth_job()                          # 沒有背景工作時呼叫不出錯
