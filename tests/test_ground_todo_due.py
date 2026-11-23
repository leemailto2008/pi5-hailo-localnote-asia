"""待辦表期限的 grounding：「前／之前／以前」是同一個意思（2026-11-23 localnote@mac，S11 深度審查）。

ground_todo_table 要求負責人、期限在逐字稿裡出現（擋模型編的欄位），比對是「標準化後的子字串」。
模型常把逐字稿的「10月7日之前」「下週五以前」寫成「10月7日前」「下週五前」：子字串對不上 → 期限被改成「-」，
有講過的日期從紀要消失。期限欄比對時先去掉結尾的「前／之前／以前」，表格顯示的文字不變。
"""
import pytest

import summary_utils as su

MD = ("## 摘要\n- 預算確認\n\n## 待辦\n| 事項 | 負責人 | 時間 |\n|---|---|---|\n"
      "| 送預算表 | 劉課長 | 10月7日前 |\n| 回報交期 | 李協理 | 下週五前 |\n| 提出改善報告 | 黃專員 | 11月5日 |\n\n## 決議\n- 無")


def _rows(md):
    return [l for l in md.splitlines() if l.startswith("| ") and "事項" not in l]


@pytest.mark.parametrize("before", ["之前", "以前", "前"])
def test_due_with_before_suffix_is_grounded(before):
    tr = f"劉課長要在10月7日{before}送預算表，李協理下週五{before}回報交期，黃專員11月5日提出改善報告。"
    rows = _rows(su.ground_todo_table(MD, tr))
    assert rows == ["| 送預算表 | 劉課長 | 10月7日前 |", "| 回報交期 | 李協理 | 下週五前 |",
                    "| 提出改善報告 | 黃專員 | 11月5日 |"]


def test_unspoken_due_is_still_removed():
    tr = "劉課長要送預算表，李協理回報交期，黃專員11月5日提出改善報告。"   # 10月7日、下週五都沒講
    rows = _rows(su.ground_todo_table(MD, tr))
    assert rows[0] == "| 送預算表 | 劉課長 | - |" and rows[1] == "| 回報交期 | 李協理 | - |"


def test_owner_grounding_unchanged():
    tr = "王經理要在10月7日之前送預算表，李協理下週五前回報交期，黃專員11月5日提出改善報告。"
    rows = _rows(su.ground_todo_table(MD, tr))
    assert rows[0] == "| 送預算表 | - | 10月7日前 |"       # 劉課長沒講過：負責人照舊拿掉
