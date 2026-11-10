# -*- coding: utf-8 -*-
import asyncio

import pytest

import transcript_polish as tp
from llm_backend import LLMError


class _FakeBackend:
    label = "hailo"


def _run(coro):
    return asyncio.run(coro)


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


def test_parse_fix_list_extracts_array_from_noisy_output():
    raw = '好的，修改如下：\n[{"from": "外科呱瓜", "to": "外科瓜瓜"}]\n謝謝'
    assert tp.parse_fix_list(raw) == [{"from": "外科呱瓜", "to": "外科瓜瓜"}]


def test_parse_fix_list_drops_invalid_items_only():
    raw = '[{"from": "", "to": "x"}, {"from": "a", "to": "a"}, {"from": 1, "to": "b"}, {"from": "ok", "to": "好"}]'
    assert tp.parse_fix_list(raw) == [{"from": "ok", "to": "好"}]


def test_parse_fix_list_returns_none_on_unparseable_output():
    assert tp.parse_fix_list('[{"from": "a", "to": ') is None
    assert tp.parse_fix_list("沒有陣列") is None
    assert tp.parse_fix_list("") is None


def test_parse_fix_list_accepts_empty_list():
    assert tp.parse_fix_list("[]") == []


def test_apply_fixes_only_exact_matches_and_counts():
    text = "外科呱瓜很好，外科呱瓜也很好"
    new_text, applied = tp.apply_fixes(
        text, [{"from": "外科呱瓜", "to": "外科瓜瓜"}, {"from": "不存在", "to": "x"}]
    )
    assert new_text == "外科瓜瓜很好，外科瓜瓜也很好"
    assert applied == [{"from": "外科呱瓜", "to": "外科瓜瓜", "count": 2}]


def test_polish_fix_applies_per_chunk_and_keeps_original_on_llm_error(monkeypatch):
    calls = []

    async def fake_achat(prompt, system=None, **kwargs):
        calls.append(prompt)
        if len(calls) == 2:
            raise LLMError("boom")
        return '[{"from": "改報", "to": "改善"}]', _FakeBackend()

    monkeypatch.setattr(tp, "achat_complete", fake_achat)
    text = "\n".join(["改報" + "甲" * 590, "改報" + "乙" * 590])
    res = _run(tp.polish_transcript(text, "fix"))

    assert res["chunks"] == 2
    assert res["failed_chunks"] == 1
    assert res["backend"] == "hailo"
    assert res["changes"] == [{"from": "改報", "to": "改善", "count": 1}]
    assert res["polished"] == "改善" + "甲" * 590 + "\n\n" + "改報" + "乙" * 590


def test_polish_fix_counts_parse_errors_and_keeps_text(monkeypatch):
    async def fake_achat(prompt, system=None, **kwargs):
        return "亂碼 [[[", _FakeBackend()

    monkeypatch.setattr(tp, "achat_complete", fake_achat)
    text = "一二三四五"
    res = _run(tp.polish_transcript(text, "fix"))
    assert res["polished"] == text
    assert res["parse_errors"] == 1
    assert res["changes"] == []


def test_polish_rewrite_rejects_suspicious_length(monkeypatch):
    async def fake_achat(prompt, system=None, **kwargs):
        return "短", _FakeBackend()

    monkeypatch.setattr(tp, "achat_complete", fake_achat)
    text = "一" * 100
    res = _run(tp.polish_transcript(text, "rewrite"))
    assert res["polished"] == text
    assert res["rejected_chunks"] == 1


def test_polish_rewrite_accepts_reasonable_output(monkeypatch):
    async def fake_achat(prompt, system=None, **kwargs):
        return "二" * 80, _FakeBackend()

    monkeypatch.setattr(tp, "achat_complete", fake_achat)
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "二" * 80
    assert res["rejected_chunks"] == 0


def test_polish_rejects_unknown_mode():
    with pytest.raises(ValueError):
        _run(tp.polish_transcript("abc", "summarize"))


def test_parse_fix_list_drops_single_char_from():
    # 單字替換 (例如「的」→「得」) 會套用到全文每一處，風險太高，直接略過。
    raw = '[{"from": "的", "to": "得"}, {"from": "外科呱瓜", "to": "外科瓜瓜"}]'
    assert tp.parse_fix_list(raw) == [{"from": "外科呱瓜", "to": "外科瓜瓜"}]
