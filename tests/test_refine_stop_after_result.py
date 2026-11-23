"""refine_transcript.run_in_subprocess：子行程已經交出 result、還在結束（釋放模型）時開始錄音，不能把完整結果丟掉。
2026-11-23 localnote@mac（S16 深度審查）：原本只要 watch_stop 看到 should_stop 就設 stopped，最後一律回傳 partial
（沒分人的稿，或空稿），已經收到的 result 被丟掉，4 小時會議要重跑約 20 分鐘。
子行程在 should_stop 之後才被 terminate，所以 CPU 推論本來就已經做完；交出 result 不違反錄音中不跑推論。
"""
import asyncio
import json
import sys
import time

import pytest

import refine_transcript as rt

RESULT = {"engine": "x", "transcript": "說話人1：好", "speakers": 1, "sentences": [], "stopped": False}
PARTIAL = {"engine": "x", "phase": "diarize", "transcript": "好", "speakers": 0, "sentences": []}


def _child(tmp_path, lines, linger_s):
    script = tmp_path / "fake_child.py"
    body = "".join(f"print({json.dumps(json.dumps(obj, ensure_ascii=False))}, flush=True)\n" for obj in lines)
    script.write_text("import time\n" + body + f"time.sleep({linger_s})\n", encoding="utf-8")
    return [sys.executable, str(script)]


def _run(cmd, stop_after_s):
    t0 = time.monotonic()
    return asyncio.run(rt.run_in_subprocess("x.ogg", should_stop=lambda: time.monotonic() - t0 >= stop_after_s, cmd=cmd))


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    monkeypatch.setattr(rt, "STOP_POLL_S", 0.2)
    monkeypatch.setattr(rt, "STOP_GRACE_S", 2.0)


def test_result_already_received_is_kept(tmp_path):
    out = _run(_child(tmp_path, [{"partial": PARTIAL}, {"result": RESULT}], linger_s=5), stop_after_s=0.8)
    assert out == RESULT


def test_stop_before_result_still_returns_partial(tmp_path):
    out = _run(_child(tmp_path, [{"partial": PARTIAL}], linger_s=5), stop_after_s=0.8)
    assert out["stopped"] is True and out["transcript"] == "好"


def test_no_stop_returns_result(tmp_path):
    out = _run(_child(tmp_path, [{"result": RESULT}], linger_s=0), stop_after_s=999)
    assert out == RESULT
