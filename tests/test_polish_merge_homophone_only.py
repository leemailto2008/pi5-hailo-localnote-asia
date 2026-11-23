"""transcript_polish.edit_opcodes：只合併同音替換（2026-11-23 localnote@mac，S19 突變測試找到）。"""
import transcript_polish as tp

# 原本「補字＋相同 1 字＋刪字」（位移）兩邊等長也會併成替換：補對的字整塊被當成「不是同音」拒收，網頁也畫出假的替換。
# docstring 的標題是「字數相同的連續同音字替換」：合併後每一處不同的字都要是同音中文字才合併。
def test_shift_is_not_merged_and_missed_char_is_kept():
    assert tp.accept_homophone_edits("替料就", "替代料")[0] == "替代料就"       # 補「代」收、刪「就」不收（原本整塊不收）


def test_shift_is_shown_as_delete_and_insert():
    tags = [op[0] for op in tp.edit_opcodes("說了話", "說話人") if op[0] != "equal"]
    assert tags == ["delete", "insert"]                                         # 原本是假的 replace「了話→話人」
    assert tp.accept_homophone_edits("說了話", "說話人")[1] == {"accepted": 0, "rejected": 2}


def test_homophone_run_still_merged():
    ops = [op for op in tp.edit_opcodes("清理協禮", "請李協理") if op[0] != "equal"]
    assert [op[0] for op in ops] == ["replace", "replace"]


# 突變導向差異搜尋（S19，修正後再跑一次）找到、合併邏輯要對的同音錯位：e2e 測資的句子
def test_misaligned_homophone_runs_from_e2e():
    cases = [
        ("同意，這件事由力謝李負責，週四前回客戶有。", "同意，這件事由李協理負責，週四前回覆客戶。", "同意，這件事由李協理負責，週四前回覆客戶有。"),
        ("說話人1：上先前線在已百台設備上試跑三天，沒有問替再全面更新", "說話人1：上線前先在一百台設備上試跑三天，沒有問題再全面更新。",
         "說話人1：上線前先在一百台設備上試跑三天，沒有問題再全面更新"),
        ("責人是長供程。", "負責人是張工程師。", "責人是張工程師。"),     # 行首補字不收、行中間補「師」收
    ]
    for src, dst, want in cases:
        assert tp.accept_homophone_edits(src, dst, tp.protected_spans(src))[0] == want
