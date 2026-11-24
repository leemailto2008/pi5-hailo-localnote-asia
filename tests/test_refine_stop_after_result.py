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
    flag = tmp_path / "printed.flag"
    body = "".join(f"print({json.dumps(json.dumps(obj, ensure_ascii=False))}, flush=True)\n" for obj in lines)
    # 子行程一律用 UTF-8 輸出（Pi 預設就是；Windows 預設 cp950，主行程用 UTF-8 讀會讀不到中文）。
    # 印完才建 flag：停止時機看 flag，不看牆鐘（11-24 Windows 記憶體吃緊時子行程啟動 > 0.8 s，偶發「還沒印就停」）
    script.write_text("import sys, time\nsys.stdout.reconfigure(encoding='utf-8')\n" + body
                      + f"open({str(flag)!r}, 'w').close()\ntime.sleep({linger_s})\n", encoding="utf-8")
    return [sys.executable, str(script)], flag


def _run(child, stop: bool):
    """stop=True：子行程印完（flag 出現）0.3 s 後才回 should_stop=True，模擬「已交出內容、還在結束時開始錄音」。"""
    cmd, flag = child
    seen = {}

    def should_stop():
        if not stop or not flag.exists():
            return False
        seen.setdefault("t", time.monotonic())
        return time.monotonic() - seen["t"] >= 0.3
    return asyncio.run(rt.run_in_subprocess("x.ogg", should_stop=should_stop, cmd=cmd))


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    monkeypatch.setattr(rt, "STOP_POLL_S", 0.2)
    monkeypatch.setattr(rt, "STOP_GRACE_S", 2.0)


def test_result_already_received_is_kept(tmp_path):
    out = _run(_child(tmp_path, [{"partial": PARTIAL}, {"result": RESULT}], linger_s=5), stop=True)
    assert out == RESULT


def test_stop_before_result_still_returns_partial(tmp_path):
    out = _run(_child(tmp_path, [{"partial": PARTIAL}], linger_s=5), stop=True)
    assert out["stopped"] is True and out["transcript"] == "好"


def test_no_stop_returns_result(tmp_path):
    out = _run(_child(tmp_path, [{"result": RESULT}], linger_s=0), stop=False)
    assert out == RESULT
