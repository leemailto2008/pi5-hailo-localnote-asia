"""issue_feedback 補測：服務 log 截斷與錯誤、錄音擷取（ffmpeg 換成假的）、壞掉的回報、依總量清除。"""
import json
import os
import subprocess
import sys
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import issue_feedback as fb  # noqa: E402


class _R:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_service_log_truncates_to_last_lines(monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return _R("\n".join(f"line{i}" for i in range(10)))
    monkeypatch.setattr(fb.subprocess, "run", run)
    out = fb.service_log(minutes=7, max_lines=3)
    assert out.splitlines() == ["(前面省略 7 行)", "line7", "line8", "line9"]
    assert seen["cmd"][:3] == ["journalctl", "-u", fb.SERVICE] and "-7min" in seen["cmd"]


def test_service_log_uses_stderr_and_reports_errors(monkeypatch):
    monkeypatch.setattr(fb.subprocess, "run", lambda cmd, **kw: _R("", "No journal files were found."))
    assert fb.service_log() == "No journal files were found."

    def missing(cmd, **kw):
        raise FileNotFoundError("journalctl")
    monkeypatch.setattr(fb.subprocess, "run", missing)
    assert fb.service_log().startswith("(讀不到服務 log：")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 15)
    monkeypatch.setattr(fb.subprocess, "run", slow)
    assert "讀不到服務 log" in fb.service_log()


def test_cut_audio_clamps_minutes_and_builds_command(monkeypatch, tmp_path):
    src = tmp_path / "m_1.ogg"
    src.write_bytes(b"x")
    dst = tmp_path / "audio.ogg"
    cmds = []

    def run(cmd, **kw):
        cmds.append(cmd)
        dst.write_bytes(b"cut")
        return _R()
    monkeypatch.setattr(fb.subprocess, "run", run)
    assert fb.cut_audio(str(src), str(dst), 99) is None
    assert cmds[-1][cmds[-1].index("-sseof") + 1] == f"-{fb.AUDIO_MAX_MIN * 60}"
    assert fb.cut_audio(str(src), str(dst), 0) is None
    assert cmds[-1][cmds[-1].index("-sseof") + 1] == "-60"
    assert "-c" in cmds[-1] and cmds[-1][cmds[-1].index("-c") + 1] == "copy"


def test_cut_audio_failures(monkeypatch, tmp_path):
    src = tmp_path / "m.ogg"
    src.write_bytes(b"x")
    monkeypatch.setattr(fb.subprocess, "run", lambda cmd, **kw: _R(stderr="Invalid data found", returncode=1))
    assert fb.cut_audio(str(src), str(tmp_path / "o.ogg"), 5) == "擷取錄音失敗：Invalid data found"
    monkeypatch.setattr(fb.subprocess, "run", lambda cmd, **kw: _R())        # rc 0 但沒產生檔案
    assert fb.cut_audio(str(src), str(tmp_path / "o.ogg"), 5).startswith("擷取錄音失敗")

    def missing(cmd, **kw):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(fb.subprocess, "run", missing)
    assert fb.cut_audio(str(src), str(tmp_path / "o.ogg"), 5).startswith("擷取錄音失敗：")


def test_list_reports_survives_broken_json(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    good, bad = "20261120_100000_pi_aaaa", "20261120_110000_pi_bbbb"
    for n in (good, bad, "not-a-report"):
        os.makedirs(tmp_path / n)
    (tmp_path / good / "feedback.json").write_text(json.dumps({"description": "d" * 300, "status": {"job": "m_9"}}), encoding="utf-8")
    (tmp_path / bad / "feedback.json").write_text("{broken", encoding="utf-8")
    lst = fb.list_reports()
    assert [r["id"] for r in lst] == [bad, good]                    # 新的在前、不合格式的資料夾不列
    assert "讀不到" in lst[0]["error"]
    assert len(lst[1]["description"]) == 120 and lst[1]["job"] == "m_9" and lst[1]["size"] > 0


def test_prune_by_total_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    monkeypatch.setattr(fb, "KEEP_BYTES", 250)
    now = time.mktime(time.strptime("2026-11-20 12:00:00", "%Y-%m-%d %H:%M:%S"))
    names = ["20261120_000001_pi_aaaa", "20261120_000002_pi_bbbb", "20261120_000003_pi_cccc"]
    for n in names:
        os.makedirs(tmp_path / n)
        (tmp_path / n / "audio.ogg").write_bytes(b"\0" * 100)
    assert fb.prune(now) == names[:1]
    assert sorted(os.listdir(tmp_path)) == names[1:]


def test_save_survives_prune_error(monkeypatch, tmp_path):
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path / "fb"))

    def bad_prune(now=None):
        raise OSError("disk")
    monkeypatch.setattr(fb, "prune", bad_prune)
    rid = fb.save({"description": "x"}, "log")
    assert fb.load(rid)["id"] == rid
    assert not (tmp_path / "fb" / rid / "feedback.json.part").exists()


def test_new_id_format_and_zip_skips_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(fb.socket, "gethostname", lambda: "box_01.local")
    rid = fb.new_id(now=time.mktime(time.strptime("2026-11-23 18:00:00", "%Y-%m-%d %H:%M:%S")))
    assert rid.startswith("20261123_180000_box-01-local_") and fb.valid_id(rid)
    monkeypatch.setattr(fb, "FEEDBACK_DIR", str(tmp_path))
    z = fb.make_zip(["20261120_000001_pi_aaaa", "../evil"])
    try:
        import zipfile
        with zipfile.ZipFile(z) as zf:
            assert zf.namelist() == []
    finally:
        os.remove(z)
