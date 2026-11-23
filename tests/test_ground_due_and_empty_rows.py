"""summary_utils.ground_todo_table 的兩個 bug（2026-11-23 localnote@mac，S19 突變測試＋差異搜尋找到）。
1. 期限欄找不到時，用 [、,，/] 拆開只留逐字稿裡有的部分：「3/15」被拆成「3」「15」，逐字稿裡到處有數字，
   期限變成「3、15」或「3」（錯的日期）。「/」是給負責人欄「吳副理/李協理」用的，期限欄不拆「/」。
2. _is_sep 只看字元集合：「|  | - | - |」（事項空、其他欄被清成 -）被當成表格分隔線，
   _drop_empty_item_rows 跳過它；docstring 寫事項欄是空的列要拿掉。改成 _drop_empty_item_rows 用嚴格的 _is_gfm_sep
   （GFM：每一格都至少有一個「-」）；其他 18 個呼叫點照舊用 _is_sep（改全域會讓 clean_summary_markdown／ensure_sections 也變）。
"""
import pytest

import summary_utils as su

H = "## 摘要\n- x\n\n## 決議\n- y\n\n## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n"
TR = "第一個議題是招募。資訊部缺3個職缺，已經面試了15位。請許經理在三月十五日前完成報到。"


def _rows(md):
    return [l for l in md.splitlines() if l.startswith("|")][2:]


@pytest.mark.parametrize("due", ["3/15", "3/15前", "10/7", "3/15-3/20"])
def test_unspoken_slash_date_is_cleared_not_split(due):
    assert _rows(su.ground_todo_table(H + f"| 完成報到 | 許經理 | {due} |\n", TR)) == ["| 完成報到 | 許經理 | - |"]


def test_spoken_slash_date_kept():
    tr = TR + "名單請在3/15前交。"
    assert _rows(su.ground_todo_table(H + "| 交名單 | 許經理 | 3/15前 |\n", tr)) == ["| 交名單 | 許經理 | 3/15前 |"]


def test_owner_column_still_split_on_slash():
    assert _rows(su.ground_todo_table(H + "| 完成報到 | 許經理/李協理 | 三月十五日 |\n", TR)) == ["| 完成報到 | 許經理 | 三月十五日 |"]


def test_due_column_still_split_on_comma():
    tr = TR + "另外週五也要回報。"
    assert _rows(su.ground_todo_table(H + "| 回報 | 許經理 | 三月十五日、四月一日 |\n", tr)) == ["| 回報 | 許經理 | 三月十五日 |"]


def test_empty_item_row_dropped_even_when_owner_is_cleared():
    out = su.ground_todo_table(H + "|  | 王經理 | - |\n| 完成報到 | 許經理 | - |\n", TR)
    assert _rows(out) == ["| 完成報到 | 許經理 | - |"]


def test_only_empty_rows_become_none_row():
    assert _rows(su.ground_todo_table(H + "|  | 王經理 | - |\n|  | - | - |\n", TR)) == ["| 無 | - | - |"]


@pytest.mark.parametrize("line,sep", [
    ("|---|---|---|", True), ("| --- | :---: | ---: |", True), ("|-|-|-|", True), ("| - | - | - |", True),
    ("|  | - | - |", False), ("| | | |", False), ("| 事項 | - | - |", False),
])
def test_gfm_sep_requires_dash_in_every_cell(line, sep):
    assert su._is_gfm_sep(line) is sep
