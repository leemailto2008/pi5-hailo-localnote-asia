"""N5（2026-11-24 localnote@mac）：數值比對（number_values／numbers_ok）與數字寫法修正的突變測試補強。
AST 突變（number_values、numbers_ok、_EN_KM_RE、_DOT_THOUSANDS_RE、_NUM_RE、_mixed_value、fix_mixed_numbers、_MIXED_NUM_RE、
cn_numerals_to_digits、_cn_to_int、_CN_NUM_RE、_CN_PERCENT_RE、fix_numerals、unit_ok、_in_number）：339 個原本存活 145 個。
找到的 bug：「1,500K」讀成 1,500 與 500,000（_EN_KM_RE 不認千分位），翻對的譯文被當成數值不符。"""
import pytest

import transcript_translate as tt

NV = lambda t: tt.number_values(t, words=True)


@pytest.mark.parametrize("text,want", [
    ("budget 1,500K yuan", [1500.0, 1500000.0]),     # 原本 [1500, 500000]（_NUM_RE 讀到 1,500，K 只吃到 500K）
    ("1,500.5K", [1500.5, 1500500.0]),
    ("80K", [80.0, 80000.0]), ("80k", [80.0, 80000.0]), ("2M", [2.0, 2000000.0]), ("1.5M", [1.5, 1500000.0]),
    ("80Kg", [80.0]), ("80KB", [80.0]), ("a80K", [80.0]), ("x80k", [80.0]), ("80.K", [80.0]),
    ("Plan K is fine", []), ("K-pop", []),
])
def test_en_km_shorthand(text, want):
    assert sorted(NV(text)) == want


def test_en_km_thousands_passes_number_check():
    assert tt.numbers_ok(tt.prepare_source("預算150萬元", "en"), "budget 1,500K yuan")
    assert not tt.numbers_ok(tt.prepare_source("預算150萬元", "en"), "budget 500K yuan")


@pytest.mark.parametrize("text,want", [("5 million", [5000000.0]), ("3 thousand", [3000.0]), ("2 billion", [2e9]),
                                       ("6 millones", [6000000.0]), ("1.5 milliards", [1.5e9]), ("7 juta", [7000000.0])])
def test_scale_words(text, want):
    assert tt.number_values(text) == want


@pytest.mark.parametrize("src,tr,ok", [
    ("4.000 viviendas", "4000 homes", True), ("4.000 viviendas", "4 homes", True),     # 句點後 3 位：千分位或小數兩種讀法
    ("1.234.567 personas", "1234567 people", True), ("400.000", "400,000", True),
    ("x.400.000 y", "400000", False), ("400.000.5", "400000", False),            # 前後接句點：讀法不明，不放寬
])
def test_dot_thousands(src, tr, ok):
    assert tt.numbers_ok(src, tr) is ok


@pytest.mark.parametrize("s,i,want", [
    ("1,234", 1, True), ("1.75", 1, True), ("1 234", 1, True), ("12", 1, True), ("3.75", 2, True), ("3,750", 2, True),
    ("a,234", 1, False), ("1,b", 1, False), ("1,", 1, False), ("1.", 1, False), ("1 ", 1, False),
    (".7", 1, False), ("x.7", 2, False), ("x7", 1, False), ("7x", 1, False), (",7", 1, False),
    ("12", 0, False), ("12", 2, False), ("12", 3, False), ("1, 2", 1, False), ("1,2", 2, True),
])
def test_in_number(s, i, want):
    assert tt._in_number(s, i) is want


@pytest.mark.parametrize("cn,want", [("零", 0), ("〇", 0), ("一", 1), ("二", 2), ("兩", 2), ("两", 2), ("三", 3), ("四", 4),
                                     ("五", 5), ("六", 6), ("七", 7), ("八", 8), ("九", 9), ("十", 10), ("一百", 100),
                                     ("十五", 15), ("九十九", 99)])
def test_percent_each_numeral(cn, want):
    assert tt.cn_numerals_to_digits(f"成長百分之{cn}") == f"成長{want}%"


_MIX_UNITS = "個个位台臺人輪轮只隻件條条日號号月年天週周次場场名家款項项輛辆張张支組组萬万千百億亿元%％倍"


@pytest.mark.parametrize("u", list(_MIX_UNITS))
def test_mixed_number_each_unit(u):
    assert tt.fix_mixed_numbers(f"共1三{u}") == f"共13{u}"


@pytest.mark.parametrize("c", list("百千萬億兩"))
def test_mixed_number_not_after_numeral(c):
    assert tt.fix_mixed_numbers(f"{c}1三個") == f"{c}1三個"            # 前面是單位：是一串更長的數字的後半，不單獨換


@pytest.mark.parametrize("c", list("0123456789零〇一二三四五六七八九十"))
def test_mixed_number_digits_before_join_the_run(c):
    out = tt.fix_mixed_numbers(f"共{c}1三個")
    assert "三" not in out or c == "十"                                 # 前面的數字字一起算進這一串


@pytest.mark.parametrize("c", list("兩"))
def test_mixed_number_not_before_liang(c):
    assert tt.fix_mixed_numbers(f"共1三{c}個") == f"共1三{c}個"


@pytest.mark.parametrize("src,want", [("攤位費二十5萬元", "攤位費250,000元"), ("十0萬", "100,000"), ("1三萬", "130,000"),
                                      ("二十5億", "2,500,000,000"), ("第1三個", "第13個")])
def test_mixed_number_before_scale_unit(src, want):
    # N5：原本「二十5萬」送模型的原文是「二十50,000」
    assert tt.prepare_source(src, "en") == want


def test_spanish_dotted_millions_do_not_crash():
    # N5：float("1.234.567") ValueError → 即時翻譯背景工作整個停掉
    assert tt.numbers_ok("Hay 1.234.567 personas", "There are 1,234,567 people")
    assert tt.numbers_ok("Hay 1.234.567 personas", "There are 1234567 people")
    assert not tt.numbers_ok("Hay 1.234.567 personas", "There are 1,234 people")


@pytest.mark.parametrize("run,want", [("1零", 10), ("1〇", 10), ("一2", 12), ("二3", 23), ("三4", 34), ("四5", 45), ("五6", 56),
                                      ("六7", 67), ("七8", 78), ("八9", 89), ("九0", 90), ("1十", 10), ("十1", 11)])
def test_mixed_number_each_digit_char(run, want):
    assert tt.fix_mixed_numbers(f"共{run}個") == f"共{want}個"
