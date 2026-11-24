"""stt_worker／sv_worker 在不能 select() pipe 的平台（Windows）也要能用：主行程讀回覆、子行程等命令，兩端都不能 select pipe。

2026-11-24（localnote@mac，N1）：重做 bd23da2。bd23da2 只改了主行程，子行程 _child_main 仍 select(stdin pipe)，
PC 在 Windows 跑這個檔案時 WinError 10093 FAIL（Mac 上用 monkeypatch 模擬只碰得到 pytest 主行程，碰不到子行程）。
這次：
  - 主行程：_SELECT_PIPES=False 時 _read_exact 用背景執行緒讀＋逾時。
  - 子行程：_FrameInbox 用常駐執行緒收訊框；stt_worker 與 sv_worker 的 _child_main 都改用它。
  - 模擬範圍：主行程用 monkeypatch 把 select.select 換成「不是 socket 就丟 OSError(10093)」；
    子行程另外用 tmp 目錄的 sitecustomize.py（經 PYTHONPATH）做同樣的替換，並設 PI5_STT_SELECT_PIPES=0。
    test_emulation_reaches_child 確認這個模擬真的碰得到子行程（舊的 select 路徑在模擬下會失敗）。
未在 Windows 實機驗證（Mac 上模擬）。
"""
import os
import pickle
import select
import socket
import struct
import textwrap
import threading
import time

import numpy as np
import pytest

import stt_worker as sw
import sv_worker as svw

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.join(os.path.dirname(HERE), "code_dispatcher")
WINERR = 10093

# 子行程用的 Windows select 模擬：只接受 socket（有 fileno 的 socket 物件，或 socket 的 fd），其餘丟 OSError(10093)。
WIN_SELECT_SITECUSTOMIZE = textwrap.dedent("""
    import os, select, socket, stat
    _orig = select.select
    def _is_socket(x):
        if isinstance(x, socket.socket):
            return True
        fd = x if isinstance(x, int) else x.fileno()
        try:
            return stat.S_ISSOCK(os.fstat(fd).st_mode)
        except OSError:
            return False
    def _win_select(r, w, x, *timeout):
        for obj in list(r) + list(w) + list(x):
            if not _is_socket(obj):
                raise OSError({winerr}, "emulated Windows select: not a socket")
        return _orig(r, w, x, *timeout)
    select.select = _win_select
""").format(winerr=WINERR)


def _win_select(r, w, x, *timeout):
    import stat
    for obj in list(r) + list(w) + list(x):
        fd = obj if isinstance(obj, int) else obj.fileno()
        if not stat.S_ISSOCK(os.fstat(fd).st_mode):
            raise OSError(WINERR, "emulated Windows select: not a socket")
    return _ORIG_SELECT(r, w, x, *timeout)


_ORIG_SELECT = select.select


@pytest.fixture()
def windows_select(monkeypatch):
    """主行程：select 不接受 pipe，並走不 select 的路徑（_SELECT_PIPES=False）。Windows 上本來就是真的 Windows select，不替換。"""
    if os.name != "nt":
        monkeypatch.setattr(select, "select", _win_select)
    monkeypatch.setattr(sw, "_SELECT_PIPES", False)


@pytest.fixture()
def windows_child(tmp_path, monkeypatch):
    """子行程：經 PYTHONPATH 載入 sitecustomize 模擬 Windows select，PI5_STT_SELECT_PIPES=0 走不 select 的路徑。"""
    site = tmp_path / "winsite"
    site.mkdir()
    (site / "sitecustomize.py").write_text(WIN_SELECT_SITECUSTOMIZE, encoding="utf-8")
    old = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", str(site) + (os.pathsep + old if old else ""))
    monkeypatch.setenv("PI5_STT_SELECT_PIPES", "0")
    return site


@pytest.fixture(params=[True, False], ids=["select", "thread"])
def read_mode(request, monkeypatch):
    if request.param and os.name == "nt":
        pytest.skip("Windows 的 select() 不能用在 pipe")
    monkeypatch.setattr(sw, "_SELECT_PIPES", request.param)
    if not request.param and os.name != "nt":
        monkeypatch.setattr(select, "select", _win_select)
    return request.param


# --------------------------------------------------------------------------- 主行程端：_read_frame


def test_frame_roundtrip_with_deadline(read_mode):
    r, wfd = os.pipe()
    with os.fdopen(wfd, "wb") as f:
        sw._write_frame(f, ("transcribe", (np.arange(3, dtype=np.float32), "en")))
    try:
        cmd, (arr, lang) = sw._read_frame(r, time.monotonic() + 5)
    finally:
        os.close(r)
    assert cmd == "transcribe" and lang == "en" and arr.tolist() == [0, 1, 2]


def test_timeout_when_no_data(read_mode):
    r, wfd = os.pipe()
    try:
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            sw._read_frame(r, time.monotonic() + 0.3)
        assert time.monotonic() - t0 < 3
    finally:
        os.close(wfd)                   # 關掉寫端：thread 模式卡在 os.read 的背景執行緒會收到 EOF 結束
        os.close(r)


def test_eof_when_writer_closes(read_mode):
    r, wfd = os.pipe()
    os.close(wfd)
    try:
        with pytest.raises(EOFError):
            sw._read_frame(r, time.monotonic() + 5)
    finally:
        os.close(r)


def test_slow_writer_in_chunks(read_mode):
    """訊框分好幾次寫進來（大音訊時常見）：要讀滿長度才回傳。"""
    r, wfd = os.pipe()
    f = os.fdopen(wfd, "wb")
    data = pickle.dumps({"ok": True, "text": "x" * 5000})
    frame = struct.pack(">I", len(data)) + data

    def writer():
        for i in range(0, len(frame), 1000):
            f.write(frame[i:i + 1000])
            f.flush()
            time.sleep(0.01)
        f.close()
    t = threading.Thread(target=writer)
    t.start()
    try:
        assert sw._read_frame(r, time.monotonic() + 5)["text"] == "x" * 5000
    finally:
        t.join(5)
        os.close(r)


@pytest.mark.skipif(os.name == "nt", reason="這是 Mac／Linux 上的 Windows 模擬本身的檢查；Windows 上 os.fstat 不能用在 socket")
def test_emulated_select_rejects_pipe_but_accepts_socket():
    """模擬本身：pipe 丟 10093、socket 照常（確認模擬沒有把所有東西都擋掉，也沒有放過 pipe）。"""
    r, wfd = os.pipe()
    a, b = socket.socketpair()
    try:
        with pytest.raises(OSError) as ei:
            _win_select([r], [], [], 0)
        assert ei.value.errno == WINERR
        assert _win_select([a], [], [], 0) == ([], [], [])
    finally:
        for fd in (r, wfd):
            os.close(fd)
        a.close()
        b.close()


def test_select_pipes_default_by_platform(monkeypatch):
    monkeypatch.delenv("PI5_STT_SELECT_PIPES", raising=False)
    assert sw._select_pipes_from_env() is (os.name != "nt")
    for v, want in (("0", False), ("1", True), ("", os.name != "nt"), ("x", os.name != "nt")):
        monkeypatch.setenv("PI5_STT_SELECT_PIPES", v)
        assert sw._select_pipes_from_env() is want, v


# --------------------------------------------------------------------------- 子行程端：_FrameInbox


@pytest.fixture(params=[True, False], ids=["select", "thread"])
def inbox_mode(request, monkeypatch):
    if request.param and os.name == "nt":
        pytest.skip("Windows 的 select() 不能用在 pipe")
    if not request.param and os.name != "nt":
        monkeypatch.setattr(select, "select", _win_select)
    return request.param


def test_inbox_frames_in_order_then_eof(inbox_mode):
    r, wfd = os.pipe()
    inbox = sw._FrameInbox(r, use_select=inbox_mode)
    with os.fdopen(wfd, "wb") as f:
        for i in range(3):
            sw._write_frame(f, ("ping", i))
    try:
        assert [inbox.get(5) for _ in range(3)] == [("ping", 0), ("ping", 1), ("ping", 2)]
        with pytest.raises(EOFError):
            inbox.get(5)
        with pytest.raises(EOFError):     # 之後再叫也一樣是 EOF（主迴圈 break 前不會卡住）
            inbox.get(0.1)
    finally:
        os.close(r)


def test_inbox_timeout_then_frame(inbox_mode):
    """閒置逾時（stt 子行程據此釋放 NPU、sv 子行程據此結束）不能吃掉之後才到的命令。"""
    r, wfd = os.pipe()
    inbox = sw._FrameInbox(r, use_select=inbox_mode)
    f = os.fdopen(wfd, "wb")
    try:
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            inbox.get(0.2)
        assert 0.15 <= time.monotonic() - t0 < 3
        sw._write_frame(f, ("release", {"exclusive_only": True}))
        assert inbox.get(5) == ("release", {"exclusive_only": True})
    finally:
        f.close()
        os.close(r)


def test_inbox_none_timeout_waits(inbox_mode):
    r, wfd = os.pipe()
    inbox = sw._FrameInbox(r, use_select=inbox_mode)
    f = os.fdopen(wfd, "wb")

    def later():
        time.sleep(0.2)
        sw._write_frame(f, ("exit", None))
    t = threading.Thread(target=later)
    t.start()
    try:
        assert inbox.get(None) == ("exit", None)
    finally:
        t.join(5)
        f.close()
        os.close(r)


def test_inbox_thread_mode_never_selects(monkeypatch):
    calls = []
    monkeypatch.setattr(select, "select", lambda *a: calls.append(a) or _ORIG_SELECT(*a))
    r, wfd = os.pipe()
    inbox = sw._FrameInbox(r, use_select=False)
    try:
        with pytest.raises(TimeoutError):
            inbox.get(0.05)
    finally:
        os.close(wfd)
        os.close(r)
    assert calls == []


# --------------------------------------------------------------------------- 真的子行程（Windows 模擬碰得到子行程）


def test_emulation_reaches_child(windows_child, windows_select, monkeypatch):
    """反證：子行程若照舊 select（PI5_STT_SELECT_PIPES=1），在模擬下會 10093 失敗 → 主行程拿到 EOF。
    這證明 sitecustomize 的模擬確實作用在子行程（bd23da2 當時的模擬碰不到子行程）。"""
    monkeypatch.setenv("PI5_STT_SELECT_PIPES", "1")
    w = sw.SttWorker()
    try:
        with pytest.raises(RuntimeError, match="closed the pipe|EOF"):
            w._call("ping", None, 30)
    finally:
        w.shutdown()


def test_stt_worker_ping_release_restart_under_windows(windows_child, windows_select):
    """主行程、子行程都在 Windows 模擬下：ping、release、子行程被砍後自動重啟，都正常。"""
    w = sw.SttWorker()
    try:
        assert w._call("ping", None, 30)["ok"] is True
        w.release()
        assert w._proc is not None and w._proc.poll() is None
        w._proc.kill()
        w._proc.wait()
        assert w._call("ping", None, 30)["engine_open"] is False
    finally:
        w.shutdown()
    assert w._proc is None


def _hailo_present() -> bool:
    try:
        import hailo_platform  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(_hailo_present(), reason="有 Hailo 的機器上會真的開 NPU，改由 HIL 測試涵蓋")
def test_stt_worker_transcribe_without_npu_under_windows(windows_child, windows_select):
    w = sw.SttWorker()
    try:
        with pytest.raises(RuntimeError, match="hailo_unavailable|ModuleNotFoundError|ImportError"):
            w.transcribe(np.zeros(1600, dtype=np.float32))
        assert w._proc is not None and w._proc.poll() is None          # 子行程仍在待命
        assert w._call("ping", None, 30)["ok"] is True
    finally:
        w.shutdown()


@pytest.mark.skipif(not hasattr(__import__("signal"), "SIGSTOP"), reason="要用 SIGSTOP 讓子行程停住不回應（Windows 沒有）")
def test_stt_worker_reply_timeout_under_windows(windows_child, windows_select):
    """主行程在 Windows 路徑下的逾時：子行程不回應 → TimeoutError → 砍掉子行程、下一次自動重啟。"""
    w = sw.SttWorker()
    try:
        w._ensure()
        import signal
        os.kill(w._proc.pid, signal.SIGSTOP)
        t0 = time.monotonic()
        with pytest.raises(RuntimeError, match="timeout"):
            w._call("ping", None, 0.5)
        assert time.monotonic() - t0 < 10
        assert w._proc is None
        assert w._call("ping", None, 30)["ok"] is True
    finally:
        w.shutdown()


# sv_worker 的子行程需要 sherpa_onnx 與模型；這裡放一個假的 sherpa_onnx（只在這個子行程的 PYTHONPATH），
# 讓真的 sv_worker._child_main 主迴圈在 Windows 模擬下跑起來。
FAKE_SHERPA = textwrap.dedent("""
    class _Res:
        text = "測試"; lang = "<|zh|>"; emotion = ""; tokens = ["測", "試"]; timestamps = [0.0, 0.1]
    class _Stream:
        result = _Res()
        def accept_waveform(self, sr, a): pass
    class OfflineRecognizer:
        @classmethod
        def from_sense_voice(cls, **kw): return cls()
        def create_stream(self): return _Stream()
        def decode_stream(self, s): pass
""")


def _sv_child_importable() -> bool:
    try:
        import refine_transcript  # noqa: F401
        import summary_utils  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _sv_child_importable(), reason="sv 子行程要 import refine_transcript／summary_utils")
def test_sv_worker_child_under_windows(windows_child, windows_select, monkeypatch):
    (windows_child / "sherpa_onnx.py").write_text(FAKE_SHERPA, encoding="utf-8")
    w = svw.SvWorker()
    try:
        assert w._call("load", None, 60)["ok"] is True
        res = w.transcribe(np.zeros(1600, dtype=np.float32))
        assert res["ok"] is True and res["tokens"] == ["測", "試"]
    finally:
        w.shutdown()
    assert w._proc is None


@pytest.mark.skipif(not _sv_child_importable(), reason="sv 子行程要 import refine_transcript／summary_utils")
def test_sv_worker_child_idle_exit_under_windows(windows_child, windows_select, monkeypatch):
    """sv 子行程閒置 IDLE_EXIT_SEC 就結束；Windows 路徑也要照樣結束，下一次呼叫自動重啟。"""
    (windows_child / "sherpa_onnx.py").write_text(FAKE_SHERPA, encoding="utf-8")
    monkeypatch.setenv("PI5_LIVE_SV_IDLE_EXIT_SEC", "0.5")
    w = svw.SvWorker()
    try:
        assert w._call("load", None, 60)["ok"] is True
        w._proc.wait(timeout=15)                                      # 閒置結束
        assert w._call("load", None, 60)["ok"] is True                # 自動重啟
    finally:
        w.shutdown()


# --------------------------------------------------------------------------- N3 突變測試補的邊界


def test_select_pipes_env_on_windows(monkeypatch):
    """在 Windows (os.name == "nt") 上：預設不 select；PI5_STT_SELECT_PIPES=1 仍可強制 select。"""
    with monkeypatch.context() as m:
        m.setattr(sw.os, "name", "nt")
        m.delenv("PI5_STT_SELECT_PIPES", raising=False)
        default = sw._select_pipes_from_env()
        m.setenv("PI5_STT_SELECT_PIPES", "1")
        forced = sw._select_pipes_from_env()
    assert (default, forced) == (False, True)


def test_short_deadline_still_reads(read_mode):
    """剩不到 1 秒的 deadline 也要等資料，不能直接當逾時。"""
    r, wfd = os.pipe()
    f = os.fdopen(wfd, "wb")

    def later():
        time.sleep(0.1)
        sw._write_frame(f, {"ok": True})
    t = threading.Thread(target=later)
    t.start()
    try:
        assert sw._read_frame(r, time.monotonic() + 0.8) == {"ok": True}
    finally:
        t.join(5)
        f.close()
        os.close(r)


def test_expired_deadline_is_timeout(read_mode):
    """deadline 已經過了：TimeoutError（不能把負的逾時交給 select → ValueError）。"""
    r, wfd = os.pipe()
    try:
        with pytest.raises(TimeoutError):
            sw._read_frame(r, time.monotonic() - 0.5)
    finally:
        os.close(wfd)
        os.close(r)


def test_thread_read_propagates_os_error():
    """背景執行緒讀取時的 OSError（例如 fd 已關、或讀到只能寫的一端）要拋給呼叫端。"""
    r, wfd = os.pipe()
    os.close(r)
    try:
        with pytest.raises(OSError):
            sw._read_chunk_with_timeout(wfd, 4, 2.0)      # 寫端不能讀：EBADF
    finally:
        os.close(wfd)


def test_inbox_thread_mode_reports_read_error():
    """常駐收訊框的執行緒讀到錯誤 (不是 EOF)：get 拋出同一個錯誤，之後也一樣 (不卡住)。"""
    r, wfd = os.pipe()
    os.close(r)
    try:
        inbox = sw._FrameInbox(wfd, use_select=False)     # 寫端不能讀
        with pytest.raises(OSError):
            inbox.get(5)
        with pytest.raises(OSError):
            inbox.get(0.1)
    finally:
        os.close(wfd)
