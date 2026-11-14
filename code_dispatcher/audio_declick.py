# code_dispatcher/audio_declick.py
"""
回放用的跳音修平 (declick)，只處理「回放」檔，不影響 STT 與原始錄音。

背景 (2026-11-03 使用者測試，228，上班時段)：藍牙 SCO 封包到達率 94.4%。沒收到的封包不會補零，
音訊直接接上，接縫處就是一個階梯跳變；解碼錯誤的幀則是幾毫秒的爆音。回放時聽起來是一連串「喀」聲與雜訊。
缺掉的音訊補不回來，這裡只把跳變處 (相鄰樣本差 > 附近平均差 12 倍且 > 3000) 前後約 1.5 ms 改成平滑銜接，
爆音型 (該處能量明顯高於前後) 再加長到約 4 ms 並壓低。5 分鐘錄音約改動 0.3% 的樣本。

make_smooth_ogg() 在錄音結束、編碼完成後於背景執行：ffmpeg 解碼 → declick → ffmpeg 以 nice 編碼成 *.smooth.ogg。
"""
import os
import subprocess
import time
from typing import Tuple

import numpy as np

SMOOTH_TIMEOUT_S = 3600   # 整個修平工作的上限 (背景、nice 10；新錄音開始時會被停掉)


def _events(x: np.ndarray, ratio: float, floor: float, gap: int):
    d = np.abs(np.diff(x))
    local = np.convolve(d, np.ones(400, dtype=np.float32) / 400, mode="same") + 1.0
    idx = np.flatnonzero((d > ratio * local) & (d > floor))
    if len(idx) == 0:
        return []
    splits = np.flatnonzero(np.diff(idx) > gap) + 1
    return [(int(g[0]), int(g[-1]) + 1) for g in np.split(idx, splits)]


def declick(pcm: np.ndarray, sr: int = 16000, ratio: float = 12.0, floor: float = 3000.0,
            half_ms: float = 1.5, burst_ms: float = 4.0) -> Tuple[np.ndarray, int]:
    """int16 單聲道 → (修平後 int16, 修了幾處)。"""
    if len(pcm) < 1000:
        return pcm.copy(), 0
    y, ev = _declick_events(pcm, sr, ratio, floor, half_ms, burst_ms)
    return np.clip(np.round(y), -32768, 32767).astype(np.int16), len(ev)


def _declick_events(pcm: np.ndarray, sr: int, ratio: float, floor: float, half_ms: float, burst_ms: float):
    """declick 的本體：回傳 (修平後 float32, 找到的跳變 [(起, 迄)])。"""
    x = pcm.astype(np.float32)
    n = len(x)
    w, wb = max(4, int(sr * half_ms / 1000)), max(8, int(sr * burst_ms / 1000))
    y = x.copy()
    ev = _events(x, ratio, floor, gap=2 * w)
    for a, b in ev:
        ctx = 4 * wb
        if a - ctx < 0 or b + ctx >= n:
            continue
        mid = x[a - wb:b + wb]
        side = np.concatenate((x[a - ctx:a - wb], x[b + wb:b + ctx]))
        burst = np.sqrt((mid ** 2).mean()) > 2.0 * (np.sqrt((side ** 2).mean()) + 1.0)
        h = wb if burst else w
        s, e = a - h, b + h
        ramp = np.linspace(y[s], y[e], e - s + 1, dtype=np.float32)
        if burst:                      # 爆音那段保留一點原始內容 (壓低 12 dB)，聽起來比完全換成直線自然
            ramp = ramp + 0.25 * (x[s:e + 1] - np.linspace(x[s], x[e], e - s + 1, dtype=np.float32))
        y[s:e + 1] = ramp
    return y, ev


# 分段處理 (2026-11-14)：4 小時會議整段解碼成 float32 再算差分、滑動平均、遮罩，記憶體峰值約 5 GB
# (8 GB 的 .228 整機 RAM 峰值 6753 MB、swap 多用 980 MB)。改成每次 BLOCK_S 秒、前後各多看 MARGIN_S 秒，
# 跳變偵測 (400 樣本滑動平均) 與修平 (前後各約 16 ms 內容) 都在邊界內完成，輸出與整段處理相同 (test_audio_declick)。
BLOCK_S, MARGIN_S = 30.0, 1.0


def declick_blocks(read_samples, write_samples, sr: int = 16000, block_s: float = BLOCK_S,
                   margin_s: float = MARGIN_S) -> int:
    """串流版 declick：read_samples(n) 回傳最多 n 個 int16 樣本 (空陣列 = 結束)，write_samples(int16 陣列) 輸出修平後的樣本。
    回傳修了幾處。記憶體只跟 block_s＋2×margin_s 有關。"""
    block, margin = int(block_s * sr), int(margin_s * sr)
    buf = np.zeros(0, dtype=np.int16)   # buf[0] 是絕對位置 buf_start 的樣本
    buf_start, out_pos, total, eof = 0, 0, 0, False
    while True:
        while not eof and buf_start + len(buf) < out_pos + block + margin:
            chunk = read_samples(block)
            if len(chunk) == 0:
                eof = True
            else:
                buf = np.concatenate((buf, chunk))
        end = min(out_pos + block, buf_start + len(buf)) if not eof else buf_start + len(buf)
        if end <= out_pos:
            return total
        ext_start = max(buf_start, out_pos - margin)
        ext_end = min(buf_start + len(buf), end + margin)
        ext = buf[ext_start - buf_start:ext_end - buf_start]
        if len(ext) < 1000:
            y, ev = ext.astype(np.float32), []
        else:
            y, ev = _declick_events(ext, sr, 12.0, 3000.0, 1.5, 4.0)
        core = slice(out_pos - ext_start, end - ext_start)
        write_samples(np.clip(np.round(y[core]), -32768, 32767).astype(np.int16))
        total += sum(1 for a, _ in ev if out_pos <= ext_start + a < end)
        out_pos = end
        keep_from = max(buf_start, out_pos - margin)
        buf = buf[keep_from - buf_start:]
        buf_start = keep_from
        if eof and out_pos >= buf_start + len(buf):
            return total


def smooth_path(ogg_path: str) -> str:
    root, ext = os.path.splitext(ogg_path)
    return f"{root}.smooth{ext or '.ogg'}"


def make_smooth_ogg(src: str, dst: str = "", sr: int = 16000, bitrate: str = "64k") -> Tuple[bool, int]:
    """原始錄音 → 修平順的回放檔。回傳 (成功與否, 修了幾處)；失敗時不留半成品。
    位元率與錄音母帶相同 (voice_pipeline 的 encoder 是 libopus 64k)，比較兩者時只差在修平，不差在編碼品質。"""
    dst = dst or smooth_path(src)
    tmp = dst + ".part"
    dec = enc = None
    deadline = time.monotonic() + SMOOTH_TIMEOUT_S
    try:
        # 解碼 → 分段修平 → 編碼，三者串流接起來：記憶體不隨錄音長度增加 (見 BLOCK_S 註解)。
        dec = subprocess.Popen(["nice", "-n", "10", "ffmpeg", "-v", "error", "-i", src, "-ac", "1", "-ar", str(sr),
                                "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        enc = subprocess.Popen(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1",
                                "-i", "-", "-c:a", "libopus", "-b:a", bitrate, "-f", "ogg", tmp],
                               stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def read_samples(n_samples: int) -> np.ndarray:
            if time.monotonic() > deadline:
                raise TimeoutError(f"超過 {SMOOTH_TIMEOUT_S} s")
            data = dec.stdout.read(n_samples * 2)
            return np.frombuffer(data[:len(data) // 2 * 2], dtype="<i2")

        def write_samples(y: np.ndarray) -> None:
            enc.stdin.write(y.astype("<i2").tobytes())

        n = declick_blocks(read_samples, write_samples, sr=sr)
        enc.stdin.close()
        rc_dec = dec.wait(timeout=60)
        rc_enc = enc.wait(timeout=max(60.0, deadline - time.monotonic()))
        if rc_dec != 0 or rc_enc != 0:
            raise RuntimeError(f"ffmpeg 解碼 rc={rc_dec}、編碼 rc={rc_enc}")
        os.replace(tmp, dst)
        return True, n
    except Exception as e:
        print(f"[Declick] smooth playback file failed: {e}")
        for p in (dec, enc):
            if p is not None and p.poll() is None:
                p.kill()
                p.wait()
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, 0


# ---- 背景產生：獨立行程 (不佔服務的 GIL)，新錄音開始時會被停掉 (錄音中不做運算) ----
_bg_proc = None


def start_smooth_job(src: str):
    """錄音檔完成後在背景產生 *.smooth.ogg；前一個還在跑就先停掉。"""
    global _bg_proc
    stop_smooth_job()
    try:
        _bg_proc = subprocess.Popen(["nice", "-n", "10", "python3", os.path.abspath(__file__), src],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[Declick] cannot start smooth job: {e}")
        _bg_proc = None


def stop_smooth_job():
    global _bg_proc
    if _bg_proc is not None and _bg_proc.poll() is None:
        try:
            _bg_proc.kill()
        except Exception:
            pass
    _bg_proc = None


if __name__ == "__main__":
    import sys
    ok, n = make_smooth_ogg(sys.argv[1])
    print(f"[Declick] {'ok' if ok else 'failed'}: {n} clicks smoothed -> {smooth_path(sys.argv[1])}")
