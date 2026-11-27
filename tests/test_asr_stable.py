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
