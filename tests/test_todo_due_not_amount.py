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


@pytest.mark.parametrize("text", ["追加2.5萬元", "預算1.5億", "3.5噸", "3-5人", "12.5%", "版本2.15.3", "13.5", "1.32"])
def test_numbers_not_dates(text):
    assert su._TIME_RE.search(text) is None, su._TIME_RE.search(text)
