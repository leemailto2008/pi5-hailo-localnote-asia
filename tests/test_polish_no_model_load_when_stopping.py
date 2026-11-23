"""transcript_polish：一開始就該停（已經在錄音）時，不載入 MacBERT（CPU 約 4 s、RSS 約 814 MB）。
2026-11-23 localnote@mac（S16）：_polish_transcript 原本先載入 CscCorrector，到第一段才看 should_stop。
refine_transcript.run_in_subprocess 改成「子行程已交出結果才開始錄音也交出結果」之後，main 的 runner 會接著呼叫 quick_fix，
錄音中就會多一次 MacBERT 載入（違反 CLAUDE.md 重點一）。手動潤稿在載入前剛好開始錄音也是同一種情況。
"""
import asyncio
import sys
import types

import transcript_polish as tp


def _fake_csc(monkeypatch):
    made = []

    class FakeCorrector:
        label = "fake"

        def __init__(self, **kw):
            made.append(kw)

        def correct(self, text, should_stop=None):
            return text

    mod = types.SimpleNamespace(CscCorrector=FakeCorrector, LABEL="fake", unavailable_reason=lambda *a: None)
    monkeypatch.setitem(sys.modules, "csc_corrector", mod)
    monkeypatch.setattr(tp, "PRE_CSC", True)
    return made


def test_quick_fix_does_not_load_model_when_recording(monkeypatch):
    made = _fake_csc(monkeypatch)
    res = asyncio.run(tp.quick_fix("說話人1：好的我們開始", should_stop=lambda: True))
    assert res["status"] == "stopped"
    assert made == []


def test_polish_does_not_load_pre_csc_when_stopping(monkeypatch):
    made = _fake_csc(monkeypatch)
    res = asyncio.run(tp.polish_transcript("好的我們開始", "rewrite", should_stop=lambda: True))
    assert res["stopped"] is True and res["polished"] == "好的我們開始"
    assert made == []


def test_quick_fix_runs_normally(monkeypatch):
    made = _fake_csc(monkeypatch)
    res = asyncio.run(tp.quick_fix("說話人1：好的我們開始", should_stop=lambda: False))
    assert res["status"] == "done" and res["text"] == "說話人1：好的我們開始"
    assert len(made) == 1
