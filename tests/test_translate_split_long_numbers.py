"""transcript_translate._split_long：太長的句子切成翻譯單位時不能切在數字中間。
2026-11-23 localnote@mac（S13 深度審查）：原本沒有標點時在第 limit 字硬切，「1500萬元」→「1」＋「500萬元」；
切點清單也有半形「,」與空白，「12,345,678」的千分位逗號會被當成切點。
兩個單位各自翻譯、各自做 numbers_ok 都會通過（1→1、500萬→5,000,000），組回去數字就錯了，保留原文的防護擋不住。
"""
import random
import re

import pytest

import transcript_translate as tt

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(pieces):
    return [n for p in pieces for n in _NUM.findall(p)]


@pytest.mark.parametrize("pad", range(130, 141))
def test_hard_cut_keeps_number(pad):
    s = "甲" * pad + "1500萬元預算，請財務確認"
    pieces = tt._split_long(s, 140)
    assert "".join(pieces) == s
    assert _numbers(pieces) == ["1500"], pieces


@pytest.mark.parametrize("pad", range(90, 141, 5))
def test_thousands_comma_is_not_a_cut(pad):
    s = "乙" * pad + "追加12,345,678元給研發部門" + "丙" * 60
    pieces = tt._split_long(s, 140)
    assert "".join(pieces) == s
    assert "12,345,678" in _numbers(pieces), pieces


def test_decimal_not_split():
    s = "丁" * 138 + "3.75萬"
    assert _numbers(tt._split_long(s, 140)) == ["3.75"]


def test_plain_text_unchanged():
    s = "戊" * 100 + "，" + "己" * 100
    assert tt._split_long(s, 140) == ["戊" * 100 + "，", "己" * 100]


def test_all_digits_still_bounded():
    s = "9" * 300
    pieces = tt._split_long(s, 140)
    assert "".join(pieces) == s and all(len(p) <= 140 for p in pieces)


def test_fuzz_content_and_length():
    rng = random.Random(13)
    alphabet = "會議預算追加給部門，、 ,0123456789."
    for _ in range(2000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 500))).strip()
        pieces = tt._split_long(s, 140)
        assert all(len(p) <= 140 for p in pieces)
        assert "".join(pieces).replace(" ", "") == s.replace(" ", "")
