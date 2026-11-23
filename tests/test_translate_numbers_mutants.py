"""transcript_translate 數字與金額轉換的突變測試補強（2026-11-23 localnote@mac，S19）。
S19 對 main 的 _scaled／number_values／numbers_ok／_mixed_value／fix_mixed_numbers／prepare_source／_cn_to_int／
cn_numerals_to_digits／fix_numerals／unit_ok 做 132 個突變，原本的 test_transcript_translate.py 殺掉 119 個、存活 13 個。
"""
import pytest

import transcript_translate as tt


@pytest.mark.parametrize("text,want", [
    ("加裝2十個警示燈", "加裝20個警示燈"),          # 十後面沒有個位
    ("第1十23個議題", "第1十23個議題"),            # 十後面超過一位：看不懂，原樣保留
    ("十1十個", "十1十個"),                        # 兩個「十」：原樣保留（突變版拆不開會當掉）
    ("第1三個議題", "第13個議題"),
])
def test_mixed_numbers_edges(text, want):
    assert tt.fix_mixed_numbers(text) == want


@pytest.mark.parametrize("src,want", [
    ("about 100 million", "about 1億"),            # 剛好 1 億用「億」
    ("about 200 million", "about 2億"),
    ("We need 2.5 million.", "We need 250萬."),
    ("costs 9.9 million", "costs 990萬"),          # 1 億以下用「萬」
])
def test_prepare_zh_scale_boundaries(src, want):
    assert tt.prepare_source(src, "zh") == want


def test_fix_numerals_only_for_chinese_target():
    assert tt.fix_numerals("September 2", "九月二日", "en") == "九月二日"     # 翻英文時不動
    assert tt.fix_numerals("September 2", None, "zh") is None
    assert tt.fix_numerals("on September 2", "在九月二日", "zh") == "在9月2日"
