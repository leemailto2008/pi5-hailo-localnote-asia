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
