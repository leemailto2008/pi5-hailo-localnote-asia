"""P3（2026-11-27 localnote@mac）：PC 11-25 之後新加的譯文後處理（fix_wrong_place、collapse_repeats）的突變測試補強。"""
import pytest

import transcript_translate as tt


def test_collapse_long_and_short_units():
    assert tt.collapse_repeats("這種情況，" * 8 + "結束") == "這種情況，結束"          # 8 次也只留一次（不是兩次）
    assert tt.collapse_repeats("詩、" * 6) == "詩、"                                   # 2 個字的單位
    assert tt.collapse_repeats("好" * 3) == "好" * 3                                    # 只有 1 個字不算
    assert tt.collapse_repeats("哈哈哈哈哈哈哈哈") == "哈哈"
    assert tt.has_repeat_loop("abab " * 4) and not tt.has_repeat_loop("abab " * 3)


def test_wrong_place_only_for_english_target():
    assert tt.postfix("新竹的聯華精密", "在Taichung的聯華精密", "zh") == "在Taichung的聯華精密"


@pytest.mark.parametrize("tr", ["Lianghua in Taichungtown", "Lianghua in xTaichung", "Lianghua in XTaichung",
                                "Lianghua in TaichungX", "Lianghua in Taichungs"])
def test_wrong_place_must_be_whole_word(tr):
    assert tt.fix_wrong_place("新竹的聯華精密", tr, "en") == tr


@pytest.mark.parametrize("src", ["新竹廠和 xTaipei 那邊", "新竹廠和 XTaipei 那邊", "新竹廠和 Taipeix 那邊", "新竹廠和 TaipeiX 那邊"])
def test_english_place_in_source_must_be_whole_word(src):
    # 原文的英文地名要是完整的字才算「原文講過」；黏在別的字裡不算，照樣換回原文的縣市
    assert tt.fix_wrong_place(src, "The plant and Taipei", "en") == "The plant and Hsinchu"
