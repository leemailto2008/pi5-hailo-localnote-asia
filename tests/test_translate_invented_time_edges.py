"""P19（2026-11-27 localnote@mac）：01afbbd drop_invented_time 與 P13／P18 國字數字轉換的邊界（突變測試補強）。
每個數字字元、每種鐘點／年份寫法各一例。"""
import pytest

import transcript_translate as tt

CN = "一二三四五六七八九"
INV = "Switch on June 15 at 22:00."           # 原文只有「晚上」時「at 22:00」是編的
EV = "Switch on June 15 in the evening."


# ---- 原文有鐘點就不動 --------------------------------------------------------------------------------
@pytest.mark.parametrize("clock", [f"{c}點" for c in "0123456789零一二兩两三四五六七八九十"] +
                         [f"{c}時" for c in "8八"] + ["八点", "八时", "8 點", "8:00", "8：00", "8pm", "8 PM", "8am", "8 Am",
                                                   "8 p.m.", "8 a.m.", "8 P.M.", "8 A.M.", "8 pM", "8 Pm", "8 o'clock"])
def test_src_clock_blocks_drop(clock):
    assert tt.drop_invented_time(f"6月15日晚上{clock}切換", INV, "en") == INV


@pytest.mark.parametrize("word", ["時間", "时间", "時段"])
def test_src_time_words_are_not_clock(word):
    assert tt.drop_invented_time(f"6月15日晚上找八{word}切換", INV, "en") == EV


# ---- 原文有年份就不動 --------------------------------------------------------------------------------
YR = "The fair is on March 21, 2023."
NOYR = "The fair is on March 21."


@pytest.mark.parametrize("y", ["年", "2023", "1999", "二〇二三", "二零二三"] + [d * 4 for d in CN] + ["〇〇〇〇", "零零零零"])
def test_src_year_blocks_drop(y):
    assert tt.drop_invented_time(f"{y} 3月21日的展覽", YR, "en") == YR


@pytest.mark.parametrize("day", ["日", "號", "号"])
def test_src_month_day_variants(day):
    assert tt.drop_invented_time(f"3月21{day}的展覽", YR, "en") == NOYR
    assert tt.drop_invented_time(f"3月{day}的展覽", YR, "en") == NOYR      # 月和日中間 0 個字也算


@pytest.mark.parametrize("tr,want", [
    ("on March 21, 2023.", "on March 21."), ("on March 21 2023.", "on March 21."), ("on March 21st, 2023.", "on March 21st."),
    ("on 21 March, 2023.", "on 21 March."), ("on 21st March 2023.", "on 21st March."), ("on 1 March, 2023.", "on 1 March."),
    ("on March 1, 1999.", "on March 1."), ("on January 5, 2023.", "on January 5."), ("on 5 January 2023.", "on 5 January."), ("on March 21, 2023,000 units.", "on March 21, 2023,000 units."),
    ("on March 21, 20234.", "on March 21, 20234."),
])
def test_added_year_forms(tr, want):
    assert tt.drop_invented_time("3月21日的展覽", tr, "en") == want


# ---- 編出來的鐘點寫法 --------------------------------------------------------------------------------
@pytest.mark.parametrize("tr,want", [
    ("at 9:00.", "in the evening."), ("at 22:00 PM.", "in the evening."), ("at 9:00 pm.", "in the evening."),
    ("at 9:00 a.m.", "in the evening"), ("at 9:00 p.m. today", "in the evening today"), ("at 9:00 PM today", "in the evening today"),
    ("at 9:00 P.M. today", "in the evening today"), ("at 9:00 A.M. today", "in the evening today"), ("at 9:00 Am.", "in the evening."), ("at 9:00 aM.", "in the evening."),
    ("at 9:00PM.", "in the evening."), ("at 9:00 Amsterdam.", "in the evening Amsterdam."),
    ("for 9:00 PM.", "for the evening."), ("for 9:00 am.", "for the evening."), ("for 9:00 A.M.", "for the evening"),
    ("for 9:00 Pm.", "for the evening."), ("for 9:00PM.", "for the evening."), ("for 2:00 hours.", "for 2:00 hours."),
    ("for 9:00 Amsterdam.", "for 9:00 Amsterdam."), ("at 9:00 PMs", "in the evening PMs"),
])
def test_added_clock_forms(tr, want):
    assert tt.drop_invented_time("6月15日晚上切換", tr, "en") == want


# ---- 國字數量剛好像年份：不拿 -------------------------------------------------------------------------
@pytest.mark.parametrize("n,cn", [(2013, "兩千零一十三"), (2034, "兩千零三十四"), (2046, "兩千零四十六"), (2057, "兩千零五十七"),
                                  (2068, "兩千零六十八"), (2079, "两千零七十九"), (2081, "二千零八十一"), (2099, "兩千零九十九"),
                                  (1900, "一千九百"), (2000, "兩千")])
def test_year_like_cn_quantity_kept(n, cn):
    tr = f"On March 21, {n} units."
    assert tt.drop_invented_time(f"3月21日出貨{cn}台", tr, "en") == tr
    assert tt.drop_invented_time(f"3月21日出貨{cn}箱", tr, "en") == tr      # 「箱」不在量詞清單：要靠國字數字串換算


# ---- 逐字號碼 ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("d", list(CN))
def test_digit_run_each_digit(d):
    n = str(CN.index(d) + 1)
    assert tt.cn_numerals_to_digits(f"編號{d}零{d}") == f"編號{n}0{n}"
    assert tt.cn_numerals_to_digits(f"編號{d}〇{d}") == f"編號{n}0{n}"


@pytest.mark.parametrize("u", list("十百千萬万億亿"))
def test_digit_run_not_after_units(u):
    assert "101" not in tt.cn_numerals_to_digits(f"編號{u}一零一")


@pytest.mark.parametrize("u", list("十百千"))
def test_digit_run_not_before_units(u):
    assert "101" not in tt.cn_numerals_to_digits(f"編號一零一{u}")      # 「一零一萬」由量詞那條讀成 101萬，是對的


@pytest.mark.parametrize("s,want", [("零一零", "010"), ("一零", "一零"), ("一一一", "一一一"), ("台北一零一零", "台北1010"),
                                    ("零件一零一", "零件101"), ("A零一零", "A010")])
def test_digit_run_edges(s, want):
    assert tt.cn_numerals_to_digits(s) == want


@pytest.mark.parametrize("s,want", [("〇件", "〇件"), ("零件", "零件"), ("一零件", "1零件"), ("零零件", "零零件"), ("歸〇三人", "歸〇3人"),
                                    ("三人", "3人"), ("零三人", "3人"), ("百分之六", "6%"), ("百分之", "百分之")])
def test_measure_path_zero_words(s, want):
    assert tt.cn_numerals_to_digits(s) == want
