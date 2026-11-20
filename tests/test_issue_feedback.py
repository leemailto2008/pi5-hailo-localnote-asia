import json
import os
import sys
import time
import types
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import issue_feedback as fb  # noqa: E402


def test_save_list_load_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path / "feedback"))
    rid = fb.save({"description": "翻譯停住", "time": "2026-11-20 16:30:00", "status": {"job": "m_1"}}, "log line",
                  transcript="## 即時稿\n好")
    assert fb.valid_id(rid)
    folder = tmp_path / "feedback" / rid
    assert sorted(os.listdir(folder)) == ["feedback.json", "service.log", "transcript.txt"]
    r = fb.load(rid)
    assert r["description"] == "翻譯停住" and r["attachments"] == {"transcript": "transcript.txt"}
    lst = fb.list_reports()
    assert lst[0]["id"] == rid and lst[0]["job"] == "m_1"
    z = fb.make_zip([rid])
    with zipfile.ZipFile(z) as zf:
        assert sorted(zf.namelist()) == sorted(f"{rid}/{n}" for n in ("feedback.json", "service.log", "transcript.txt"))
    os.remove(z)


def test_audio_missing_is_recorded_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path / "feedback"))
    rid = fb.save({"description": "x"}, "", audio_src=str(tmp_path / "nope.ogg"), audio_minutes=5)
    assert "沒有這場的錄音檔" in fb.load(rid)["attachments"]["audio"]


def test_invalid_ids_rejected():
    assert not fb.valid_id("../etc") and not fb.valid_id("20261120_163000_pi_zzzz")
    try:
        fb.load("../../x")
        raise AssertionError("should reject")
    except ValueError:
        pass


def test_prune_by_count_and_age(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    monkeypatch.setattr(fb, "KEEP_MAX", 3)
    now = time.mktime(time.strptime("2026-11-20 12:00:00", "%Y-%m-%d %H:%M:%S"))
    names = ["20260101_000000_pi_aaaa", "20261118_000000_pi_bbbb", "20261119_000000_pi_cccc",
             "20261119_100000_pi_dddd", "20261120_000000_pi_eeee"]
    for n in names:
        os.makedirs(tmp_path / n)
        (tmp_path / n / "feedback.json").write_text(json.dumps({"description": n}), encoding="utf-8")
    removed = fb.prune(now)
    assert removed == names[:2]                    # 太舊的 1 筆＋超過 3 筆的 1 筆
    assert sorted(os.listdir(tmp_path)) == names[2:]


def test_audio_attachment_names_its_job(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path / "feedback"))
    monkeypatch.setattr(fb, "cut_audio", lambda src, dst, minutes: None)
    rid = fb.save({"description": "x"}, "", audio_src=str(tmp_path / "m_123.ogg"), audio_minutes=3)
    assert fb.load(rid)["attachments"]["audio"] == "audio.ogg（m_123 最後 3 分鐘）"
