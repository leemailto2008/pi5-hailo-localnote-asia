"""summary_utils.compact_notes 截斷 map 筆記時不能切斷數字（2026-11-23 localnote@mac，S10 深度審查）。

每條筆記截到 max_len（40）字：40 字內後半段有標點就切在標點，否則在第 40 字硬切。
硬切落在數字中間 → 「…1500萬元」變「…15」、「12.5萬」變「12」、「3,500台」變「3」；
切點清單有半形逗號，千分位「3,500」的逗號也被當成切點 → 只剩「3」。
截斷後的筆記是 reduce 與最後紀要的輸入：數字的值被改掉（CLAUDE.md：數字寧可不寫也不能寫錯）。
同類問題待辦事項以前修過（_cut_item，「…拿到5」），這裡沒有跟上。
"""
import re

import pytest

import summary_utils as su

PREFIX = "設備採購預算經過三輪討論後最後由財務部確認確定為新台幣總額共計"   # 31 字、沒有標點


def _note(num, filler):
    return "- " + PREFIX + filler + num + "並且下週三前送簽完成"


def _numbers(s):
    return re.findall(r"\d[\d,.]*\d|\d", s)


@pytest.mark.parametrize("num", ["1500萬元", "12.5萬元", "3,500台", "250人"])
@pytest.mark.parametrize("filler", ["九" * k for k in range(0, 10)], ids=lambda f: f"pad{len(f)}")   # 數字跨過第 40 字
def test_hard_cut_never_leaves_partial_number(num, filler):
    out = su.compact_notes(_note(num, filler))
    assert len(out) - 2 <= 40
    for n in _numbers(out):                      # 留下來的數字一定是原本完整的數字
        assert n in _numbers(num), (out, num)


def test_thousands_comma_is_not_a_cut_point():
    note = "- 第二季的設備採購預算經過討論確定為3,500萬元另外人力預算再議"   # 40 字以上、唯一的標點是千分位逗號
    out = su.compact_notes(note)
    assert "3,500" in out or not _numbers(out), out


def test_number_fits_and_normal_punctuation_cut_unchanged():
    assert su.compact_notes("- 預算：80萬元") == "- 預算：80萬元"
    long_ = "- 教育訓練的報名人數目前是二十二人另外還有三位候補，場地和講師的時間安排與費用都還要再確認一次"
    assert su.compact_notes(long_) == "- 教育訓練的報名人數目前是二十二人另外還有三位候補"   # 後半段的「，」：切在標點（既有行為）


def test_whole_note_is_a_number_falls_back_to_hard_cut():
    out = su.compact_notes("- " + "1" * 60)
    assert out == "- " + "1" * 40                 # 整條都是數字：沒得退，照舊硬切（不回空白）
