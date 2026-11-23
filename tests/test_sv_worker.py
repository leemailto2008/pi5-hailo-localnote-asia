"""sv_worker 主行程端：子行程協定、閒置結束後自動重啟、錯誤回報、逾時砍掉子行程。
子行程換成一支小 Python 腳本（同樣的 [長度][pickle] 訊框），不需要 sherpa-onnx 與 SenseVoice 模型；
另有一項用真的子行程（沒裝 sherpa-onnx 時會在 import 就結束），確認主行程不會卡住。"""
import importlib.util
import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest

import sv_worker as svw

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.join(os.path.dirname(HERE), "code_dispatcher")

FAKE_CHILD = textwrap.dedent("""
    import os, sys, time
    sys.path.insert(0, {code_dir!r})
    from stt_worker import _read_frame, _write_frame
    out = os.fdopen(os.dup(1), "wb")
    mode = os.environ.get("FAKE_SV_MODE", "")
    n = 0
    while True:
        try:
            cmd, payload = _read_frame(sys.stdin.fileno())
        except EOFError:
            break
        n += 1
        if cmd == "exit":
            _write_frame(out, {{"ok": True}}); break
        if mode == "die_after_one" and n > 1:
            break                                   # 模擬閒置結束：收到第二個請求就直接離開
        if mode == "hang":
            time.sleep(30)
        if cmd == "load":
            _write_frame(out, {{"ok": True, "load_ms": 12, "lang": payload}})
        elif cmd == "transcribe":
            audio, lang = payload if isinstance(payload, tuple) else (payload, "")
            _write_frame(out, {{"ok": True, "text": f"{{len(audio)}}:{{lang}}", "inference_time_ms": 1}})
        else:
            _write_frame(out, {{"ok": False, "error": "unknown command " + repr(cmd)}})
""").format(code_dir=CODE_DIR)


@pytest.fixture
def fake_child(monkeypatch, tmp_path):
    script = tmp_path / "fake_sv_child.py"
    script.write_text(FAKE_CHILD)
    spawned = []
    real_popen = subprocess.Popen

    def popen(argv, **kw):
        assert argv[-1] == "--child" and argv[1] == "-u"
        p = real_popen([sys.executable, "-u", str(script)], **kw)
        spawned.append(p)
        return p
    monkeypatch.setattr(svw.subprocess, "Popen", popen)
    w = svw.SvWorker()
    yield w, spawned
    w.shutdown()
    for p in spawned:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_transcribe_and_language_payload(fake_child):
    w, spawned = fake_child
    audio = np.zeros(16000, dtype=np.float32)
    assert w.transcribe(audio)["text"] == "16000:"
    assert w.transcribe(audio, language="en")["text"] == "16000:en"
    assert len(spawned) == 1                          # 同一個子行程常駐


def test_warm_up_and_shutdown(fake_child, capsys):
    w, spawned = fake_child
    w.warm_up("zh")
    assert "warm up done (12 ms)" in capsys.readouterr().out
    w.shutdown()                                      # 送 exit 後一律 kill 保險，所以 returncode 可能是 0 或 -9
    assert spawned[0].poll() is not None and w._proc is None
    w.shutdown()                                      # 沒有子行程時再呼叫也沒事


def test_restarts_once_when_child_exited(fake_child, monkeypatch):
    monkeypatch.setenv("FAKE_SV_MODE", "die_after_one")
    w, spawned = fake_child
    audio = np.zeros(10, dtype=np.float32)
    assert w.transcribe(audio)["text"] == "10:"
    assert w.transcribe(audio)["text"] == "10:"       # 第一個子行程不回應 → 重啟再試一次就成功
    assert len(spawned) == 2


def test_child_error_is_raised(fake_child):
    w, _ = fake_child
    with pytest.raises(RuntimeError, match="unknown command 'bogus'"):
        w._call("bogus", None, 10.0)


def test_timeout_kills_child(fake_child, monkeypatch):
    monkeypatch.setenv("FAKE_SV_MODE", "hang")
    w, spawned = fake_child
    with pytest.raises(RuntimeError, match="sv worker load failed"):
        w._call("load", "zh", 0.5)
    assert w._proc is None and spawned[0].wait(timeout=5) != 0


@pytest.mark.skipif(importlib.util.find_spec("sherpa_onnx") is not None, reason="有 sherpa-onnx 時會真的載入模型")
def test_real_child_without_sherpa_fails_fast():
    w = svw.SvWorker()
    try:
        with pytest.raises(RuntimeError, match="sv worker transcribe failed"):
            w.transcribe(np.zeros(1600, dtype=np.float32))
        w.warm_up()                                   # 只記 log，不拋例外
    finally:
        w.shutdown()
    assert w._proc is None
