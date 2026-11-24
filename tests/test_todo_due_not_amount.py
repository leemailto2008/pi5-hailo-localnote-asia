"""待辦表期限不能把小數金額、數量、範圍當成日期（2026-11-23 localnote@mac，S18 fuzz 找到）。
summary_utils._TIME_RE 的 \\d{1,2}[./-]\\d{1,2} 原本會吃到「2.5萬」「1.5億」「3.5噸」「3-5人」：
「| 訂購2.5萬個零件 | 吳副理 | - |」期限被填成「2.5」。hypothesis 最小化（冪等性）：「| 吳副理the 2.5 million | - | - |」。
"""
import pytest

import summary_utils as su

H = "# 會議紀要\n\n## 摘要\n\n## 決議\n\n## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n"


def _due(row, tr=""):
    return su.ground_todo_table(H + row + "\n", tr).splitlines()[-1]


@pytest.mark.parametrize("row,tr", [
    ("| 訂購2.5萬個零件 | 吳副理 | - |", "吳副理負責訂購2.5萬個零件。"),
    ("| 預算追加1.5億 | 李協理 | - |", "李協理負責預算追加1.5億。"),
    ("| 採購3.5噸鋼材 | 吳副理 | - |", "採購3.5噸鋼材由吳副理處理。"),
    ("| 招募3-5人 | 許經理 | - |", "許經理負責招募3-5人。"),
    ("| 良率提升到2.5% | 品保部 | - |", "品保部負責良率提升到2.5%。"),
    ("| 吳副理the 2.5 million | - | - |", "the 2.5 million"),
])
def test_amount_is_not_due(row, tr):
    assert _due(row, tr).endswith("| - |"), _due(row, tr)


@pytest.mark.parametrize("text,due", [
    ("吳副理3/15前寄送報告", "3/15"),
    ("吳副理3.15前寄送報告", "3.15"),
    ("吳副理10-7前回覆", "10-7"),
    ("吳副理在3/15日前寄送", "3/15日"),
    ("10月7日前交初稿", "10月7日"),
    ("週五前交名單", "週五"),
])
def test_real_dates_still_found(text, due):
    m = su._TIME_RE.search(text)
    assert m and m.group(1).replace(" ", "") == due


@pytest.mark.parametrize("text", ["追加2.5萬元", "預算1.5億", "3.5噸", "3-5人", "12.5%", "版本2.15.3", "13.5", "1.32",
                                  "第3.5版", "改成3.5版", "第2/3季"])   # 11-24 localnote：版本號、「第N/M」不是日期
def test_numbers_not_dates(text):
    assert su._TIME_RE.search(text) is None, su._TIME_RE.search(text)


@pytest.mark.parametrize("text", ["V3.5上線", "韌體v3.12要更新", "版本3.12", "版本 3.5 上線"])
def test_version_number_is_not_a_due_date(text):
    # N4 審查 69eca7e：「第3.5版」「3.5版」擋了，前面寫 V／版本的版本號仍被當成 3/5、3/12
    assert [m.group(0) for m in su._TIME_RE.finditer(text)] == []


@pytest.mark.parametrize("text,want", [("3.15前交", ["3.15"]), ("在3/15前", ["3/15"]), ("TV 3/15上市", ["3/15"])])
def test_dates_still_found_near_letters(text, want):
    assert [m.group(0) for m in su._TIME_RE.finditer(text)] == want


@pytest.mark.parametrize("text", ["請吳副理1.5天內完成", "工期2.5年", "每3.5週檢查一次", "會議1.5小時", "休息10-15分鐘", "抽查2.3次", "第3-4季"])
def test_durations_are_not_due_dates(text):
    # N10 fuzz：「1.5天」被讀成 1/5 填進待辦表的期限欄（數量／時長不是日期）
    assert [m.group(0) for m in su._TIME_RE.finditer(text)] == []


def test_pipe_in_transcript_does_not_break_todo_table():
    # N10 fuzz：逐字稿裡的「|」原樣放進待辦表的格子，表格欄位錯開，再處理一次結果又變
    rows = su.transcript_todo_rows("待辦事項是請吳副理10月7日前完成|報告。")
    assert all(r.count("|") == 4 for r in rows), rows



def test_transcript_todo_does_not_glue_separate_numbers():
    # N10 fuzz：事項從逐字稿取時把空白全部拿掉，「0 0」變成憑空的「00」
    for r in su.transcript_todo_rows("教育訓練：請吳副理八月十五日0 0。") + su.transcript_todo_rows("請王經理下週三前準備3 5台樣品。"):
        assert "00" not in r and "35" not in r, r
