"""即時切片串接（summary_utils.live_join_sep）：前段已經以逗號、頓號、分號、冒號結尾時不再補「，」。
2026-11-23 localnote@mac（S10 深度審查）找到：原本只看句末「。！？」，其他標點結尾照補「，」→
「好的,，下一個」「第一點：，預算」「預算是 3,，500 萬」（數字被拆開）。中文的「，，」會被 tidy_live_transcript 合併，
但錄音中預覽看得到；半形「, ; :」與「：，」tidy 不合併，會留在紀要用的全文裡。
"""
import pytest

import summary_utils as su


def _join(segs):
    out = ""
    for s in segs:
        s = su.clean_live_segment(s)
        if s:
            out = out + (su.live_join_sep(out, s) if out else "") + s
    return out


@pytest.mark.parametrize("segs,expect", [
    (["好的，", "下一個議題"], "好的，下一個議題"),
    (["好的,", "下一個議題"], "好的,下一個議題"),
    (["第一點：", "預算"], "第一點：預算"),
    (["第一、", "第二"], "第一、第二"),
    (["預算是 3,", "500 萬"], "預算是 3,500 萬"),
    (["接著；", "下一個"], "接著；下一個"),
])
def test_no_double_separator_after_punctuation(segs, expect):
    assert _join(segs) == expect
    assert su.tidy_live_transcript(_join(segs)) == expect


@pytest.mark.parametrize("prev,cur,sep", [
    ("我們開始今天的週會。", "今天有幾個議題", ""),       # 既有行為不變
    ("我們開始今天的週會", "今天有幾個議題", "，"),
    ("Let's start.", "First topic", " "),
    ("Let's start", "first topic", ", "),
    ("We agreed,", "next topic", " "),                   # 英文：逗號後補空白（既有行為）
    ("OK.", "下一個", " "),
])
def test_existing_behaviour_kept(prev, cur, sep):
    assert su.live_join_sep(prev, cur) == sep


def test_tidy_prefix_property_still_holds():
    segs = ["我們開始今天的週會。", "第一點：", "預算八十萬，", "下週三再確認", "好的,", "結束"]
    full = _join(segs)
    for k in range(1, len(segs)):
        part = _join(segs[:k])
        assert su.tidy_live_transcript(full).startswith(su.tidy_live_transcript(part))
