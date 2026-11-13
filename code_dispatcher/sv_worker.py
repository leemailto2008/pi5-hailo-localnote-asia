# -*- coding: utf-8 -*-
"""
sv_worker.py — 錄音中的即時逐字稿用 SenseVoice（2026-11-13，使用者要求「錄音中也用 SenseVoice」）。

SenseVoiceSmall int8（sherpa-onnx，CPU）在獨立子行程常駐，一次辨識一個即時切片（停頓處切 4–9.5 秒）。
  - 為什麼要子行程：sherpa-onnx 推論期間持有 GIL（11-10 分說話人實測會卡住整個 API），放在 uvicorn 行程網頁會卡。
  - CPU：子行程綁 CPU 2、3、nice 10、LIVE_THREADS 執行緒；錄音的 ffmpeg 與 PipeWire／bluetoothd 綁 0、1（voice_pipeline）。
  - 藍牙收音也可用（11-13 實測封包到達與補靜音都沒變差，見 voice_pipeline.LIVE_SV_ON_BT）；由 voice_pipeline.live_asr_engine 決定。
  - 子行程閒置 IDLE_EXIT_SEC 秒自己結束（釋放模型記憶體），下一次呼叫自動重啟；會議錄完主行程也會叫它結束。
  - 模型、語言與後處理（OpenCC s2twp＋台灣用字修正）與錄音後的高精度逐字稿（refine_transcript）相同，只是不切句、不分說話人。
協定與 stt_worker 相同：stdin/stdout 上的 [4 bytes big-endian 長度][pickle] 訊框；子行程的 print 全部導到 stderr。
"""

import os
import select
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

from stt_worker import _read_frame, _write_frame

LIVE_THREADS = int(os.environ.get("PI5_LIVE_SV_THREADS", "2"))
LIVE_CPUS = {2, 3}
IDLE_EXIT_SEC = float(os.environ.get("PI5_LIVE_SV_IDLE_EXIT_SEC", "60"))
_HERE = os.path.dirname(os.path.abspath(__file__))


def live_label() -> str:
    """網頁「完整逐字稿」區顯示的 ASR 名稱。"""
    from refine_transcript import ASR_LANGUAGE
    return f"SenseVoiceSmall int8（sherpa-onnx，CPU {LIVE_THREADS} 執行緒，語言 {ASR_LANGUAGE}，ITN；即時切片）"


LIVE_POST_LABEL = "OpenCC s2twp＋台灣用字修正"


# --------------------------------------------------------------------------- 子行程


def _child_main() -> None:
    proto_out = os.fdopen(os.dup(1), "wb")   # 協定專用的 stdout
    os.dup2(2, 1)                            # 其餘 print 一律寫到 stderr，避免汙染協定
    sys.stdout = sys.stderr
    in_fd = sys.stdin.fileno()
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    try:
        os.sched_setaffinity(0, LIVE_CPUS & os.sched_getaffinity(0) or os.sched_getaffinity(0))
        os.nice(10)
    except (AttributeError, OSError) as e:   # 非 Linux 或權限不足：照跑，只是不綁核心
        print(f"[SvWorker] cpu affinity/nice not applied: {e}", flush=True)
    import numpy as np
    import sherpa_onnx
    from refine_transcript import ASR_LANGUAGE, SAMPLE_RATE, model_path
    from summary_utils import to_taiwan_traditional

    recognizer = None

    def load() -> float:
        nonlocal recognizer
        t0 = time.perf_counter()
        if recognizer is None:
            recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=model_path("asr"), tokens=model_path("tokens"), num_threads=LIVE_THREADS,
                language=ASR_LANGUAGE, use_itn=True)
            print(f"[SvWorker] SenseVoice loaded ({(time.perf_counter() - t0) * 1000:.0f} ms, pid {os.getpid()})", flush=True)
        return (time.perf_counter() - t0) * 1000

    print(f"[SvWorker] ready (pid {os.getpid()})", flush=True)
    while True:
        r, _, _ = select.select([in_fd], [], [], IDLE_EXIT_SEC)
        if not r:
            print("[SvWorker] idle, exiting", flush=True)
            break
        try:
            cmd, payload = _read_frame(in_fd)
        except EOFError:
            break
        if cmd == "exit":
            _write_frame(proto_out, {"ok": True})
            break
        try:
            if cmd == "load":
                _write_frame(proto_out, {"ok": True, "load_ms": round(load())})
            elif cmd == "transcribe":
                load()
                t0 = time.perf_counter()
                stream = recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, np.asarray(payload, dtype=np.float32))
                recognizer.decode_stream(stream)
                text = to_taiwan_traditional(stream.result.text.strip())
                _write_frame(proto_out, {"ok": True, "text": text, "lang": getattr(stream.result, "lang", ""),
                                         "emotion": getattr(stream.result, "emotion", ""),
                                         "inference_time_ms": round((time.perf_counter() - t0) * 1000)})
            else:
                _write_frame(proto_out, {"ok": False, "error": f"unknown command {cmd!r}"})
        except Exception as e:   # 單段失敗回報給主行程（主行程這段改走 Hailo Whisper），子行程繼續待命
            _write_frame(proto_out, {"ok": False, "error": f"{type(e).__name__}: {e}"})


# --------------------------------------------------------------------------- 主行程端


class SvWorker:
    """主行程端代理：所有呼叫互斥（一次一段音訊），子行程掛掉或閒置結束後下一次呼叫自動重啟。"""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def _ensure(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", os.path.abspath(__file__), "--child"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, cwd=_HERE)
        return self._proc

    def _kill(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as e:
                print(f"[SvWorker] kill: {e}")
        self._proc = None

    def _call(self, cmd: str, payload: Any, timeout: float) -> Dict[str, Any]:
        for attempt in (1, 2):   # 子行程剛好閒置結束（管線已關）時重啟再試一次
            proc = self._ensure()
            try:
                _write_frame(proc.stdin, (cmd, payload))
                reply = _read_frame(proc.stdout.fileno(), time.monotonic() + timeout)
            except (EOFError, BrokenPipeError) as e:
                self._kill()
                if attempt == 2:
                    raise RuntimeError(f"sv worker {cmd} failed: {e}") from e
                continue
            except (TimeoutError, OSError) as e:
                self._kill()   # 狀態不明 → 砍掉，下次重啟
                raise RuntimeError(f"sv worker {cmd} failed: {e}") from e
            if not reply.get("ok"):
                raise RuntimeError(reply.get("error") or f"sv worker {cmd} error")
            return reply
        raise RuntimeError(f"sv worker {cmd} failed")

    def warm_up(self) -> None:
        """錄音一開始先載入模型（約 1–2 s），第一個切片就不用等。失敗只記 log，切片時會再試。"""
        with self._lock:
            try:
                reply = self._call("load", None, 60.0)
                print(f"[SvWorker] warm up done ({reply.get('load_ms')} ms)")
            except RuntimeError as e:
                print(f"[SvWorker] warm up failed: {e}")

    def transcribe(self, audio: Any) -> Dict[str, Any]:
        """audio：16 kHz float32 單聲道。回傳 {"text", "inference_time_ms"}；失敗 raise RuntimeError。"""
        timeout = 60.0 + 1.5 * len(audio) / 16000.0
        with self._lock:
            return self._call("transcribe", audio, timeout)

    def shutdown(self) -> None:
        """會議錄完就結束子行程，釋放模型記憶體。"""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._call("exit", None, 10.0)
                except RuntimeError as e:
                    print(f"[SvWorker] exit: {e}")
            self._kill()


sv_worker = SvWorker()


if __name__ == "__main__" and "--child" in sys.argv:
    _child_main()
