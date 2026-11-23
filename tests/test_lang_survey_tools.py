"""tools/whisper_lang_survey.py、tools/sv_lang_survey.py 的離線部分（文字判斷、切片、結果彙總、sv_lang_guard 模擬）。
量測本體（run）要 Pi 上的 Hailo／sherpa-onnx，不在這裡測。"""
import importlib.util
import json
import os
import wave

import numpy as np
import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wls = _load("whisper_lang_survey")
sls = _load("sv_lang_survey")


@pytest.mark.parametrize("text,expect", [
    ("We need two more engineers for the project.", True),
    ("okay", True),
    ("Hola, ¿cómo estás? Necesitamos dos ingenieros.", False),     # 西班牙文：拉丁字母但不是英文功能詞
    ("Chúng ta cần thêm hai kỹ sư.", False),                       # 越南文
    ("我們需要 two engineers", False),                              # 中英夾雜：拉丁字母不到八成
    ("", False), ("1234 5678", False), ("Jakarta", False),
])
def test_is_english(text, expect):
    assert wls.is_english(text) is expect


@pytest.mark.parametrize("text,expect", [
    ("これはテストです", "kana"), ("테스트입니다", "hangul"), ("ทดสอบ", "thai"), ("這是測試", "cjk"),
    ("This is the test", "en"), ("Esto es una prueba", "latin"), ("   ", "none"), ("123 !!", "other"),
])
def test_script_of(text, expect):
    assert wls.script_of(text) == expect


def test_lang_tag_and_native_map():
    assert wls.lang_tag("/x/ja__podcast_01.wav") == "ja"
    assert wls.lang_tag("zh_en__m.wav") == "zh_en"
    assert wls.NATIVE["yue"] == "zh" and wls.NATIVE["nan"] == "zh"


def test_slices_cut_at_pauses_and_drop_short_tail():
    sr = wls.SR
    x = np.zeros(int(25.3 * sr), np.float32)
    cuts = []

    def pause_cut_index(seg, rate, lo, hi):
        cuts.append((len(seg), rate, lo, hi))
        return int(8 * rate)
    spans = list(wls.slices(x, pause_cut_index))
    assert spans == [(0, 8 * sr), (8 * sr, 16 * sr), (16 * sr, len(x))]   # 最後 9.3 s ≤ 9.5 s 整段
    assert cuts[0] == (int(9.5 * sr), sr, 4.0, 9.5)
    assert list(wls.slices(np.zeros(sr // 4, np.float32), pause_cut_index)) == []   # ≤ 0.5 s 不送


def test_load_wav(tmp_path):
    p = tmp_path / "a.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.array([16384, -16384], np.int16).tobytes())
    assert wls.load_wav(str(p)).tolist() == [0.5, -0.5]
    with wave.open(str(tmp_path / "b.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0")
    with pytest.raises(AssertionError):
        wls.load_wav(str(tmp_path / "b.wav"))


def test_recorder_records_language_and_output():
    class S2T:
        model = "small"

        def generate_all_text(self, **kw):
            return "out-" + str(kw.get("language"))
    r = wls._Recorder(S2T())
    assert r.generate_all_text(language=None) == "out-None"
    r.generate_all_text(language="zh")
    assert r.calls == [[None, "out-None"], ["zh", "out-zh"]] and r.model == "small"


def _jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return str(path)


def test_summary_counts_english_output_and_retries(tmp_path, capsys):
    rows = [
        {"file": "ja__a.wav", "i": 0, "tag": "ja", "t0": 0, "t1": 5, "text": "We need two more engineers.", "calls": [[None, "x"], ["zh", "y"]]},
        {"file": "ja__a.wav", "i": 1, "tag": "ja", "t0": 5, "t1": 10, "text": "これはテスト"},
        {"file": "ja__a.wav", "i": 1, "tag": "ja", "t0": 5, "t1": 10, "text": "これはテスト"},   # 重複的列只算一次
        {"file": "en__b.wav", "i": 0, "tag": "en", "t0": 0, "t1": 4, "text": "This is the plan."},   # 英文會議的英文不算
        {"file": "en__b.wav", "i": 1, "tag": "en", "t0": 4, "t1": 6, "text": "  "},
    ]
    wls.summary([_jsonl(tmp_path / "r.jsonl", rows)])
    out = capsys.readouterr().out.splitlines()
    ja = next(l for l in out if l.startswith("ja")).split()
    en = next(l for l in out if l.startswith("en")).split()
    al = next(l for l in out if l.startswith("ALL")).split()
    assert ja[1:5] == ["2", "2", "1", "50.0%"] and ja[-1] == "1"
    assert en[1:4] == ["2", "1", "0"]
    assert al[1:4] == ["4", "3", "1"]


def test_sv_sim_counts_probes_and_switches(tmp_path, capsys, monkeypatch):
    import sv_lang_guard as g

    class Guard:
        def __init__(self, clock):
            pass

        def should_probe(self, lang):
            return lang not in ("zh", "en")

        def decide(self, lang, sv_text, w_text):
            return "whisper" if lang == "ja" else "sv"
    monkeypatch.setattr(g, "ForeignLangGuard", Guard)
    monkeypatch.setattr(g, "refine_whisper_choices", lambda recs: [i for i, r in enumerate(recs) if r.get("wtext")])
    sv = [{"file": "ja__x.wav", "i": i, "sv_lang": lang, "sv_raw": f"s{i}"} for i, lang in enumerate(["ja", "zh", "ko"])]
    sv.append({"file": "only_sv.wav", "i": 0, "sv_lang": "ja", "sv_raw": "s"})          # Whisper 沒有對應：略過
    wh = [{"file": "ja__x.wav", "i": i, "text": f"w{i}"} for i in range(3)]
    sls.sim(type("A", (), {"sv": _jsonl(tmp_path / "sv.jsonl", sv), "res": [_jsonl(tmp_path / "w.jsonl", wh)]})())
    out = capsys.readouterr().out.splitlines()
    row = next(l for l in out if l.startswith("ja")).split()
    assert row[1:] == ["3", "2", "1", "2"]          # slices、probed（ja、ko）、live_whisper（ja）、refine_whisper
    assert not any(l.startswith("only_sv") for l in out)


def test_sv_rows_last_duplicate_wins(tmp_path):
    p = _jsonl(tmp_path / "r.jsonl", [{"file": "a", "i": 0, "v": 1}, {"file": "a", "i": 0, "v": 2}])
    assert sls._rows([p]) == {("a", 0): {"file": "a", "i": 0, "v": 2}}
