"""故障注入：寫檔時磁碟滿（ENOSPC）。2026-11-23（localnote@mac，S7）。

這些設定／狀態檔都用「先寫 .tmp／.part 再 os.replace」，寫到一半磁碟滿時舊檔不會壞；
但例外往外拋（或被接住）之前沒有刪掉寫了一半的 .tmp／.part，留在 /dev/shm（RAM 磁碟）佔記憶體，
即時切片結果（*.live_asr.json.part）一場 4 小時會議可達數 MB；Issue 回報則留下沒有 feedback.json 的半成品資料夾，
之後 list_reports 一直列出一筆「讀不到」。

注入方式：只攔 tmp_path 底下的寫入檔，先寫一半內容再 raise OSError(ENOSPC)，其他檔案照常。
每項確認：錯誤照原本的方式回報（raise 或回傳 False／None）、舊檔不變、沒有殘檔。
"""
import builtins
import errno
import json
import os
import sys
import types

import pytest

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))


class _FullDisk:
    """包住真的檔案：第一次 write 只寫進一半就 ENOSPC（模擬寫到一半磁碟滿）。"""

    def __init__(self, f):
        self._f = f

    def write(self, s):
        self._f.write(s[: max(1, len(s) // 2)])
        self._f.flush()
        raise OSError(errno.ENOSPC, "No space left on device")

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._f.close()
        return False


@pytest.fixture
def disk_full(monkeypatch, tmp_path):
    real_open = builtins.open
    root = str(tmp_path)

    def fake_open(file, mode="r", *a, **k):
        f = real_open(file, mode, *a, **k)
        if isinstance(file, str) and file.startswith(root) and any(c in mode for c in "wax"):
            return _FullDisk(f)
        return f
    monkeypatch.setattr(builtins, "open", fake_open)
    return tmp_path


def _leftovers(d):
    return sorted(os.path.relpath(os.path.join(r, n), d).replace(os.sep, "/")
                  for r, _, files in os.walk(d) for n in files if n.endswith((".tmp", ".part")))


def test_asr_language(disk_full, monkeypatch):
    import asr_language
    p = disk_full / "asr_language.json"
    p.write_bytes(json.dumps({"language": "en"}).encode())
    monkeypatch.setattr(asr_language, "ASR_LANG_PATH", str(p))
    with pytest.raises(OSError):
        asr_language.save_asr_language("zh")                 # main 會轉成 HTTP 500
    assert json.loads(p.read_bytes()) == {"language": "en"} and _leftovers(disk_full) == []


def test_live_translate_pref(disk_full, monkeypatch):
    import live_translate
    p = disk_full / "live_tr.json"
    monkeypatch.setattr(live_translate, "LIVE_TR_PATH", str(p))
    with pytest.raises(OSError):
        live_translate.save_live_translate_preference("en")
    assert not p.exists() and _leftovers(disk_full) == []


def test_meeting_glossary(disk_full, monkeypatch):
    import meeting_glossary
    p = disk_full / "glossary.txt"
    p.write_bytes("舊詞彙".encode("utf-8"))
    monkeypatch.setattr(meeting_glossary, "GLOSSARY_PATH", str(p))
    with pytest.raises(OSError):
        meeting_glossary.write_text("新詞彙、很多很多字")
    assert p.read_bytes().decode("utf-8") == "舊詞彙" and _leftovers(disk_full) == []


def test_last_meeting(disk_full):
    import last_meeting
    p = str(disk_full / "state" / "last_meeting.json")
    assert last_meeting.save_last_meeting({"job": "m_1", "summary": ["x" * 100]}, {"state": "done"}, path=p) is False
    assert _leftovers(disk_full) == []


def test_single_job_persist(disk_full):
    import single_job
    job = single_job.SingleJob("refine", persist_path=str(disk_full / "refine_last.json"))
    job._save({"status": "done", "text": "y" * 200})          # 只記 log，不拋
    assert _leftovers(disk_full) == []


def test_refine_live_asr(disk_full, monkeypatch):
    import refine_transcript as rt
    target = str(disk_full / "localnote_state" / "m_1.live_asr.json")
    monkeypatch.setattr(rt, "live_asr_path", lambda audio_path, suffix=rt.LIVE_ASR_SUFFIX: target)
    slices = [{"t0": i, "t1": i + 1, "text": "測試" * 20} for i in range(50)]
    assert rt.save_live_asr("/x/m_1.ogg", slices, 16000 * 50) is None   # 存不了：高精度稿整段重新辨識
    assert _leftovers(disk_full) == []


def test_issue_feedback_leaves_no_half_report(disk_full, monkeypatch):
    import issue_feedback as fb
    fbdir = disk_full / "feedback"
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(fbdir))
    with pytest.raises(OSError):
        fb.save({"description": "翻譯停住"}, "log line " * 100, transcript="逐字稿")   # main 會轉成 HTTP 500
    assert not fbdir.exists() or os.listdir(fbdir) == []      # 不留半成品資料夾
    assert fb.list_reports() == []                            # 列表不會多一筆「讀不到」
