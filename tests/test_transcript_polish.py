# -*- coding: utf-8 -*-
import asyncio

import pytest

import summary_utils
import transcript_polish as tp
from llm_backend import LLMError


class _FakeBackend:
    label = "CPU Ollama qwen2.5:3b-opt"


def _run(coro):
    return asyncio.run(coro)


def _stream(reply, seen=None):
    """aiter_chat_stream 的假版本：reply(prompt) 回傳整段文字（或 raise），一次吐出。seen 收集呼叫參數。"""
    async def fake(prompt, system=None, **kwargs):
        if seen is not None:
            seen.append({"prompt": prompt, "system": system, **kwargs})
        yield reply(prompt), True, _FakeBackend()
    return fake


def _chunk_of(prompt):
    return prompt.split("逐字稿片段：\n", 1)[1]


def test_split_chunks_respects_limit_and_keeps_all_text():
    text = "\n".join(["甲" * 250, "乙" * 250, "丙" * 250])
    chunks = tp.split_chunks(text, max_chars=600)
    assert chunks == ["甲" * 250 + "\n" + "乙" * 250, "丙" * 250]
    assert all(len(c) <= 600 for c in chunks)


def test_split_chunks_cuts_long_line_after_punctuation():
    line = "一" * 300 + "。" + "二" * 400
    chunks = tp.split_chunks(line, max_chars=600)
    assert chunks == ["一" * 300 + "。", "二" * 400]


def test_split_chunks_skips_blank_lines():
    assert tp.split_chunks("\n\n  \n", max_chars=600) == []


def test_accept_small_edits_keeps_short_fixes_and_rejects_rewrites():
    src = "請李協里確認期，然後我們今天就先討論到這裡"
    dst = "請李協理確認日期，然後今天的會議到此結束"
    out, st = tp.accept_small_edits(src, dst)
    assert out.startswith("請李協理確認日期，")          # 同音字（替換 1 字）與漏字（補 1 字）收
    assert out.endswith("我們今天就先討論到這裡")       # 整句改寫（被 difflib 拆成幾個小修改）不收，保留原文
    assert st == {"accepted": 1, "rejected": 1}


def test_accept_small_edits_limits_deletions():
    out, _ = tp.accept_small_edits("好好的，開始", "好的，開始")
    assert out == "好的，開始"                            # 刪 1 字（口吃）收
    out, _ = tp.accept_small_edits("我們我們我們來看第一項", "來看第一項")
    assert out == "我們我們我們來看第一項"                # 刪一大段不收


def test_accept_small_edits_never_touches_speaker_labels():
    src = "說話人1：大家好\n說話人2：李協里好"
    dst = "說話人3：大家好\n說話人2：李協理好"
    out, st = tp.accept_small_edits(src, dst, tp.protected_spans(src))
    assert out == "說話人1：大家好\n說話人2：李協理好"
    assert st == {"accepted": 1, "rejected": 1}


def test_polish_fix_applies_per_chunk_and_keeps_original_on_llm_error(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise LLMError("boom")
        return _chunk_of(prompt).replace("改報", "改善")

    text = "\n".join(["改報" + "甲" * 590, "改報" + "乙" * 590])
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(reply))
    res = _run(tp.polish_transcript(text, "fix"))
    assert res["chunks"] == 2 and res["failed_chunks"] == 1
    assert res["backend"] == "CPU Ollama qwen2.5:3b-opt"
    assert res["polished"] == "改善" + "甲" * 590 + "\n\n" + "改報" + "乙" * 590
    assert res["accepted_edits"] == 1
    assert "".join(t for op, t, _ in res["segments"] if op != "del") == res["polished"]
    assert ["rep", "善", "報"] in res["segments"]
    assert res["diff_counts"] == {"rep": 1, "ins": 0, "del": 0}


def test_polish_fix_uses_cpu_first_and_strips_echoed_header(monkeypatch):
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "逐字稿片段：" + _chunk_of(p).replace("期", "日期"), seen))
    res = _run(tp.polish_transcript("確認期", "fix", source="refine"))
    assert res["polished"] == "確認日期"
    assert res["source"] == "refine"
    assert seen[0]["cpu_first"] is (tp.POLISH_BACKEND == "cpu")
    assert seen[0]["system"] == tp.FIX_SYSTEM


def test_polish_reports_progress_per_chunk(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of))
    seen = []
    text = "\n".join(["甲" * 590, "乙" * 590, "丙" * 590])
    res = _run(tp.polish_transcript(text, "fix", on_progress=lambda done, total: seen.append((done, total))))
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert res["stopped"] is False


def test_polish_stops_between_chunks_and_keeps_rest_original(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return _chunk_of(prompt).replace("改報", "改善")

    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(reply))
    text = "\n".join(["改報" + "甲" * 590, "改報" + "乙" * 590, "改報" + "丙" * 590])
    # 第一段做完後「開始錄音」：第二段開始前就要停。
    done = []
    res = _run(tp.polish_transcript(text, "fix", on_progress=lambda d, t: done.append(d), should_stop=lambda: len(done) >= 1))
    assert len(calls) == 1
    assert res["stopped"] is True
    assert res["polished"] == "\n\n".join(["改善" + "甲" * 590, "改報" + "乙" * 590, "改報" + "丙" * 590])
    assert res["diff_counts"]["rep"] == 1   # 沒處理的段落不標


def test_polish_stops_mid_generation_and_closes_the_stream(monkeypatch):
    state = {"tokens": 0, "closed": False}

    async def slow_stream(prompt, system=None, **kwargs):
        try:
            for tok in ["改", "善", "甲"]:
                state["tokens"] += 1
                yield tok, False, _FakeBackend()
        finally:
            state["closed"] = True

    monkeypatch.setattr(tp, "aiter_chat_stream", slow_stream)
    res = _run(tp.polish_transcript("改報甲", "fix", should_stop=lambda: state["tokens"] >= 1))
    assert res["stopped"] is True
    assert res["polished"] == "改報甲"            # 生成中被打斷的那段保留原文
    assert state["closed"] is True and state["tokens"] == 1


def test_polish_rewrite_rejects_suspicious_length(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "短"))
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "一" * 100
    assert res["rejected_chunks"] == 1


def test_polish_rewrite_accepts_reasonable_output(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "二" * 80))
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "二" * 80
    assert res["rejected_chunks"] == 0


def test_polish_rejects_unknown_mode():
    with pytest.raises(ValueError):
        _run(tp.polish_transcript("abc", "summarize"))


class _FakeCC:
    """測試用的簡轉台灣繁體：只換本檔用到的字。"""

    def convert(self, text):
        return text.translate(str.maketrans({"没": "沒", "伤": "傷", "协": "協", "员": "員"}))


def test_polish_fix_ignores_script_only_changes(monkeypatch):
    # 模型把繁體「修」成簡體：轉回台灣繁體後與原文相同，不算修改；真正的修改仍保留且為繁體。
    monkeypatch.setattr(summary_utils, "_CC", _FakeCC())
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "没有人受伤，李协理"))
    res = _run(tp.polish_transcript("沒有人受傷，李協里", "fix"))
    assert res["polished"] == "沒有人受傷，李協理"
    assert res["diff_counts"] == {"rep": 1, "ins": 0, "del": 0}


def test_polish_rewrite_output_is_taiwan_traditional(monkeypatch):
    monkeypatch.setattr(summary_utils, "_CC", _FakeCC())
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "全员" + "二" * 80))
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "全員" + "二" * 80


def test_polish_rewrite_keeps_original_when_numbers_change(monkeypatch):
    # 日期、數量被改掉 (或中文化) 的段落保留原文。
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "修正版預計十月十二日上線，先在一百臺裝置上試跑三天" + "。" * 10))
    text = "修正版 預記 10月11日上線，先在100臺裝置上市跑三天"
    res = _run(tp.polish_transcript(text, "rewrite"))
    assert res["polished"] == text
    assert res["fact_rejected_chunks"] == 1


def test_polish_rewrite_accepts_when_numbers_are_kept(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "修正版預計10月11日上線，先在100臺裝置上試跑三天"))
    text = "修正版 預記 10月11日上線，先在100臺裝置上市跑三天"
    res = _run(tp.polish_transcript(text, "rewrite"))
    assert res["polished"] == "修正版預計10月11日上線，先在100臺裝置上試跑三天"
    assert res["fact_rejected_chunks"] == 0


def test_output_timeout_grows_with_output_budget(monkeypatch):
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "二" * 500, seen))
    _run(tp.polish_transcript("一" * 590, "rewrite"))
    assert seen[0]["num_predict"] == 1180
    assert seen[0]["timeout"] >= 1180 / 4.5


def test_diff_segments_marks_replacement_insertion_and_deletion():
    segs = tp.diff_segments("請李協里確認期", "請李協理確認日期")
    assert segs == [["eq", "請李協", ""], ["rep", "理", "里"], ["eq", "確認", ""], ["ins", "日", ""], ["eq", "期", ""]]
    assert tp.diff_segments("好的好的，開始", "好的，開始") == [["del", "好的", ""], ["eq", "好的，開始", ""]]
    # 去掉 del 後接起來就是新文字
    src, dst = "第一個議題是公安", "第一個議題是工安。"
    assert "".join(t for op, t, _ in tp.diff_segments(src, dst) if op != "del") == dst
