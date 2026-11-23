"""幾個小模組的錯誤分支：設定檔壞掉、存檔失敗、功能關閉時。都只動暫存檔，不碰硬體。"""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import asr_language  # noqa: E402
import meeting_glossary as mg  # noqa: E402
import single_job  # noqa: E402
import sv_lang_guard as g  # noqa: E402


def test_asr_language_unreadable_or_unknown(monkeypatch, tmp_path):
    p = tmp_path / "asr_language.json"
    monkeypatch.setattr(asr_language, "ASR_LANG_PATH", str(p))
    p.write_text("{broken", encoding="utf-8")
    assert asr_language.load_asr_language() == asr_language.ASR_LANG_DEFAULT
    p.write_text(json.dumps(["zh"]), encoding="utf-8")                  # 不是 dict → AttributeError
    assert asr_language.load_asr_language() == asr_language.ASR_LANG_DEFAULT
    p.write_text(json.dumps({"language": "klingon"}), encoding="utf-8")
    assert asr_language.load_asr_language() == asr_language.ASR_LANG_DEFAULT


def test_glossary_read_errors_and_missing_pypinyin(monkeypatch, tmp_path):
    p = tmp_path / "glossary.txt"
    monkeypatch.setattr(mg, "GLOSSARY_PATH", str(p))
    p.write_bytes(b"\xff\xfe\x00bad")                                    # 不是 UTF-8
    assert mg.read_text() == ""
    mg.write_text("宏遠科技、韌體")
    assert mg.read_text() == "宏遠科技、韌體" and not os.path.exists(str(p) + ".tmp")
    import transcript_polish as tp

    def no_pinyin(*a, **k):
        raise ImportError("缺少 pypinyin")
    monkeypatch.setattr(tp, "apply_glossary", no_pinyin)
    assert mg.apply_to_text("宏源科技") == ("宏源科技", 0)              # 沒裝 pypinyin：原樣回傳
    assert mg.apply_to_text("") == ("", 0)


def test_single_job_save_failure_is_not_fatal(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    job = single_job.SingleJob("t", persist_path=str(blocker / "sub" / "state.json"))   # 上層是檔案：建不了資料夾
    job._save({"status": "done"})                                        # 只記 log，不拋例外
    assert not os.path.exists(str(blocker / "sub"))


def test_sv_guard_disabled(monkeypatch):
    monkeypatch.setattr(g, "ENABLED", False)
    guard = g.ForeignLangGuard(clock=lambda: 0.0)
    assert guard.should_probe("<|ja|>") is False
    assert g.refine_whisper_choices([{"sv_lang": "<|ja|>", "sv_text": "x", "wtext": "Hola amigos que tal"}] * 5) == []


def test_whisper_verdict_edge_cases():
    assert g.whisper_verdict("<|en|>", "hello there my friend", "Xin chào các bạn") == "foreign"   # 與 SenseVoice 的英文字沒有重疊
    # 越南文會被 [a-z']+ 切成 y／l／ph 等碎片（不是空集合），同樣靠重疊率判外語
    assert g.whisper_verdict("<|en|>", "x", "Đây là bộ phận kỹ thuật") == "foreign"
    assert g.whisper_verdict("<|zh|>", "大家好", "hi") is None                                       # 拉丁字太少：不判
