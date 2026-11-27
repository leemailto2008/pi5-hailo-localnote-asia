"""P2（2026-11-27 localnote@mac）：ASR 後處理整理兩次要和一次一樣（test_fuzz_e2e_asr 找到的，寫成一般回歸測試，CI 沒裝 hypothesis 也會跑）。
流程照 meeting_minutes（只讀）：clean_live_segment → live_join_sep → tidy_live_transcript → fix_meeting_terms。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # hailo_whisper 在 repo 根目錄
import summary_utils as su  # noqa: E402
from hailo_whisper.engine import fix_meeting_terms  # noqa: E402


def asr_transcript(segs):
    out, prev = "", None
    for s in segs:
        c = su.clean_live_segment(s)
        if not c:
            continue
        out = c if prev is None else out + su.live_join_sep(prev, c) + c
        prev = c
    return fix_meeting_terms(su.tidy_live_transcript(out))


@pytest.mark.parametrize("segs", [["好的the budget、"], ["請the 吳副理，"], ["預算 the 3 萬。"], ["好的", "the budget so", "好的"]],
                         ids=["dunhao", "comma", "period", "double-space"])
def test_latin_noise_removal_leaves_no_space_before_cjk_punct(segs):
    # P2 fuzz：拿掉英文碎片（the）後補的空白留在「、」前面、或變成兩個空白，要等下一次 tidy 才收掉 → 整理兩次結果不一樣
    tr = asr_transcript(segs)
    assert fix_meeting_terms(su.tidy_live_transcript(tr)) == tr, tr


@pytest.mark.parametrize("seg,want", [("我們我們我們要開會", "我們要開會"), ("目前目前目前存1200臺", "目前存1200臺"), ("然後 然後 然後", "然後")])
def test_stutter_collapsed_in_one_pass(seg, want):
    # P2 fuzz：「(目前|已經|我們|然後)\s*\1」一次只收一對，三次重複要整理兩次才收乾淨
    assert fix_meeting_terms(seg) == want


@pytest.mark.parametrize("p", list("，、。"))
def test_no_space_next_to_each_cjk_punct(p):
    # P3：英文碎片會出現在中文字或「，。、」旁邊；拿掉之後這三個標點前後都不留補的空白
    for seg in (f"好的the budget{p}好的", f"好的{p}the budget好的"):
        tr = asr_transcript([seg])
        assert f" {p}" not in tr and f"{p} " not in tr, tr
        assert fix_meeting_terms(su.tidy_live_transcript(tr)) == tr


def test_latin_fragment_exact_output():
    from hailo_whisper.engine import _fix_latin_in_cjk
    assert _fix_latin_in_cjk("好的the budget好") == "好的 budget 好"
    assert _fix_latin_in_cjk("有two 個職缺") == "有二個職缺"              # 英文數字字換成國字，前後不補空白
    assert _fix_latin_in_cjk("請the 吳副理 er 處理") == "請 吳副理 處理" or "the" not in _fix_latin_in_cjk("請the 吳副理 er 處理")


def test_latin_fragment_single_spaces():
    from hailo_whisper.engine import _fix_latin_in_cjk
    assert _fix_latin_in_cjk("好的the budget so好的") == "好的 budget so 好的"
