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


def test_due_without_date_after_stripping_qian_is_not_grounded():
    """11-20 L_final45 5 分實錄：模型把「週五前」寫成「週前」；去掉「前」只剩「週」，逐字稿到處都有，不能算講過。"""
    import summary_utils as su
    md = "## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n| 韌體測試 | 許經理 | 週前 |\n"
    out = su.ground_todo_table(md, "許經理說韌體測試要在這週五前完成。")
    assert "週前" not in out


@pytest.mark.parametrize("cell,tr", [("下週前", "請大家在下週之前交"), ("年底前", "年底之前要完成"), ("本週前", "本週之前回覆"),
                                     ("明天前", "明天之前給我"), ("下個月前", "下個月之前上線"), ("週末前", "週末之前寄出")])
def test_relative_due_before_is_grounded(cell, tr):
    # N4 審查 ed1e372：「去掉前後要還有日期」只認數字／月日號／週幾，相對期限被當成沒講過
    assert su._grounded(cell, su._ground_norm(tr), due=True)


def test_bare_week_still_not_grounded():
    assert not su._grounded("週前", su._ground_norm("週五之前交"), due=True)
    # 「今天」會議裡到處都有 (「今天的週會」)：「今天前」不靠去掉「前」來對
    assert not su._grounded("今天前", su._ground_norm("今天的週會有三個議題"), due=True)
