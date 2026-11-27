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


@pytest.mark.parametrize("s", ["最多1-2日", "至少3-5日", "平均2.5日", "延後1-2日", "延遲3-5日", "提前1-2日", "每1-2日", "共3-5日",
                               "前後3-5日", "頂多2-3日", "只需2-3日", "延後1-2日為限", "3-5日一次"])
def test_more_duration_contexts(s):
    # P24：這些前後文一定是天數（最多、至少、平均、延後、提前、每、共、為限、一次…）
    assert "月" not in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s,want", [("需要 4 於 26 日上線", "4月26日"), ("大約 11 夜15日晚上", "11月15日"), ("延後到 1 於 24 日", "1月24日")])
def test_misheard_month_words_not_treated_as_ranges(s, want):
    # P24：「於／夜」是「月」聽錯，不會是天數範圍：前面有「需要／大約」也照樣修成日期（P21 的判斷只看「-」「.」）
    assert want in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("c", list("日號号萬千百元%臺台個位人天點週周年次場支件批輪張份.:：月折倍歲") + ["3", "，3", ",3", "成"])
def test_missing_day_exclusions_each_char(c):
    # P25 突變補強：「月」後面的數字接這些字（量詞、單位、已經有日／號）時不補「日」
    s = f"在3月5{c}"
    out = fix_meeting_terms(s)
    assert "5日" not in out or c in "日月", (s, out)


@pytest.mark.parametrize("s,want", [("10月31的會", "10月31日"), ("12月30上線", "12月30日"), ("11月1的會", "11月1日"),
                                    ("3月21st的會", "3月21日"), ("5月10，日前", "5月10日前"), ("5月10,日前", "5月10日前"),
                                    ("5月10成立", "5月10日成立"), ("5月9上線", "5月9日上線")])
def test_missing_day_boundaries(s, want):
    assert want in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s", ["0.3月5的會"])
def test_missing_day_not_after_decimal(s):
    assert "5日" not in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s,ok", [("我們大約需要3-5日", True), ("需要我們3-5日", False)])
def test_duration_before_window(s, ok):
    # 「需要／大約」要緊接在數字前面（往前看 4 個字以內）
    assert ("月" not in fix_meeting_terms(s)) == ok, fix_meeting_terms(s)


@pytest.mark.parametrize("w", ["成立", "成交", "成果", "成功", "成員", "成為", "成長"])
def test_missing_day_cheng_words(w):
    assert "5月10日" + w in fix_meeting_terms(f"5月10{w}"), fix_meeting_terms(f"5月10{w}")


def test_duration_before_with_space():
    assert "月" not in fix_meeting_terms("保固期 3-5日"), fix_meeting_terms("保固期 3-5日")


@pytest.mark.parametrize("s,bad", [("這是no one的問題", "一"), ("用 one drive 存", "一"), ("我們team one負責", "一"),
                                   ("他說one more時", "一"), ("那個ten的問題", "十")])
def test_en_number_word_needs_measure_word(s, bad):
    # P26：英文數字字只在後面緊接量詞時才換成國字（「two個職缺」「six 月」）；「no one的」「one drive」不是數字（原本生出「一」）
    assert bad not in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s,want", [("有two個職缺", "二個職缺"), ("第three個議題", "第三個議題"), ("聯發科 six 月", "六月"),
                                    ("目前er two 個職缺", "二個"), ("招募 five 人", "五人"), ("請 ten 位同仁", "十位")])
def test_en_number_word_before_measure_still_converted(s, want):
    assert want in fix_meeting_terms(s), fix_meeting_terms(s)


def test_en_number_word_followed_by_noise_still_converted():
    # P26：實錄「業務部目前，two of 職已經面世了15位候選人」的 of 是「個」聽錯，照舊換成「二」
    assert "二職" in fix_meeting_terms("業務部目前，two of 職已經面世了15位候選人")


@pytest.mark.parametrize("s", ["公司有十個部門", "總共十個部門參加", "請十個部門回覆", "十個部門的預算", "我們邀請了十個部門"])
def test_ten_departments_kept_outside_todo_recap(s):
    # P27：「十個部門」只在「待辦事項」後面才是「是各部門」聽錯（實錄 17 處）；其他地方是真的數量，不能拿掉 10
    assert "十個部門" in fix_meeting_terms(s), fix_meeting_terms(s)


@pytest.mark.parametrize("s,want", [("3為工程師", "3位工程師"), ("三圍候選人", "三位候選人"), ("第100個議題", "第100個議題"),
                                    ("第1個月", "第1個月"), ("第2個季度", "第2個季度"), ("3D為工程師", "3D為工程師")])
def test_topic_and_headcount_keep_numbers(s, want):
    assert fix_meeting_terms(s) == want
