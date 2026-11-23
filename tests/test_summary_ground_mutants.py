"""summary_utils 待辦 grounding／期限規則的突變測試補強（2026-11-23 localnote@mac，S19）。
S19 對 ground_todo_table 與輔助函式、_todo_parts、_strip_time 做 490 個突變，原本的 test_summary_utils.py 殺掉 383 個、存活 107 個。
這裡的案例是突變導向差異搜尋（用 e2e 測資組出的紀要與逐字稿）找到、而且人工確認過原版輸出正確的。
"""
import json
import os

import summary_utils as su

ROOT = os.path.join(os.path.dirname(__file__), "..")
H = "## 摘要\n- x\n\n## 決議\n- y\n\n## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n"


def _rows(md):
    return [l for l in md.splitlines() if l.startswith("|")][2:]


def _en_transcript():
    with open(os.path.join(ROOT, "tools", "e2e", "fixtures", "meeting_en_long.json"), encoding="utf-8") as f:
        return " ".join(t for _, t in json.load(f)["lines"])


ZH_TR = ("上週地下停車場發生一起小事故，沒有人受傷。已經加裝八支警示燈，並在三月二十六日前完成全員複訓。負責人是許經理。"
         "第一個議題是供應商。新光材料的電源晶片交期延到十月十日，比原本晚了七天。請李協理跟對方確認，週五回報。")


# ------------------------------------------------------------------ _fill_todo_cells：中文事項欄裡的期限、負責人
def test_due_taken_from_chinese_item_and_grounded():
    out = _rows(su.ground_todo_table(H + "| 已經加裝八支警示燈，並在三月二十六日前完成全 | 劉課長 |  |\n", ZH_TR))
    assert out == ["| 已經加裝八支警示燈，並在三月二十六日前完成全 | - | 三月二十六日 |"]   # 劉課長沒講過 → -


def test_english_item_kept_when_owner_cell_not_empty():
    tr = "Please arrange the testing. Kevin will confirm."
    out = _rows(su.ground_todo_table(H + "| Confirm firmware testing by Kevin | 李協理 | - |\n", tr))
    assert out == ["| Confirm firmware testing by Kevin | - | - |"]                           # 事項不被拆、李協理沒講過


def test_owner_stub_completed_and_ownerless_duplicate_dropped():
    md = H + "| 確認交期 | 理協 | 10月7 |\n| 確認交期 | - | 10月7 |\n"
    assert _rows(su.ground_todo_table(md, ZH_TR)) == ["| 確認交期 | 李協理 | - |"]              # 理協 → 李協理；10月7 沒講過


# ------------------------------------------------------------------ _drop_empty_item_rows：標籤列、整張表拿光
def test_label_only_row_without_due_becomes_none_table():
    assert _rows(su.ground_todo_table(H + "| 決議 | 3位 | 2月23 |\n", ZH_TR)) == ["| 無 | - | - |"]


def test_label_row_with_owner_and_due_kept_once():
    tr = _en_transcript()
    md = H + "| 招募方面 | Mary | March 15 |\n| 招募方面 | - | March 15 |\n"
    assert _rows(su.ground_todo_table(md, tr)) == ["| 招募方面 | Mary | March 15 |"]


def test_trailing_empty_due_cell_kept():
    out = _rows(su.ground_todo_table(H + "| 確認交期 | 李協理 |  |\n", ZH_TR))
    assert out == ["| 確認交期 | 李協理 |  |"]                                                 # 3 格，不會被砍成 2 格


# ------------------------------------------------------------------ 英文：負責人、期限不能被「對齊」成星期或月份
def test_english_owners_never_become_weekday_or_month():
    tr = _en_transcript()
    md = H + ("| The third topic is the firm | Mary | July 1 |\n| Kevin wil | Grace | - |\n"
              "| We have installed eigh | Linda | 10月7日 |\n| The third topic is the firm | - | July 1 |\n"
              "| The th | Tom | by Friday |\n| The  | John and Mary |  |\n")
    rows = _rows(su.ground_todo_table(md, tr))
    owners = {r.strip("|").split("|")[1].strip() for r in rows}
    assert not owners & {"March", "Thursday", "Friday", "Wednesday", "July", "We"}, rows
    assert "| The third topic is the firm | Mary | July 1 |" in rows                          # Mary、July 1 講稿裡都有
    assert "| We have installed eigh | Linda | - |" in rows                                    # 10月7日 沒講過
    assert "| The th | Tom | - |" in rows                                                     # 「by Friday」這個寫法沒講過


def test_english_duplicate_without_owner_dropped():
    tr = "We will hold three more interviews next week, led by Linda, and we hope new hires start by October 12th."
    md = H + "| We will hold three more | Linda | by Friday |\n| We will hold three more | - | by Friday |\n"
    assert _rows(su.ground_todo_table(md, tr)) == ["| We will hold three more | Linda | - |"]


def test_english_rows_with_mixed_cells_do_not_crash():
    """差異搜尋裡 3 個突變在這裡丟 IndexError（_fill_en_due_from_transcript）；原版要能處理中英混雜的列。"""
    tr = _en_transcript()
    md = H + ("| 招募方面 | 待確認 | 3/15 |\n| 22 people have | 王經理 | 週五前 |\n| The first topic is trai |  | March 15 |\n"
              "| There | David | 11月5日前 |\n|  | John and Mary |  |\n| Firmware: we decided | Mary | 週五前 |\n")
    rows = _rows(su.ground_todo_table(md, tr))
    assert rows == ["| 22 people have | - | - |", "| The first topic is trai |  | March 15 |", "| There | David | - |",
                    "| Firmware: we decided | Mary | - |"]          # 標籤列與空事項列拿掉；只有 March 15 講稿裡有


def test_unspoken_due_and_owner_cleared():
    md = H + "| 招募方面 | 6位 | 7月1 |\n| 確認預算表 | 蔡組長 | 3/15 |\n"
    assert _rows(su.ground_todo_table(md, ZH_TR)) == ["| 確認預算表 | - | - |"]                 # 標籤列拿掉；蔡組長、3/15 沒講過


# ------------------------------------------------------------------ _todo_parts：「待辦事項是…」（e2e 測資的結尾總結句）
def test_todo_mark_with_owner_lead():
    rows = su.extract_todos(["待辦事項是負責人是許經理，已經加裝八支警示燈，並在十二月二十六日前完成全員複訓。",
                             "待辦事項是負責人是劉課長，希望在五月二十六日前完成報到。"])
    cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
    assert [(c[1], c[2]) for c in cells] == [("許經理", "十二月二十六日"), ("劉課長", "五月二十六日")]
    assert not any(c[0].startswith(("人是", "是", "負責")) for c in cells), rows        # 「負責人是」整段拿掉


def test_todo_mark_with_please_and_weekday():
    assert su.extract_todos(["待辦事項是請李協理跟對方確認，週四回報。"]) == ["| 跟對方確認 | 李協理 | 週四 |"]


def test_recipient_is_owner_by_e2e_definition():
    """「請各部門…把名單交給黃專員」：e2e 測資的 facts 把黃專員記成「T9訓練-負責人」，負責人取黃專員是刻意的。"""
    assert su.extract_todos(["請各部門在週四前把名單交給黃專員。"])[0].split("|")[2].strip() == "黃專員"
