"""transcript_translate.prepare_source：英翻中把 million／billion 換成「萬／億」時不能丟精度。
2026-11-23 localnote@mac（S13 深度審查）：原本 f"{v / 10**4:g}萬" 只留 6 位有效數字 →
「12.345678 million」→「1234.57萬」（12,345,678 變 12,345,700）、「1.2345678 billion」→「12.3457億」。
numbers_ok 比的是 prepare_source 之後的文字，模型照抄改過的數字也會通過 → 錯的數字被當成正確的翻譯。
（CLAUDE.md 重點十：數值對不上就保留原文，寧可不翻也不翻錯數字）
"""
import pytest

import transcript_translate as tt


@pytest.mark.parametrize("src", [
    "The budget is 12.345678 million dollars.",
    "Revenue reached 1.2345678 billion.",
    "We need 2.5 million.",
    "about 11 billion",
    "costs 0.75 million in total",
    "a total of 123.456789 billion",
])
def test_prepare_source_zh_keeps_values(src):
    prepared = tt.prepare_source(src, "zh")
    assert tt.number_values(prepared) == tt.number_values(src), prepared


def test_wrong_echo_is_rejected():
    src = "The budget is 12.345678 million dollars."
    prepared = tt.prepare_source(src, "zh")
    assert "1234.5678萬" in prepared
    assert not tt.numbers_ok(prepared, "預算是1234.57萬美元。")       # 被四捨五入的數字對不上


@pytest.mark.parametrize("src,expect", [
    ("We need 2.5 million.", "We need 250萬."),
    ("about 11 billion", "about 110億"),
    ("about 200 million", "about 2億"),
])
def test_common_cases_unchanged(src, expect):
    assert tt.prepare_source(src, "zh") == expect
