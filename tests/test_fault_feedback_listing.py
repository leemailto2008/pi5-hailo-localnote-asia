"""故障注入：其中一筆 Issue 回報的 feedback.json 格式不對（2026-11-23 localnote@mac，S7）。

list_reports 原本只接 JSON 解不開：合法 JSON 但不是物件（陣列、字串）、或 status 不是物件時拋 AttributeError，
整個 /api/feedback 列表都出不來（一筆壞檔拖垮全部）。應該只把那一筆標成「讀不到」，其他照常列出。
"""
import json
import os
import sys
import types

import pytest

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import issue_feedback as fb  # noqa: E402

GOOD = "20261120_100000_pi_aaaa"
BAD = "20261120_110000_pi_bbbb"


@pytest.mark.parametrize("bad", [["a", "list"], "string", 42, {"description": "x", "status": "not-a-dict"}])
def test_one_malformed_report_does_not_break_listing(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    for rid, body in ((GOOD, {"description": "好的", "status": {"job": "m_1"}}), (BAD, bad)):
        os.makedirs(tmp_path / rid)
        (tmp_path / rid / "feedback.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    lst = fb.list_reports()
    assert [r["id"] for r in lst] == [BAD, GOOD]
    assert "讀不到" in lst[0].get("error", "") or lst[0].get("job") is None
    assert lst[1]["job"] == "m_1" and lst[1]["description"] == "好的"
