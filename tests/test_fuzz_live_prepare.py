"""N7（2026-11-24 localnote@mac）：即時翻譯前處理（transcript_translate.prepare_source／number_values／_split_long）的 hypothesis fuzz。

原則（N3「看不懂整串保留」）：不准憑空生出數字。每個數字段落送出去時，要嘛原樣保留（之後數值對不上就保留原文），
要嘛讀出來的數值和真值完全相同；而且一句裡有好幾個數字時，彼此不互相影響（跟單獨處理時一樣）。
- 預設快速模式：每個性質 max_examples 40、deadline 300 ms、derandomize、不寫 .hypothesis/。PI5_FUZZ_SLOW=1：2,000 例、不設 deadline。
- 沒裝 hypothesis 時整檔 skip。
"""
import os
import tempfile
from decimal import Decimal

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, assume, given, settings, strategies as st  # noqa: E402
from hypothesis.configuration import set_hypothesis_home_dir  # noqa: E402

set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "pi5_localnote_hypothesis"))

import transcript_translate as tt  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=2000 if SLOW else 40, deadline=None if SLOW else 300, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])

_D = "零一二三四五六七八九"
_FULL = str.maketrans("0123456789,.", "０１２３４５６７８９，．")


def cn(n: int) -> str:
    """0 < n < 10^12 的標準國字讀法（兩萬五千、一億二千萬、三萬零五百）。"""
    def sec(v: int) -> str:
        out, zero = "", False
        for unit, u in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
            d = v // u % 10
            if d:
                out += ("零" if zero else "") + ("" if unit == "十" and d == 1 and v < 20 and not out else _D[d]) + unit
                zero = False
            elif out:
                zero = True
        return out
    parts, rest = [], n
    for unit, u in (("億", 10 ** 8), ("萬", 10 ** 4)):
        if rest >= u:
            parts.append(sec(rest // u) + unit)
            rest %= u
            if rest and rest < u // 10:
                parts.append("零")
    if rest:
        parts.append(sec(rest))
    return "".join(parts)


def half_itn(n: int) -> str:
    def sec(v: int) -> str:
        out, zero = "", False
        for unit, u in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
            d = v // u % 10
            if d:
                out, zero = out + ("零" if zero else "") + str(d) + unit, False
            elif out:
                zero = True
        return out
    parts, rest = [], n
    for unit, u in (("億", 10 ** 8), ("萬", 10 ** 4)):
        if rest >= u:
            parts.append(sec(rest // u) + unit)
            rest %= u
            if rest and rest < u // 10:
                parts.append("零")
    if rest:
        parts.append(sec(rest))
    return "".join(parts)


def renders(n: int):
    """n 的各種寫法（ITN／ASR 可能的輸出）。"""
    out = {"digits": str(n), "fullwidth": str(n).translate(_FULL), "cn": cn(n), "half": half_itn(n)}
    if n >= 1000:
        out["comma"] = f"{n:,}"
    if n % 10 ** 4 == 0:
        out["wan"] = f"{n // 10 ** 4}萬"
        if n // 10 ** 4 >= 1000:
            out["wan_comma"] = f"{n // 10 ** 4:,}萬"
    if n % 1000 == 0 and n >= 10 ** 4:
        out["wan_dec"] = format((Decimal(n) / 10 ** 4).normalize(), "f") + "萬"
    a, b = divmod(n, 10 ** 4)
    if a and b and b % 1000 == 0:
        out["colloq"] = f"{a}萬{b // 1000}"                   # 三萬五＝35,000
    c = cn(n)
    if c and c[-1] in _D[1:]:
        out["sv_mixed"] = c[:-1] + str(_D.index(c[-1]))          # SenseVoice 個位數字寫成阿拉伯數字：「二十5」
    return out


NUMS = st.one_of(st.integers(1, 99), st.integers(100, 9999), st.integers(1, 9999).map(lambda k: k * 10 ** 4),
                 st.integers(1, 99).map(lambda k: k * 1000 + 10 ** 4), st.integers(10 ** 4, 10 ** 9), st.integers(10 ** 8, 10 ** 11))
UNITS = st.sampled_from(["元", "人", "台", "個", "%", "", "。", "臺", "件", "天"])
PREFIX = st.sampled_from(["預算", "大約", "總共", "請準備", "", "我們有", "這次是"])


def _one(n, style, unit):
    r = renders(n)
    assume(style in r)
    return r[style] + unit


def _check_segment(seg: str, n: int) -> list:
    """單獨一段：原樣保留，或讀出來剛好是真值。回傳這段處理後的數值 (給整句比對)。"""
    p = tt.prepare_source(seg, "en")
    vals = tt.number_values(p)
    if p != seg:
        assert vals == [float(n)], (seg, p, vals)
    return vals


@CFG
@given(NUMS, st.sampled_from(["digits", "fullwidth", "cn", "half", "comma", "wan", "wan_comma", "wan_dec", "colloq", "sv_mixed"]),
       UNITS, PREFIX)
def test_single_number_kept_or_exact(n, style, unit, prefix):
    seg = prefix + _one(n, style, unit)
    _check_segment(seg, n)


@CFG
@given(NUMS, st.sampled_from(["digits", "half", "comma", "wan", "colloq", "sv_mixed", "cn"]), UNITS,
       NUMS, st.sampled_from(["digits", "half", "comma", "wan", "colloq", "sv_mixed", "cn"]), UNITS,
       st.sampled_from(["，", "、", "，另外", "；還有", " 和 "]))
def test_two_numbers_do_not_interfere(n1, s1, u1, n2, s2, u2, sep):
    a, b = "預算" + _one(n1, s1, u1), _one(n2, s2, u2)
    va, vb = _check_segment(a, n1), _check_segment(b, n2)
    both = tt.number_values(tt.prepare_source(a + sep + b, "en"))
    assert both == va + vb, (a + sep + b, tt.prepare_source(a + sep + b, "en"))


# ASR 常見亂碼：數字字、國字數字、單位、全形、標點、口語贅字隨意混在一起
GARBAGE = st.text(alphabet="0123456789０１２３一二三兩十百千萬万億零〇點.,，、 元人個台%的了是第月日號 ", max_size=24)


@CFG
@given(GARBAGE)
def test_garbage_does_not_crash_and_is_stable(s):
    p = tt.prepare_source(s, "en")
    # 再處理一次數值不會再變 (不會被乘兩次)；文字可能再整理一點 (「0 十」→「0」)，數值相同就好
    assert tt.number_values(tt.prepare_source(p, "en")) == tt.number_values(p), (s, p)
    assert tt.numbers_ok(p, p)                                     # 自己對自己一定對得上


@CFG
@given(GARBAGE)
def test_garbage_never_invents_values(s):
    # 不准憑空生出數字：處理後讀到的每個數，要嘛原文也讀得到，要嘛是原文裡某一串連續的數字／國字／單位換算出來的
    p = tt.prepare_source(s, "en")
    if p == s:
        return
    before, after = tt.number_values(s), tt.number_values(p)
    assert len(after) <= len(before) + s.count("十") + s.count("百") + s.count("千") + 1, (s, p, before, after)
    import re
    # 數量級不能憑空變大：最多是原文最長那串數字字（阿拉伯／全形／國字，逐字讀）的位數，再乘上後面能出現的萬億
    longest = max((len(r) for r in re.findall("[0-9０-９零〇一二兩两三四五六七八九十百千]+", s)), default=0)
    for v in after:
        assert abs(v) < 10 ** (longest + 12), (s, p, v)


@CFG
@given(st.lists(st.one_of(st.text(alphabet="甲乙丙丁，、 ", min_size=1, max_size=30),
                          NUMS.map(lambda n: f"{n:,}"), NUMS.map(str), NUMS.map(lambda n: f"{n / 100:.2f}")), min_size=1, max_size=12))
def test_split_long_never_cuts_numbers(parts):
    s = "甲".join(parts)                                        # 數字之間有文字（整串都是數字時本來就照原樣硬切）
    assume(len(s) > 20)
    pieces = tt._split_long(s, 20)
    assert "".join(pieces).replace(" ", "") == s.replace(" ", "")
    got = [v for p in pieces for v in tt.number_values(p)]
    assert got == tt.number_values(s), (s, pieces)
