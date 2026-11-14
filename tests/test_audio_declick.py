import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))
import audio_declick  # noqa: E402


def _tone(sec=1.0, sr=16000, f=300.0, amp=8000.0):
    t = np.arange(int(sec * sr)) / sr
    return amp * np.sin(2 * np.pi * f * t)


def test_clean_audio_is_left_alone():
    x = _tone().astype(np.int16)
    y, n = audio_declick.declick(x)
    assert n == 0 and np.array_equal(x, y)


def test_dropped_packet_step_is_smoothed():
    # 藍牙掉一個封包 (7.5 ms = 120 樣本) 後音訊直接接上：在相位相差半週期處接起來，形成大跳變
    x = _tone(2.0)
    cut = 16013                                                         # 波峰處 (1/4 週期)
    spliced = np.concatenate((x[:cut], x[cut + 27:])).astype(np.int16)   # 27 樣本 ≈ 300 Hz 半週期
    jump = np.abs(np.diff(spliced.astype(np.float32)))[cut - 2:cut + 2].max()
    y, n = audio_declick.declick(spliced)
    assert n == 1
    assert np.abs(np.diff(y.astype(np.float32)))[cut - 40:cut + 40].max() < 0.5 * jump
    changed = np.flatnonzero(y != spliced)
    assert changed.min() > cut - 80 and changed.max() < cut + 80                # 只動接縫附近


def test_smooth_path():
    assert audio_declick.smooth_path("/dev/shm/audio_cache/m_1.ogg") == "/dev/shm/audio_cache/m_1.smooth.ogg"


def _clicky(sec=12.0, sr=16000, seed=3):
    """語音般的訊號＋各種位置的跳變（含落在分段邊界附近的），給分段版對照整段版。"""
    rng = np.random.default_rng(seed)
    x = _tone(sec, sr, 220.0, 6000.0) + rng.standard_normal(int(sec * sr)) * 300
    for pos in rng.integers(300, len(x) - 300, 40):
        x[pos:] += rng.choice([-1, 1]) * rng.uniform(4000, 9000)      # 階梯跳變（掉封包）
        x[pos:] *= 0.8
    for pos in (16000, 31990, 32000, 32010, 48005, 63999):          # 正好在 1 s 分段邊界附近
        x[pos:pos + 40] += 15000                                       # 爆音
    return np.clip(x, -32768, 32767).astype(np.int16)


def _run_blocks(x, block_s, margin_s, read_size_jitter=False):
    out, pos = [], [0]

    def read(n):
        if read_size_jitter:
            n = max(1, n // 3)
        chunk = x[pos[0]:pos[0] + n]
        pos[0] += len(chunk)
        return chunk

    n = audio_declick.declick_blocks(read, out.append, block_s=block_s, margin_s=margin_s)
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int16), n


def test_block_declick_matches_whole_file_declick():
    """2026-11-14：4 小時錄音整段 declick 記憶體峰值約 5 GB → 改分段串流，輸出必須跟整段一模一樣。"""
    x = _clicky()
    y_all, n_all = audio_declick.declick(x)
    assert n_all >= 5
    for block_s, margin_s, jitter in ((1.0, 0.1, False), (2.5, 0.05, True), (30.0, 1.0, False)):
        y_blk, n_blk = _run_blocks(x, block_s, margin_s, jitter)
        assert len(y_blk) == len(x)
        assert np.array_equal(y_blk, y_all), (block_s, margin_s, int(np.flatnonzero(y_blk != y_all)[0]))
        assert n_blk == n_all


def test_block_declick_short_and_empty_input():
    y, n = _run_blocks(np.zeros(0, dtype=np.int16), 1.0, 0.1)
    assert len(y) == 0 and n == 0
    x = _tone(0.03).astype(np.int16)                                  # < 1000 樣本：原樣輸出
    y, n = _run_blocks(x, 1.0, 0.1)
    assert np.array_equal(y, x) and n == 0
