"""N8（2026-11-24 localnote@mac）：issue_feedback 的輸入驗證與存檔邊界。
1. valid_id 用 re.match＋「$」：「$」在結尾換行前也算結尾，「<合法 id>\\n」被當成合法。
2. 同一秒、同一個 4 碼亂數（1／65536）的兩筆回報：os.makedirs(exist_ok=True) 讓第二筆寫進第一筆的資料夾，蓋掉第一筆的
   feedback.json 與 service.log（資料遺失，而且兩次 API 回傳同一個 id）。"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))
import issue_feedback as fb  # noqa: E402

GOOD = "20261124_101010_raspi543_abcd"


def test_valid_id_rejects_trailing_newline_and_spaces():
    assert fb.valid_id(GOOD)
    for bad in (GOOD + "\n", GOOD + " ", "\n" + GOOD, GOOD + "\r\n", GOOD + "/..", "../" + GOOD, GOOD.upper()):
        assert not fb.valid_id(bad), repr(bad)


def test_same_id_twice_does_not_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    ids = iter([GOOD, GOOD, "20261124_101010_raspi543_beef"])
    monkeypatch.setattr(fb, "new_id", lambda now=None: next(ids))
    a = fb.save({"description": "第一筆"}, "log1")
    b = fb.save({"description": "第二筆"}, "log2")
    assert a != b
    assert fb.load(a)["description"] == "第一筆" and fb.load(b)["description"] == "第二筆"
    assert open(os.path.join(tmp_path, a, "service.log"), encoding="utf-8").read() == "log1"


def test_save_gives_up_after_many_collisions(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    monkeypatch.setattr(fb, "new_id", lambda now=None: GOOD)
    fb.save({"description": "x"}, "")
    try:
        fb.save({"description": "y"}, "")
    except FileExistsError:
        pass
    else:
        raise AssertionError("一直撞同一個 id 時要失敗，不能蓋掉")
    assert json.load(open(os.path.join(tmp_path, GOOD, "feedback.json"), encoding="utf-8"))["description"] == "x"


def test_valid_id_one_char_host():
    assert fb.valid_id("20261124_101010_a_abcd")                  # 主機名稱 1 字也合法 (new_id 會產生)


def test_collision_retries_exactly_five_times(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(fb, "new_id", lambda now=None: calls.append(1) or GOOD)
    os.makedirs(os.path.join(tmp_path, GOOD))
    try:
        fb.save({"description": "x"}, "")
    except FileExistsError:
        pass
    assert len(calls) == 5


def test_audio_attachment_text_and_clamp(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    made = []

    def fake_cut(src, dst, minutes):
        made.append(os.path.basename(dst))
        open(dst, "wb").close()
        return None
    monkeypatch.setattr(fb, "cut_audio", fake_cut)
    src = str(tmp_path / "m_1.ogg")
    r1 = fb.load(fb.save({"description": "a"}, "", audio_src=src))                  # 預設 5 分鐘
    r2 = fb.load(fb.save({"description": "b"}, "", audio_src=src, audio_minutes=0))  # 下限 1
    r3 = fb.load(fb.save({"description": "c"}, "", audio_src=src, audio_minutes=99)) # 上限 AUDIO_MAX_MIN
    assert made == ["audio.ogg"] * 3
    assert r1["attachments"]["audio"] == "audio.ogg（m_1 最後 5 分鐘）"
    assert r2["attachments"]["audio"] == "audio.ogg（m_1 最後 1 分鐘）"
    assert r3["attachments"]["audio"] == f"audio.ogg（m_1 最後 {fb.AUDIO_MAX_MIN} 分鐘）"
