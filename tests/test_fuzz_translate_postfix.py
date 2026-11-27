"""P10（2026-11-27 localnote@mac）：譯文後處理 transcript_translate.postfix 的 hypothesis fuzz。
性質：不生出數字（譯文和原文都沒有的數值）；原本數值都對的譯文，後處理後還是對；做兩次和一次一樣；不當掉。
沒裝 hypothesis 時整檔 skip；PI5_FUZZ_SLOW=1 每個性質 2,000 例。"""
import os
import tempfile

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

hypothesis.configuration.set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "hyp_p10"))
import transcript_translate as tt  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=2000 if SLOW else 40, deadline=None, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])

ZH = st.sampled_from(["蔡組長", "吳副理", "許經理", "新竹", "台中", "Taipei 101", "星期五", "週三", "聯華精密", "預算", "交貨",
                      "3 台", "1,200 台", "2.5 萬", "30%", "12 月 10 日", "三十人", "第 2 季", "，", "。", "要", "在", "的"])
EN = st.sampled_from(["Team Lead蔡", "Team Lead Cai", "Captain", "Manager許", "Hsinchu", "Taichung", "Taipei 101", "Friday",
                      "星期五", "budget", "delivery", "3 units", "1,200 units", "25,000", "30%", "December 10", "thirty people",
                      "Q2", "one", "two rounds", ", ", ". ", "the", "in", "is", "the plan, " * 5, "OK OK OK OK OK"])
ZH_TR = st.sampled_from(["蔡組長", "團隊負責人", "星期五", "Friday", "新竹", "預算", "3 台", "1,200 台", "2.5 萬", "30%",
                         "12月10日", "，", "。", "好的好的好的好的", "Team Lead"])
EN_SRC = st.sampled_from(["Team Lead Cai", "Friday", "budget", "3 units", "1,200 units", "25,000", "30%", "December 10",
                          "Taipei", "the", ", ", ". "])


def _vals(s, words=False):
    return {round(v, 6) for v in tt.number_values(s, words=words)}


@CFG
@given(st.lists(ZH, max_size=12).map("".join), st.lists(EN, max_size=12).map(" ".join))
def test_postfix_zh_to_en(src, tr):
    out = tt.postfix(src, tr, "en")
    out = out if out is not None else tr
    assert _vals(out, True) <= _vals(tr, True) | _vals(src), (src, tr, out)
    if tt.numbers_ok(src, tr):
        assert tt.numbers_ok(src, out), (src, tr, out)
    again = tt.postfix(src, out, "en")
    assert (again if again is not None else out) == out, (src, tr, out, again)


@CFG
@given(st.lists(EN_SRC, max_size=10).map("".join), st.lists(ZH_TR, max_size=12).map("".join))
def test_postfix_en_to_zh(src, tr):
    out = tt.postfix(src, tr, "zh")
    out = out if out is not None else tr
    assert _vals(out, True) <= _vals(tr, True) | _vals(src), (src, tr, out)
    if tt.numbers_ok(src, tr):
        assert tt.numbers_ok(src, out), (src, tr, out)
    again = tt.postfix(src, out, "zh")
    assert (again if again is not None else out) == out, (src, tr, out, again)


@CFG
@given(st.text(max_size=60), st.text(max_size=60), st.sampled_from(["en", "zh"]))
def test_postfix_never_crashes(src, tr, target):
    tt.postfix(src, tr, target)


@CFG
@given(st.lists(ZH, max_size=12).map("".join), st.lists(EN, max_size=12).map("".join))
def test_postfix_zh_to_en_glued_stable(src, tr):
    # 模型輸出常常沒有空白（「Team Lead蔡星期五」）：黏在一起時只要求做兩次和一次一樣（數字詞黏著時 number_values 讀不到，不比數值）
    out = tt.postfix(src, tr, "en")
    out = out if out is not None else tr
    again = tt.postfix(src, out, "en")
    assert (again if again is not None else out) == out, (src, tr, out, again)
