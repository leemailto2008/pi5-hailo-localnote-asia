# -*- coding: utf-8 -*-
import refine_transcript as rt
from refine_transcript import Sentence


def test_assign_speakers_uses_longest_overlap_and_nearest_gap():
    sentences = [Sentence(0.0, 4.0, "甲"), Sentence(4.0, 6.0, "乙"), Sentence(10.2, 11.0, "丙"), Sentence(30.0, 31.0, "丁")]
    turns = [(0.0, 1.0, 5), (1.0, 4.5, 7), (4.5, 10.0, 5)]
    rt.assign_speakers(sentences, turns)
    # 甲：7 重疊 3 s > 5 重疊 1 s；乙：5 重疊 1.5 s > 7 重疊 0.5 s；丙：在空隙，0.2 s 內最近的是 5；丁：太遠 → None
    assert [s.speaker for s in sentences] == [7, 5, 5, None]


def test_format_transcript_numbers_speakers_by_first_appearance_and_merges_runs():
    sentences = [Sentence(0, 1, "好，我們開始。", 7), Sentence(1, 2, "第一個議題是公安", 7),
                 Sentence(2, 3, "收到。", 3), Sentence(3, 4, "繼續", 7)]
    text, speakers = rt.format_transcript(sentences)
    assert speakers == 2
    assert text == "說話人1：好，我們開始。第一個議題是公安\n說話人2：收到。\n說話人1：繼續"


def test_format_transcript_without_speakers_is_plain_text():
    text, speakers = rt.format_transcript([Sentence(0, 1, "第一句"), Sentence(1, 2, "第二句。"), Sentence(2, 3, "第三句")])
    assert speakers == 0
    assert text == "第一句，第二句。第三句"


def test_check_available_reports_missing_models(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "MODEL_DIR", str(tmp_path))
    reason = rt.check_available()
    assert reason is not None
    assert ("sherpa-onnx" in reason) or ("sensevoice_small_int8.onnx" in reason)


def test_refine_raises_clear_error_when_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "MODEL_DIR", str(tmp_path))
    try:
        rt.refine(str(tmp_path / "x.ogg"))
    except rt.RefineError as e:
        assert str(e)
    else:
        raise AssertionError("expected RefineError")
