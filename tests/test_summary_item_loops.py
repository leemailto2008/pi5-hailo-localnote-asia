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
