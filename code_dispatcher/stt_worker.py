# -*- coding: utf-8 -*-
"""
stt_worker.py — Hailo-10H Whisper 語音轉文字 (STT) 獨立子行程 (2026-10-27，方案 B)。

為什麼要獨立行程：
  py-spy 實測錄音中 uvicorn 行程約 80% 時間有 STT 執行緒持有 GIL：
  (1) 每段都重新建立 VDevice + Speech2Text (載入 Whisper HEF)；(2) HailoRT 的 generate_all_text 執行期間不釋放 GIL。
  結果 /api/status 最長 18 s 無回應、網頁卡頓。GIL 是每個行程各一把，推論移到子行程後 uvicorn 不再被卡住。

設計：
  - 推論仍在 Hailo-10H NPU 上執行；子行程只負責持有 VDevice 與 Speech2Text。
  - 子行程常駐待命 (不佔 NPU)。第一次收到音訊才開 NPU 並載入 Whisper，整段錄音共用同一個引擎。
  - 閒置 IDLE_RELEASE_SEC 秒，或主行程要用 Hailo LLM 前呼叫 release()，就釋放 NPU 給 hailo-ollama
    (Hailo-10H 的 VDevice 一次只能給一個行程)。
  - 共用模式 (2026-10-29，見 npu_share.py)：hailo-ollama 以 HAILO_OLLAMA_VDEVICE_GROUP_ID 啟動時，VDevice 帶相同 group_id，
    Whisper 一直常駐 (不做閒置釋放，LLM 請求前也不釋放)，根治每次開關約 22 MB 的裝置記憶體洩漏。
  - NPU 開不起來時回傳 error，由 voice_pipeline 走原本的 CPU 備援流程 (子行程內不做 CPU 推論)。
  - 子行程異常結束時，下一次呼叫自動重啟。

協定：stdin/stdout 上的 [4 bytes big-endian 長度][pickle] 訊框。子行程的 print/log 全部導到 stderr (進 journal)。
"""

import os
import pickle
import queue
import select
import struct
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional
import logging
_log = logging.getLogger(__name__)

IDLE_RELEASE_SEC = float(os.environ.get("PI5_STT_IDLE_RELEASE_SEC", "10"))
_HERE = os.path.dirname(os.path.abspath(__file__))


def _write_frame(f, obj: Any) -> None:
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    f.write(struct.pack(">I", len(data)) + data)
    f.flush()


# Windows 的 select() 只接受 socket，對 pipe 會 OSError（WinError 10038／10093）。主行程讀回覆、子行程等命令都會用到，
# 兩端都要改：不能 select pipe 時，主行程用背景執行緒讀＋逾時（_read_chunk_with_timeout），子行程用常駐執行緒收訊框（_FrameInbox）。
# POSIX（Pi）一律用 select，行為不變。PI5_STT_SELECT_PIPES=0／1 可強制指定（子行程會繼承環境變數；測試在 Mac 上用它走 Windows 路徑）。
def _select_pipes_from_env() -> bool:
    return {"0": False, "1": True}.get(os.environ.get("PI5_STT_SELECT_PIPES", ""), os.name != "nt")


_SELECT_PIPES = _select_pipes_from_env()


def _read_chunk_with_timeout(fd: int, n: int, timeout: float) -> bytes:
    """讀最多 n bytes，timeout 秒內沒有資料就 TimeoutError。逾時後呼叫端會砍掉子行程，pipe 關閉，卡在 os.read 的執行緒就會結束。"""
    result: Dict[str, Any] = {}

    def reader() -> None:
        try:
            result["data"] = os.read(fd, n)
        except OSError as e:
            result["error"] = e
    t = threading.Thread(target=reader, daemon=True, name="stt-pipe-read")
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError("stt worker reply timeout")
    if "error" in result:
        raise result["error"]
    return result["data"]


def _read_exact(fd: int, n: int, deadline: Optional[float]) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("stt worker reply timeout")
            if not _SELECT_PIPES:
                chunk = _read_chunk_with_timeout(fd, n - len(buf), remaining)
                if not chunk:
                    raise EOFError("stt worker closed the pipe")
                buf += chunk
                continue
            r, _, _ = select.select([fd], [], [], remaining)
            if not r:
                raise TimeoutError("stt worker reply timeout")
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            raise EOFError("stt worker closed the pipe")
        buf += chunk
    return bytes(buf)


def _read_frame(fd: int, deadline: Optional[float] = None) -> Any:
    (size,) = struct.unpack(">I", _read_exact(fd, 4, deadline))
    return pickle.loads(_read_exact(fd, size, deadline))


class _FrameInbox:
    """子行程收命令用：get(timeout) 回傳下一個訊框；timeout 秒內沒有命令 → TimeoutError（None = 一直等）；主行程關掉 pipe → EOFError。
    能 select pipe 的平台（POSIX）：select 等到有資料再讀，跟原本一樣。
    不能的平台（Windows）：常駐 daemon 執行緒一直讀訊框放進 queue；EOF 或讀取錯誤也放進 queue 由 get 拋出，之後執行緒結束。"""

    def __init__(self, fd: int, use_select: Optional[bool] = None) -> None:
        self._fd = fd
        self._select = _SELECT_PIPES if use_select is None else use_select
        self._q: Optional[queue.Queue] = None
        self._failed: Optional[BaseException] = None
        if not self._select:
            self._q = queue.Queue()
            threading.Thread(target=self._pump, daemon=True, name="stt-child-inbox").start()

    def _pump(self) -> None:
        assert self._q is not None
        while True:
            try:
                frame = _read_frame(self._fd)
            except BaseException as e:          # EOFError、OSError、訊框損毀：交給 get 拋出
                self._q.put(_InboxError(e))
                return
            self._q.put(frame)

    def get(self, timeout: Optional[float]) -> Any:
        if self._failed is not None:
            raise self._failed
        if self._q is None:
            r, _, _ = select.select([self._fd], [], [], timeout)
            if not r:
                raise TimeoutError("no command")
            return _read_frame(self._fd)
        try:
            item = self._q.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError("no command") from None
        if isinstance(item, _InboxError):
            self._failed = item.exc
            raise item.exc
        return item


class _InboxError:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc


# --------------------------------------------------------------------------- 子行程


def _child_main() -> None:
    proto_out = os.fdopen(os.dup(1), "wb")   # 協定專用的 stdout
    os.dup2(2, 1)                            # 其餘 print 一律寫到 stderr，避免汙染協定
    sys.stdout = sys.stderr
    in_fd = sys.stdin.fileno()
    for p in (_HERE, os.path.dirname(_HERE)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from hailo_whisper.engine import HailoWhisperEngine
    from npu_share import shared_group

    engine = None
    engine_group: Optional[str] = None   # 共用模式的 group_id；None = 獨占 VDevice
    last_use = time.monotonic()

    def release() -> None:
        nonlocal engine, engine_group
        if engine is None:
            return
        for obj in (getattr(engine, "_s2t", None), getattr(engine, "_vdevice", None)):
            try:
                if obj is not None:
                    obj.release()
            except Exception as e:
                print(f"[SttWorker] release warning: {e}", flush=True)
        engine, engine_group = None, None
        print("[SttWorker] Hailo NPU released", flush=True)

    inbox = _FrameInbox(in_fd)
    print(f"[SttWorker] ready (pid {os.getpid()})", flush=True)
    while True:
        timeout = IDLE_RELEASE_SEC if engine is not None and engine_group is None else None   # 共用模式不做閒置釋放
        try:
            cmd, payload = inbox.get(timeout)
        except TimeoutError:
            if engine is not None and time.monotonic() - last_use >= IDLE_RELEASE_SEC:
                release()
            continue
        except EOFError:
            break
        if cmd == "exit":
            release()
            _write_frame(proto_out, {"ok": True})
            break
        if cmd == "release":
            exclusive_only = bool(payload and payload.get("exclusive_only"))
            if not (exclusive_only and engine_group):   # 共用模式下 LLM 不需要 STT 讓出 NPU
                release()
            _write_frame(proto_out, {"ok": True, "engine_open": engine is not None})
            continue
        if cmd == "ping":
            _write_frame(proto_out, {"ok": True, "engine_open": engine is not None, "shared_group": engine_group})
            continue
        if cmd == "transcribe":
            audio, language = payload
            try:
                if engine is None:
                    t0 = time.perf_counter()
                    group = shared_group(force_refresh=True)
                    engine = HailoWhisperEngine(group_id=group)
                    engine_group = group
                    if not engine.is_hardware_accelerated():
                        release()
                        _write_frame(proto_out, {"ok": False, "error": "hailo_unavailable"})
                        continue
                    mode = f"shared group {group}" if group else "exclusive"
                    print(f"[SttWorker] Hailo NPU opened ({mode}), Whisper loaded ({(time.perf_counter() - t0) * 1000:.0f} ms)", flush=True)
                res = engine.transcribe(audio, language=language, initial_prompt=None, temperature=0.0)
                _write_frame(proto_out, {"ok": True, "result": res, "shared_group": engine_group})
            except Exception as e:
                release()
                _write_frame(proto_out, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            last_use = time.monotonic()
            continue
        _write_frame(proto_out, {"ok": False, "error": f"unknown command {cmd!r}"})


# --------------------------------------------------------------------------- 主行程端


class SttWorker:
    """主行程端代理：所有呼叫互斥 (一次一段音訊)，子行程掛掉會自動重啟。"""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._busy = False
        self._engine_group: Optional[str] = None   # 子行程的 Whisper 以共用模式開著時為 group_id

    def is_busy(self) -> bool:
        return self._busy

    def _ensure(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", os.path.abspath(__file__), "--child"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, cwd=_HERE)
        return self._proc

    def shared_group(self) -> Optional[str]:
        return self._engine_group

    def _kill(self) -> None:
        self._engine_group = None
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=5)
            except Exception as _exc:
                _log.debug("stt_worker.py:177 略過：%s", _exc)
        self._proc = None

    def _call(self, cmd: str, payload: Any, timeout: float) -> Dict[str, Any]:
        proc = self._ensure()
        try:
            _write_frame(proc.stdin, (cmd, payload))
            return _read_frame(proc.stdout.fileno(), time.monotonic() + timeout)
        except (TimeoutError, EOFError, BrokenPipeError, OSError) as e:
            self._kill()   # 狀態不明 → 砍掉，下次重啟 (子行程結束時 VDevice 隨之釋放)
            raise RuntimeError(f"stt worker {cmd} failed: {e}") from e

    def transcribe(self, audio: Any, language: Optional[str] = None) -> Dict[str, Any]:
        """回傳 HailoWhisperEngine.transcribe() 的 dict；NPU 不可用或失敗時 raise RuntimeError。"""
        try:
            import numpy as np
            if isinstance(audio, np.ndarray):
                timeout = 60.0 + 1.5 * len(audio) / 16000.0
            elif isinstance(audio, bytes):
                timeout = 60.0 + 1.5 * len(audio) / 32000.0
            else:
                timeout = 4 * 3600.0 + 600.0   # 檔案路徑 (整段母帶，最長 4 小時) 長度未知
        except Exception:
            timeout = 4 * 3600.0 + 600.0
        with self._lock:
            self._busy = True
            try:
                reply = self._call("transcribe", (audio, language), timeout)
            finally:
                self._busy = False
        if not reply.get("ok"):
            self._engine_group = None          # 子行程出錯時已釋放 NPU
            raise RuntimeError(reply.get("error") or "stt worker error")
        self._engine_group = reply.get("shared_group")
        return reply["result"]

    def release(self, timeout: float = 15.0, exclusive_only: bool = False) -> None:
        """釋放 NPU (子行程保留待命)。沒有子行程時什麼都不做。
        exclusive_only=True (LLM 請求前)：Whisper 以共用模式開著時不釋放，也不等鎖 (LLM 不必等正在跑的 STT)。"""
        if exclusive_only and self._engine_group:
            return
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return
            try:
                reply = self._call("release", {"exclusive_only": exclusive_only}, timeout)
                if not reply.get("engine_open"):
                    self._engine_group = None
            except RuntimeError as e:
                print(f"[SttWorker] release: {e}")

    def _shutdown_locked(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._call("exit", None, 10.0)
            except RuntimeError as _exc:
                _log.debug("stt_worker.py:233 略過：%s", _exc)
        self._kill()

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown_locked()

    @contextmanager
    def paused(self) -> Iterator[None]:
        """結束子行程並在 with 區塊內擋住所有 STT 呼叫 (NPU 群組重置用)；離開後下一次呼叫自動重啟子行程。"""
        with self._lock:
            self._shutdown_locked()
            yield


stt_worker = SttWorker()


if __name__ == "__main__" and "--child" in sys.argv:
    _child_main()
