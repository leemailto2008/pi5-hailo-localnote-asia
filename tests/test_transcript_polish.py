# -*- coding: utf-8 -*-
import asyncio

import pytest

import summary_utils
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
    raw = '[{"from": "", "to": "x"}, {"from": "a", "to": "a"}, {"from": 1, "to": "b"}, {"from": "李協里", "to": "李協理"}]'
    assert tp.parse_fix_list(raw) == [{"from": "李協里", "to": "李協理"}]


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


def test_parse_fix_list_rejects_deletion_and_semantic_rewrite():
    raw = ('[{"from": "週五回報", "to": ""}, {"from": "涼率", "to": "合格率"}, '
           '{"from": "使用者", "to": "用戶"}, {"from": "李協里", "to": "李協理"}]')
    assert tp.parse_fix_list(raw) == [{"from": "李協里", "to": "李協理"}]


def test_parse_fix_list_rejects_length_explosion_and_collapse():
    raw = '[{"from": "好", "to": "很好很好很好很好很好"}, {"from": "劉課長送預算表", "to": "預算書"}]'
    assert tp.parse_fix_list(raw) == []


def test_parse_fix_list_salvages_items_from_truncated_output():
    # num_predict 用完時陣列沒有收尾；已完整的項目仍要採用，未完成的那筆丟掉。
    raw = '[\n  {"from": "李協里", "to": "李協理"},\n  {"from": "辛光材料", "to": "新光材料"},\n  {"from": "涼'
    assert tp.parse_fix_list(raw) == [
        {"from": "李協里", "to": "李協理"},
        {"from": "辛光材料", "to": "新光材料"},
    ]


def test_polish_reports_progress_per_chunk(monkeypatch):
    async def fake_achat(prompt, system=None, **kwargs):
        return "[]", _FakeBackend()

    monkeypatch.setattr(tp, "achat_complete", fake_achat)
    seen = []
    text = "\n".join(["甲" * 590, "乙" * 590, "丙" * 590])
    res = _run(tp.polish_transcript(text, "fix", on_progress=lambda done, total: seen.append((done, total))))
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert res["stopped"] is False


def test_polish_stops_between_chunks_and_keeps_rest_original(monkeypatch):
    calls = []

    async def fake_achat(prompt, system=None, **kwargs):
        calls.append(prompt)
        return '[{"from": "改報", "to": "改善"}]', _FakeBackend()

    monkeypatch.setattr(tp, "achat_complete", fake_achat)
    text = "\n".join(["改報" + "甲" * 590, "改報" + "乙" * 590, "改報" + "丙" * 590])
    # 第一段做完後「開始錄音」：第二段開始前就要停。
    res = _run(tp.polish_transcript(text, "fix", should_stop=lambda: len(calls) >= 1))
    assert len(calls) == 1
    assert res["stopped"] is True
    assert res["polished"] == "\n\n".join(["改善" + "甲" * 590, "改報" + "乙" * 590, "改報" + "丙" * 590])
    assert res["changes"] == [{"from": "改報", "to": "改善", "count": 1}]


class _FakeCC:
    """測試用的簡轉台灣繁體：只換本檔用到的字。"""

    def convert(self, text):
        return text.translate(str.maketrans({"没": "沒", "伤": "傷", "协": "協", "员": "員"}))


def test_parse_fix_list_drops_script_only_changes(monkeypatch):
    # 模型把繁體「修」成簡體：轉回台灣繁體後與原文相同，必須丟棄；真正的修改仍保留且輸出為繁體。
    monkeypatch.setattr(summary_utils, "_CC", _FakeCC())
    raw = '[{"from": "沒有人受傷", "to": "没有人受伤"}, {"from": "李協里", "to": "李协理"}]'
    assert tp.parse_fix_list(raw) == [{"from": "李協里", "to": "李協理"}]


def test_polish_rewrite_output_is_taiwan_traditional(monkeypatch):
    monkeypatch.setattr(summary_utils, "_CC", _FakeCC())

    async def fake_achat(prompt, system=None, **kwargs):
        return "全员" + "二" * 80, _FakeBackend()

    monkeypatch.setattr(tp, "achat_complete", fake_achat)
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "全員" + "二" * 80


def test_apply_fixes_insertion_leaves_already_correct_text_alone():
    # 補字修改：原本已經正確的「第138個議題」不能再被補一次，變成「第138個議題個議題」。
    text = "第138個議題是預算，第138已經面試"
    new_text, applied = tp.apply_fixes(text, [{"from": "第138", "to": "第138個議題"}])
    assert new_text == "第138個議題是預算，第138個議題已經面試"
    assert applied == [{"from": "第138", "to": "第138個議題", "count": 1}]


def test_apply_fixes_insertion_skips_when_everything_is_already_correct():
    text = "第138個議題是預算"
    new_text, applied = tp.apply_fixes(text, [{"from": "第138", "to": "第138個議題"}])
    assert new_text == text
    assert applied == []
