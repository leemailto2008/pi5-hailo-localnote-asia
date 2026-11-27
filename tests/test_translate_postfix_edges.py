"""N5（2026-11-24 localnote@mac）：transcript_translate.postfix 家族的突變測試補強與邊界。
AST 突變（fix_titles、romanize_titled_names、fix_weekdays、fix_name_zh_titles、fix_cjk_name_titles、fix_common_zh_words
與它們的 regex）：255 個突變原本存活 66 個；這個檔案補的是存活突變指出的空白。"""
import pytest

import transcript_translate as tt

P = lambda src, tr: tt.postfix(src, tr, "en")


@pytest.mark.parametrize("zh,en", [("一", "Monday"), ("二", "Tuesday"), ("三", "Wednesday"), ("四", "Thursday"),
                                   ("五", "Friday"), ("六", "Saturday"), ("日", "Sunday"), ("天", "Sunday")])
def test_each_weekday(zh, en):
    assert tt.fix_weekdays(f"Reply by 週{zh}.", "en") == f"Reply by {en}."
    assert tt.fix_weekdays(f"on 星期{zh}", "en") == f"on {en}"


@pytest.mark.parametrize("tr,want", [("週二3點開會", "Tuesday 3點開會"), ("週二Meeting", "Tuesday Meeting"),
                                     ("週二meeting", "Tuesday meeting"), ("週二, next", "Tuesday, next")])
def test_weekday_spacing(tr, want):
    assert tt.fix_weekdays(tr, "en") == want


@pytest.mark.parametrize("tr,want", [("Captain蔡 will", "Team Lead蔡 will"), ("the Captain.", "the Team Lead."),
                                     ("SeaCaptain", "SeaCaptain"), ("seaCaptain", "seaCaptain"),
                                     ("CaptainX", "CaptainX"), ("Captains", "Captains")])
def test_captain_word_boundaries(tr, want):
    assert tt.fix_titles("負責人是蔡組長", tr, "en") == want


def test_captain_needs_team_lead_in_source():
    assert tt.fix_titles("負責人是蔡先生", "Captain Cai", "en") == "Captain Cai"     # 原文沒有「組長」
    assert tt.fix_titles("蔡組長和林船長", "Captain Cai", "en") == "Captain Cai"     # 原文有船長：Captain 可能是對的


def test_zh_target_untouched():
    for tr in ("Team Lead蔡", "Wang经理", "蔡组长", "全员", "週二"):
        assert tt.postfix("蔡組長王經理", tr, "zh") == tr


@pytest.mark.parametrize("src,tr,want", [
    ("曾組長負責", "Team Lead曾 is in charge", "Team Lead Zeng is in charge"),     # romanize：姓氏讀音
    ("覃經理", "Manager覃", "Manager Qin"),
    ("曾組長負責", "曾组长 is in charge", "Team Lead Zeng is in charge"),          # fix_cjk_name_titles：姓氏讀音
    ("請曾經理處理", "Please ask Ceng经理", "Please ask Manager Zeng"),            # fix_name_zh_titles：原文的姓用姓氏讀音
    ("請曾經理處理", "Please ask Zeng经理", "Please ask Manager Zeng"),
])
def test_surname_readings_in_every_path(src, tr, want):
    assert P(src, tr) == want


@pytest.mark.parametrize("tr,want", [
    ("蔡组长 will do it", "Team Lead Cai will do it"),            # 在開頭：左邊不補空白（不能看 translation[-1]）
    ("Ask 2蔡组长", "Ask 2 Team Lead Cai"),
    ("done by 蔡组长", "done by Team Lead Cai"),                  # 在結尾
    ("done by蔡组长", "done by Team Lead Cai"),
    ("蔡组长X", "Team Lead Cai X"),
    ("大蔡组长", "大蔡组长"),                                      # 前面是中文字：不是單字姓
    ("蔡组长們", "蔡组长們"),                                      # 後面是中文字
])
def test_cjk_name_title_positions(tr, want):
    assert tt.fix_cjk_name_titles("負責人是蔡組長", tr, "en") == want


@pytest.mark.parametrize("tr,want", [
    ("Team Lead蔡 (Cai) said", "Team Lead Cai said"),
    ("Team Lead蔡(Cai) said", "Team Lead Cai said"),              # 括號前沒有空白
    ("Manager焦文軒 (Jiao Wenxuan) said", "Manager Jiao Wenxuan said"),
    ("Team Lead蔡 (cai) said", "Team Lead Cai (cai) said"),       # 小寫不是模型寫的拼音
    ("Team Lead蔡 (CAI) said", "Team Lead CAI said"),
    ("Team Lead蔡文 said", "Team Lead Cai Wen said"),
    ("Team Lead蔡文軒的 said", "Team Lead蔡文軒的 said"),          # 4 個中文字：不是人名
])
def test_romanize_parenthesised_pinyin(tr, want):
    assert tt.romanize_titled_names("負責人是蔡組長，焦文軒經理，蔡文軒的", tr, "en") == want


def test_name_zh_title_needs_real_name():
    assert tt.fix_name_zh_titles("王經理", "W经理", "en") == "W经理"              # 單一個大寫字母不是姓名
    assert tt.fix_name_zh_titles("王經理", "Wang经理", "en") == "Manager Wang"


@pytest.mark.parametrize("tr,want", [("全员培训", "all staff training"), ("全员 培训", "all staff training"),
                                     ("A报价", "A quotation"), ("报价B", "quotation B"), ("3出差", "3 business trip"),
                                     ("出差9", "business trip 9"), ("a培训b", "a training b"), ("(报价)", "(quotation)")])
def test_common_words_spacing(tr, want):
    assert tt.fix_common_zh_words(tr, "en") == want


@pytest.mark.parametrize("tr", ["XCaptain", "xCaptain", "ZCaptain", "zCaptain"])
def test_captain_inside_word_untouched(tr):
    assert tt.fix_titles("蔡組長", tr, "en") == tr


def test_captain_needs_zu_zhang_not_any_zhang():
    assert tt.fix_titles("林課長負責", "Captain Lin", "en") == "Captain Lin"       # 有「長」但不是「組長」


def test_name_zh_title_two_surnames_same_title():
    # 原文有兩位經理：譯文的姓對得上其中一位才換；對不上就不猜
    assert tt.fix_name_zh_titles("王經理和許經理", "Wang经理 agreed", "en") == "Manager Wang agreed"
    assert tt.fix_name_zh_titles("王經理和許經理", "Xiang经理 agreed", "en") == "Xiang经理 agreed"


@pytest.mark.parametrize("tr,want", [("a蔡组长", "a Team Lead Cai"), ("中a蔡组长", "中a Team Lead Cai")])
def test_cjk_name_title_left_space(tr, want):
    assert tt.fix_cjk_name_titles("蔡組長", tr, "en") == want


def test_common_word_then_zero():
    assert tt.fix_common_zh_words("报价0", "en") == "quotation 0"


def test_without_pypinyin_names_are_left(monkeypatch):
    # 沒裝 pypinyin：人名、姓名職稱都不轉，原樣回傳（不能變成 None）
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "pypinyin":
            raise ImportError("no pypinyin")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert tt.romanize_titled_names("蔡組長", "Team Lead蔡", "en") == "Team Lead蔡"
    assert tt.fix_name_zh_titles("王經理", "Wang经理", "en") == "Wang经理"
    assert tt.fix_cjk_name_titles("蔡組長", "蔡组长", "en") == "蔡组长"


@pytest.mark.parametrize("tr,want", [
    ("Manager焦文軒 (Jiao WenXuan) said", "Manager Jiao WenXuan said"),
    ("Manager焦文軒 (Jiao W) said", "Manager Jiao W said"),
    ("Manager焦文軒 (J) said", "Manager J said"),
    ("Manager焦文軒 (Jiao wenxuan) said", "Manager Jiao Wenxuan (Jiao wenxuan) said"),   # 第二個字小寫開頭：不是拼音括號
    ("Manager焦文軒 (Jiao Wen Xuan) said", "Manager Jiao Wenxuan (Jiao Wen Xuan) said"),  # 三個字：不吃
])
def test_romanize_parenthesised_two_words(tr, want):
    assert tt.romanize_titled_names("焦文軒經理", tr, "en") == want


@pytest.mark.parametrize("src,tr,want", [
    ("蔡組長星期五交", "Team Lead蔡星期五 delivers", "Team Lead Cai Friday delivers"),
    ("蔡組長週三", "Team Lead蔡週三", "Team Lead Cai Wednesday"),
])
def test_postfix_weekday_glued_after_titled_name(src, tr, want):
    # P10 fuzz：中文星期緊接在職稱後的中文姓名後面時，romanize_titled_names 比到 4 個中文字不轉，
    # 之後 fix_weekdays 才把星期換掉——姓名留著中文，要再做一次 postfix 才轉拼音
    import transcript_translate as tt
    out = tt.postfix(src, tr, "en")
    assert out == want
    assert tt.postfix(src, out, "en") == out


@pytest.mark.parametrize("src,tr,want", [
    ("王經理新竹", "in 新竹Wang经理", "in Hsinchu Manager Wang"),
    ("和林主任", "和Lin主任 meet", None),
    ("王經理", "XWang经理", "XWang经理"),               # 前面是英文字母：不是姓名開頭，不動
])
def test_postfix_name_title_after_cjk(src, tr, want):
    # P11 fuzz：姓名前面緊接中文字（「新竹Wang经理」）時 \b 不成立，第一次不換、fix_place_names 補空白後第二次才換
    import transcript_translate as tt
    out = tt.postfix(src, tr, "en")
    if want is not None:
        assert out == want
    else:
        assert "Director Lin" in out
    assert tt.postfix(src, out, "en") == out


def test_postfix_titled_cjk_name_after_cjk():
    # P11 fuzz：「新竹Director林」職稱前面緊接中文字時 \b 不成立，第一次不轉拼音
    import transcript_translate as tt
    out = tt.postfix("林主任新竹", "in 新竹Director林", "en")
    assert out == "in Hsinchu Director Lin" and tt.postfix("林主任新竹", out, "en") == out


def test_collapse_repeats_reaches_fixpoint():
    # P11 fuzz：收一次之後又形成新的 4 次重複（「OK OKOK OKOK OKOK OK」），要一次收到底
    import transcript_translate as tt
    s = "OK OK OK OK OK" * 4
    out = tt.collapse_repeats(s)
    assert tt.collapse_repeats(out) == out and out.count("OK") <= 2


@pytest.mark.parametrize("src,tr,want", [
    ("劉課長", "全员培训劉課長", "all staff training Section Chief Liu"),
    ("蔡組長", "Team Lead蔡 Team Lead蔡 Team Lead蔡 Team Lead Cai Team Lead蔡", "Team Lead Cai Team Lead Cai"),  # 最後一份沒有空白，不算同一單位
])
def test_postfix_order_interactions_stable_in_one_pass(src, tr, want):
    # P11 fuzz：常見商用詞緊接在姓名前面、姓名轉拼音後才變成重複迴圈——原本都要做兩次 postfix 才穩定
    import transcript_translate as tt
    out = tt.postfix(src, tr, "en")
    assert out.strip() == want.strip()
    assert tt.postfix(src, out, "en") == out


@pytest.mark.parametrize("prefix", ["X", "x", "3", "_", "Z", "a", "0", "9"])
def test_titled_name_needs_word_start(prefix):
    # P12 突變補強：職稱／姓名前面緊接英文字母、數字、底線時不是開頭，不轉（「XManager蔡」「3Wang经理」不動）
    import transcript_translate as tt
    assert tt.romanize_titled_names("蔡組長", f"{prefix}Manager蔡", "en") == f"{prefix}Manager蔡"
    assert tt.fix_name_zh_titles("王經理", f"{prefix}Wang经理", "en") == f"{prefix}Wang经理"


@pytest.mark.parametrize("src,tr,want", [
    ("Q1 target", "第一季目標", "第1季目標"),
    ("Q4 revenue up 10%", "第四季營收成長百分之十", "第4季營收成長10%"),
    ("Taipei 101", "台北一零一", "台北101"),
    ("room 302", "三零二室", "302室"),
    ("10 rounds, together", "十輪，一起", "10輪，一起"),          # 一般用詞不動
    ("Q1 target", "第一季目標，萬一", "第1季目標，萬一"),
])
def test_fix_numerals_quarter_and_digit_by_digit(src, tr, want):
    # P13：「Q1」翻成「第一季」、「101」「302」逐字念成「一零一」「三零二」時數值對不上，整行被當成數值錯誤
    import transcript_translate as tt
    assert tt.fix_numerals(src, tr, "zh") == want


@pytest.mark.parametrize("tr", ["零件一一確認", "零星的一些", "歸零一下"])
def test_fix_numerals_digit_run_keeps_plain_words(tr):
    import transcript_translate as tt
    assert tt.cn_numerals_to_digits(tr) == tr


@pytest.mark.parametrize("src,tr,want", [
    ("10 suppliers of parts", "十家零件供應商", "10家零件供應商"),
    ("10 rounds, zero defects in 3 days", "十輪，三天零件不良", "10輪，3天零件不良"),
])
def test_fix_numerals_lone_zero_is_a_word(src, tr, want):
    # P13：「零件」的「零」後面接量詞「件」，原本被換成 0（「10家0件供應商」：生出原文沒有的數字 0）。單獨一個「零／〇」不換
    import transcript_translate as tt
    assert tt.fix_numerals(src, tr, "zh") == want


@pytest.mark.parametrize("tr,want", [("台北一零一零件", "台北101零件"), ("三零二零星", "302零星"), ("台北一零一", "台北101"),
                                     ("編號三零零", "編號300"), ("三零二室", "302室")])
def test_digit_run_leaves_trailing_zero_word(tr, want):
    # P18 fuzz：逐字念的號碼後面緊接「零件」「零星」時，最後那個零是下一個詞的（原本「台北1010件」生出 1010）
    import transcript_translate as tt
    assert tt.cn_numerals_to_digits(tr) == want


@pytest.mark.parametrize("tr,want", [("歸零三零二室", "歸零302室"), ("歸零三人", "歸零3人"), ("零三零二室", "0302室")])
def test_digit_run_leading_zero_word(tr, want):
    # P18 fuzz：「歸零」的零接著號碼時不是號碼的一部分（原本「歸0302室」）
    import transcript_translate as tt
    assert tt.cn_numerals_to_digits(tr) == want
