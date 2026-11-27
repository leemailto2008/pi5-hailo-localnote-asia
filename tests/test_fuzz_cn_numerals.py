"""P13（2026-11-27 localnote@mac）：國字數字換阿拉伯數字（cn_numerals_to_digits、fix_numerals）的 hypothesis fuzz。
性質：fix_numerals 不生出數字（輸出的數值都在原文或譯文讀得到的數值裡）；數值本來就對的譯文不動；做兩次和一次一樣。"""
import os
import tempfile

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

hypothesis.configuration.set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "hyp_p13"))
import transcript_translate as tt  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=2000 if SLOW else 40, deadline=None, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow])

ZH = st.sampled_from(["十輪", "第一季", "九月二日", "二十二人", "百分之六", "台北一零一", "三零二室", "二〇二六年", "零件", "零售",
                      "零星", "歸零", "一起", "一一確認", "萬一", "統一", "唯一", "一下", "三合一", "兩家", "十家", "零點五",
                      "供應商", "，", "。", "的", "要", "和"])
EN = st.sampled_from(["10 rounds", "Q1", "September 2", "22 people", "6%", "Taipei 101", "room 302", "2026", "parts", "retail",
                      "together", "one by one", "just in case", "unified", "2 companies", "10 suppliers", "0.5", ", ", "and"])


def _vals(s, words=False):
    return {round(v, 6) for v in tt.number_values(s, words=words)}


@CFG
@given(st.lists(EN, max_size=8).map(" ".join), st.lists(ZH, max_size=10).map("".join))
def test_fix_numerals_no_new_numbers(src, tr):
    out = tt.fix_numerals(src, tr, "zh")
    prepared = tt.prepare_source(src, "zh")
    if tt.numbers_ok(prepared, tr):
        assert out == tr
    elif out != tr:
        assert tt.numbers_ok(prepared, out), (src, tr, out)
        assert _vals(out) <= _vals(prepared) | _vals(tt.cn_numerals_to_digits(tr)), (src, tr, out)
        # 「零件」「零售」「零星」「歸零」的零不會變成 0（P18：原本用「沒有 0」粗略判斷，「百分之六十輪」的 60% 被誤判）
        assert not any(w in out for w in ("0件", "0售", "0星", "歸0")), (src, tr, out)
    assert tt.fix_numerals(src, out, "zh") == out
