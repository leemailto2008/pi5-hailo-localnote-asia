"""P2（2026-11-27 localnote@mac）：ASR 後處理整理兩次要和一次一樣（test_fuzz_e2e_asr 找到的，寫成一般回歸測試，CI 沒裝 hypothesis 也會跑）。
流程照 meeting_minutes（只讀）：clean_live_segment → live_join_sep → tidy_live_transcript → fix_meeting_terms。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # hailo_whisper 在 repo 根目錄
import summary_utils as su  # noqa: E402
from hailo_whisper.engine import fix_meeting_terms  # noqa: E402


def asr_transcript(segs):
    out, prev = "", None
    for s in segs:
        c = su.clean_live_segment(s)
        if not c:
            continue
        out = c if prev is None else out + su.live_join_sep(prev, c) + c
        prev = c
    return fix_meeting_terms(su.tidy_live_transcript(out))


@pytest.mark.parametrize("segs", [["好的the budget、"], ["請the 吳副理，"], ["預算 the 3 萬。"], ["好的", "the budget so", "好的"]],
                         ids=["dunhao", "comma", "period", "double-space"])
def test_latin_noise_removal_leaves_no_space_before_cjk_punct(segs):
    # P2 fuzz：拿掉英文碎片（the）後補的空白留在「、」前面、或變成兩個空白，要等下一次 tidy 才收掉 → 整理兩次結果不一樣
    tr = asr_transcript(segs)
    assert fix_meeting_terms(su.tidy_live_transcript(tr)) == tr, tr


@pytest.mark.parametrize("seg,want", [("我們我們我們要開會", "我們要開會"), ("目前目前目前存1200臺", "目前存1200臺"), ("然後 然後 然後", "然後")])
def test_stutter_collapsed_in_one_pass(seg, want):
    # P2 fuzz：「(目前|已經|我們|然後)\s*\1」一次只收一對，三次重複要整理兩次才收乾淨
    assert fix_meeting_terms(seg) == want


@pytest.mark.parametrize("p", list("，、。"))
def test_no_space_next_to_each_cjk_punct(p):
    # P3：英文碎片會出現在中文字或「，。、」旁邊；拿掉之後這三個標點前後都不留補的空白
    for seg in (f"好的the budget{p}好的", f"好的{p}the budget好的"):
        tr = asr_transcript([seg])
        assert f" {p}" not in tr and f"{p} " not in tr, tr
        assert fix_meeting_terms(su.tidy_live_transcript(tr)) == tr


def test_latin_fragment_exact_output():
    from hailo_whisper.engine import _fix_latin_in_cjk
    assert _fix_latin_in_cjk("好的the budget好") == "好的 budget 好"
    assert _fix_latin_in_cjk("有two 個職缺") == "有二個職缺"              # 英文數字字換成國字，前後不補空白
    assert _fix_latin_in_cjk("請the 吳副理 er 處理") == "請 吳副理 處理" or "the" not in _fix_latin_in_cjk("請the 吳副理 er 處理")


def test_latin_fragment_single_spaces():
    from hailo_whisper.engine import _fix_latin_in_cjk
    assert _fix_latin_in_cjk("好的the budget so好的") == "好的 budget so 好的"


@pytest.mark.parametrize("s", ["預計3-5日內交貨", "需要2-3日", "延長7-14日", "大約3-5日左右", "為期2-3日的訓練", "花了5-7日",
                               "約1.5日", "需要2.5日", "工作天數3-10日", "保固期延長10-14日", "3-5日以內回覆", "3-5日之內", "3-5 日工作天"])
def test_day_ranges_and_durations_not_dates(s):
    # P21：「3-5日內」「需要2-3日」「1.5日」是天數，不是 3月5日、2月3日、1月5日（憑空生出月份）
    assert "月" not in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s,want", [("8-15日前完成", "8月15日前完成"), ("預計12.8日到貨", "預計12月8日到貨"), ("2.15日前提出", "2月15日前提出"),
                                    ("修正版預計 4 於 26 日上線", "4月26日上線"), ("切換定在 11 夜15日晚上", "11月15日晚上")])
def test_misheard_dates_still_fixed(s, want):
    assert want in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s", ["3月1,000台", "12月2,500萬元", "3月1，000台", "預算3月5折", "3月5倍", "他3月5歲", "3月5成"])
def test_missing_day_not_added_to_quantities(s):
    # P22：「月」後面的數字其實是數量（千分位、折、倍、歲、成）時不補「日」（原本「3月1,000台」→「3月1日,000台」，數字被拆開）
    assert "日" not in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s,want", [("延到10月10，比原本", "10月10日"), ("6月21的周會", "6月21日的周會"), ("5月10上線", "5月10日上線"),
                                    ("6月12，日前", "6月12日前")])
def test_missing_day_still_added(s, want):
    assert want in fix_meeting_terms(s), fix_meeting_terms(s)


_Q = ["1,200台", "3.5%", "2,500萬元", "10-15人", "3-5日內", "12.8萬", "0.5個百分點", "第3季", "Q3", "300台", "1.234元", "50/50",
      "3:2", "24小時", "7-11", "3月1,000台", "需要2-3日", "約1.5日", "5折", "1.5倍"]


@pytest.mark.parametrize("q", _Q)
@pytest.mark.parametrize("ctx", ["預計{q}", "{q}，請吳副理處理", "這次{q}的", "第二個議題是預算{q}完成"])
def test_quantities_keep_digit_sequence(q, ctx):
    # P23：數量的阿拉伯數字序列整理前後一樣（不拆、不併、不生出、不吃掉）；日期整理（6. 04. 日→6月4日）不在這裡
    import re
    s = ctx.format(q=q)
    assert re.findall(r"\d+", fix_meeting_terms(s)) == re.findall(r"\d+", s), fix_meeting_terms(s)
