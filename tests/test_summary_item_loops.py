"""11-26 馬來文 6 分紀要：條列裡「30 years, 30 years, …」重複 7 次（generation_loop_start 要 10 次才停）。
clean_summary_markdown 把條列／表格列裡連續 4 次以上的重複收成一次；正常重複與數字、空表格列不動。"""
import pytest

import summary_utils as su


def test_item_loop_collapsed():
    md = "## 摘要\n- **Decision made**: 2024-2025, 30-35 years, 27th, " + "30 years, " * 7 + "30 years\n"
    out = su.clean_summary_markdown(md)
    assert "- **Decision made**: 2024-2025, 30-35 years, 27th, 30 years" in out and out.count("30 years") == 1


@pytest.mark.parametrize("s", ["- 對對對，好", "- 預算 1,000,000,000,000 元", "- Hà, Hà và Lan", "| 事項 | 王經理 | 11月28日 |"])
def test_normal_lines_kept(s):
    assert su.collapse_item_loops(s) == s


def test_row_loop_collapsed():
    assert su.collapse_item_loops("| 準備報告準備報告準備報告準備報告 | 王 | - |") == "| 準備報告 | 王 | - |"


def test_alternating_segments_deduped():
    """11-27 法文紀要：兩個片段交替重複。"""
    s = "- **Agreed**: 250–300 million in July, 22% gain, 25% tax, 22% norm, 22% gain, 22% norm, 22% gain, 22% norm, 22% norm"
    assert su.collapse_item_loops(s) == "- **Agreed**: 250–300 million in July, 22% gain, 25% tax, 22% norm"


@pytest.mark.parametrize("s", ["- 王經理負責教育訓練，李經理負責教育訓練", "- 出貨 1,000,000 台、1,000 台、1,000 台",
                               "- 同意，同意，下週再議", "| 事項 | 王經理 | 11月28日 |"])
def test_segment_normal_lines_kept(s):
    assert su.collapse_item_loops(s) == s


def test_table_row_cells_not_merged():
    # P1 審查 b652886：表格列整列套 collapse_item_loops，4 格內容相同的列被收成一格（「| 待確認 |」），欄位消失
    import summary_utils as su
    md = ("## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n| 待確認 | 待確認 | 待確認 | 待確認 |\n"
          "| 送樣品 | 吳副理 | 好好好好好好好好 |")
    out = su.clean_summary_markdown(md)
    rows = [l for l in out.splitlines() if l.startswith("|") and "---" not in l]
    assert all(r.count("|") >= 4 for r in rows), rows
    assert "| 送樣品 | 吳副理 | 好好 |" in out                       # 格子裡的迴圈照舊收掉


@pytest.mark.parametrize("line,want", [
    ("- 22% norm, 22% gain, 22% norm, 22% norm, 22% norm", "- 22% norm, 22% gain"),
    ("- 22% norm, 22% gain, 22% norm, 22% norm", "- 22% norm, 22% gain"),
    ("* 預算審核，人力規劃，預算審核，預算審核", "* 預算審核，人力規劃"),
])
def test_dedupe_segments_counts_first_bullet_segment(line, want):
    # P5 審查 08a761c：整行含條列符號「- 」，第一段的 key 帶著「- 」比不到後面的同一段：3 次只算 2 次、4 次留兩份
    import summary_utils as su
    assert su.collapse_item_loops(line) == want


@pytest.mark.parametrize("line,want", [
    ("1. 預算審核，人力規劃，預算審核，預算審核", "1. 預算審核，人力規劃"),
    ("2) 22% norm, 22% gain, 22% norm, 22% norm", "2) 22% norm, 22% gain"),
    ("**決議**：預算審核、人力規劃、預算審核、預算審核", "**決議**：預算審核、人力規劃"),
    ("- 負責人：John Smith, Mary Lee, John Smith, John Smith", "- 負責人：John Smith, Mary Lee"),
    ("- Owner: John Smith, Mary Lee, John Smith, John Smith", "- Owner: John Smith, Mary Lee"),
    ("- 預算審核，人力規劃，預算審核，預算審核。", "- 預算審核，人力規劃。"),
    ("- 22% norm, 22% gain, 22% norm, 22% norm.", "- 22% norm, 22% gain."),
    ("- 會議 22:30 開始, 22% gain, 22% gain", "- 會議 22:30 開始, 22% gain, 22% gain"),   # 只出現 2 次不收；時間的冒號不算標籤
])
def test_dedupe_segments_first_segment_prefix_and_terminator(line, want):
    # P7：第一段前面的編號（1. 2)）、標籤（決議：、Owner: ）不算進比對；被收掉的最後一段帶著的句號要留給整行
    import summary_utils as su
    assert su.collapse_item_loops(line) == want


def test_dedupe_segments_bullet_dot_and_short_keys():
    import summary_utils as su
    assert su.collapse_item_loops("• 預算審核，人力規劃，預算審核，預算審核") == "• 預算審核，人力規劃"
    assert su.collapse_item_loops("- tax, fee, tax, tax") == "- tax, fee, tax, tax"        # 不到 4 個字不收
