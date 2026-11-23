"""千分位 + million／billion、千分位 + 小數（2026-11-23 localnote@mac，S18 fuzz 找到）。
- prepare_source(英翻中)：_EN_SCALED_RE 只吃 \\d+(\\.\\d+)?，「1,500 million」只換掉「500 million」→「1,5億」（應為 15億）；
  numbers_ok 比的是換過的文字，模型照抄錯的「1,5億」會通過、翻對的「15億」反而被擋。
- number_values：千分位後面接小數「1,234.5」被讀成 1234 與 5 兩個數。
（hypothesis 最小化後的輸入：「1.0001千」→ prepare_source 英 →「1,000.1」→ number_values [1000, 1]）
"""
import pytest

import transcript_translate as tt


@pytest.mark.parametrize("src,expect", [
    ("Revenue was 1,500 million dollars.", "Revenue was 15億 dollars."),
    ("12,000 million", "120億"),
    ("a budget of 1,234.5 million", "a budget of 12.345億"),
    ("2,500 billion", "25000億"),
    ("2.5 million", "250萬"),                       # 原本就對的不變
    ("about 11 billion", "about 110億"),
])
def test_prepare_zh_thousands_scaled(src, expect):
    assert tt.prepare_source(src, "zh") == expect


def test_correct_translation_accepted_wrong_rejected():
    prepared = tt.prepare_source("Revenue was 1,500 million dollars.", "zh")
    assert tt.numbers_ok(prepared, "營收為15億美元。")
    assert not tt.numbers_ok(prepared, "營收為1,5億美元。")


@pytest.mark.parametrize("text,vals", [
    ("1,234.5", [1234.5]),
    ("3,500.75 units", [3500.75]),
    ("1,000.1", [1000.1]),
    ("12,345", [12345.0]),
    ("105 000 hectares", [105000.0]),
    ("3.5 and 1,000", [3.5, 1000.0]),
    ("items 1,000. 5 more", [1000.0, 5.0]),        # 句點後有空白：不是小數
])
def test_number_values_thousands_decimal(text, vals):
    assert tt.number_values(text) == vals


def test_prepare_en_decimal_thousands_roundtrip():
    """hypothesis 最小化的輸入：「1.0001千」換成「1,000.1」，數值要讀回 1000.1。"""
    assert tt.number_values(tt.prepare_source("預算1.0001千元", "en")) == [1000.1]
