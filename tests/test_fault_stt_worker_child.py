"""故障注入：STT 子行程卡住、回應到一半當掉、回報錯誤（2026-11-23 localnote@mac，S7）。
子行程換成同樣訊框協定的小腳本，不需要 Hailo。確認主行程不卡死、錯誤往外報（RuntimeError），
而且下一次呼叫自動重開子行程。Windows 的 select 不能用在 pipe（stt_worker 兩端都用 select），在 Windows 跳過。
"""
import os
import subprocess
import sys
import textwrap
import time

import numpy as np
import pytest

import stt_worker as sw

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="stt_worker 用 select 等子行程 pipe，Windows 不支援")

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "code_dispatcher")

CHILD = textwrap.dedent("""
    import os, pickle, struct, sys, time
    sys.path.insert(0, {code_dir!r})
    from stt_worker import _read_frame, _write_frame
    out = os.fdopen(os.dup(1), "wb")
    while True:
        try:
            cmd, payload = _read_frame(sys.stdin.fileno())
        except EOFError:
            break
        mode = open({mode_file!r}, encoding="utf-8").read().strip()   # 每個請求重讀：測試中途可以換故障模式
        if cmd == "ping":
            _write_frame(out, {{"ok": True, "engine_open": False}}); continue
        if mode == "hang":
            time.sleep(60)
        elif mode == "crash_mid_reply":
            data = pickle.dumps({{"ok": True, "text": "x" * 1000}})
            out.write(struct.pack(">I", len(data)) + data[:10]); out.flush()
            os._exit(3)                                   # 回應寫一半就當掉
        elif mode == "error":
            _write_frame(out, {{"ok": False, "error": "hailo_unavailable: HAILO_OUT_OF_PHYSICAL_DEVICES"}})
        else:
            _write_frame(out, {{"ok": True, "result": {{"text": "好"}}, "shared_group": "G"}})   # 同 stt_worker 子行程的回應格式
""")


@pytest.fixture
def worker(monkeypatch, tmp_path):
    mode_file = tmp_path / "mode.txt"
    mode_file.write_text("ok", encoding="utf-8")
    script = tmp_path / "fake_stt_child.py"
    script.write_text(CHILD.format(code_dir=CODE_DIR, mode_file=str(mode_file)), encoding="utf-8")
    real_popen = subprocess.Popen
    spawned = []

    def popen(argv, **kw):
        p = real_popen([sys.executable, "-u", str(script)], **kw)
        spawned.append(p)
        return p
    monkeypatch.setattr(sw.subprocess, "Popen", popen)
    w = sw.SttWorker()
    yield w, spawned, (lambda m: mode_file.write_text(m, encoding="utf-8"))
    w._kill()
    for p in spawned:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_hung_child_times_out_and_restarts(worker):
    w, spawned, set_mode = worker
    set_mode("hang")
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="stt worker transcribe failed"):
        w._call("transcribe", (np.zeros(10, np.float32), None), 0.5)
    assert time.monotonic() - t0 < 5                          # 不會卡到子行程睡完
    assert w._proc is None and spawned[0].wait(timeout=5) != 0
    set_mode("ok")
    assert w.transcribe(np.zeros(1600, np.float32))["text"] == "好"
    assert len(spawned) == 2 and w.shared_group() == "G" and w.is_busy() is False


def test_child_crash_mid_reply(worker):
    w, spawned, set_mode = worker
    set_mode("crash_mid_reply")
    with pytest.raises(RuntimeError, match="stt worker transcribe failed"):
        w.transcribe(np.zeros(1600, np.float32))
    assert w._proc is None and w.is_busy() is False
    set_mode("ok")
    assert w.transcribe(np.zeros(1600, np.float32))["text"] == "好"


def test_child_reports_error(worker):
    w, spawned, set_mode = worker
    set_mode("ok")
    w.transcribe(np.zeros(1600, np.float32))
    assert w.shared_group() == "G"
    set_mode("error")
    with pytest.raises(RuntimeError, match="HAILO_OUT_OF_PHYSICAL_DEVICES"):
        w.transcribe(np.zeros(1600, np.float32))
    assert w.shared_group() is None                           # 出錯時子行程已釋放 NPU，不再當成共用中
    assert w._proc is not None and w._proc.poll() is None     # 回報錯誤（非當掉）：子行程留著待命


def test_child_killed_between_calls(worker):
    w, spawned, set_mode = worker
    assert w._call("ping", None, 10)["ok"] is True
    spawned[0].kill()
    spawned[0].wait()
    assert w._call("ping", None, 10)["ok"] is True            # _ensure 發現已結束就重開
    assert len(spawned) == 2
