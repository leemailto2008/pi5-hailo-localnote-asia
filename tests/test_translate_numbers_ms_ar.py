"""11-26 語音語系加馬來文 (ms)、阿拉伯文 (ar)：數值比對要認得阿拉伯文數字／小數點與兩種語言的大數單位，
否則翻對的句子被當成數值不符、保留原文不翻。"""
import pytest

import transcript_translate as tt


@pytest.mark.parametrize("text,want", [
    ("ارتفع الناتج بنسبة ٣٫٥ في المئة عام ٢٠٢٠", [3.5, 2020.0]),     # 原本 [3, 5, 2020]：٫ 不是小數點
    ("١٢٬٥٠٠ دولار", [12500.0]),
    ("استثمار 3 مليار دولار", [3e9]), ("٥٠٠ ألف", [5e5]), ("2 مليون", [2e6]),
    ("RM1.2 bilion", [1.2e9]), ("5 juta orang", [5e6]), ("20 ribu", [2e4]), ("1 trilion", [1e12]),
])
def test_number_values_ms_ar(text, want):
    assert tt.number_values(text) == want


@pytest.mark.parametrize("src,tr", [
    ("ارتفع ٣٫٥ عام ٢٠٢٠", "增长3.5%，2020年"),
    ("استثمار 3 مليار دولار", "投资30亿美元"),
    ("RM1.2 bilion", "12亿令吉"),
    ("5 juta orang", "500万人"),
])
def test_numbers_ok_after_prepare_zh(src, tr):
    assert tt.numbers_ok(tt.prepare_source(src, "zh"), tr)


def test_prepare_zh_converts_scale_words():
    assert tt.prepare_source("RM1.2 bilion dan 5 juta", "zh") == "RM12億 dan 500萬"
    assert tt.prepare_source("٣٫٥", "zh") == "3.5"


def test_arabic_left_in_zh_translation_is_untranslated():
    assert tt.untranslated_left("這項服務的目標是提供給使用者ما ن推ب", "zh")
    assert not tt.untranslated_left("這項服務的目標是提供給使用者", "zh")


def test_arabic_with_english_words_is_not_english():
    assert not tt.in_target_language("هذا النخفاد the fastest in the production process and the use of the waste", "en")
