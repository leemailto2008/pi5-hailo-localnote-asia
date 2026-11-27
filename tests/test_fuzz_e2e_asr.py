"""P2（2026-11-27 localnote@mac）：ASR 後處理 → 即時翻譯／紀要 的端到端 hypothesis fuzz。
流程照 meeting_minutes（只讀）：即時切片 clean_live_segment → live_join_sep 接起來 → tidy_live_transcript → fix_meeting_terms
＝紀要用的全文；即時翻譯每段 fix_meeting_terms(clean_live_segment(段)) → prepare_source。
原則：看不懂整串保留，不准憑空生出數字。
- 快速模式：每個性質 40 例、deadline 800 ms、derandomize、不寫 .hypothesis/。PI5_FUZZ_SLOW=1：2,000 例、不設 deadline。
- 沒裝 hypothesis 時整檔 skip。
"""
import os
import re
import sys
import tempfile
from decimal import Decimal

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, assume, given, settings, strategies as st  # noqa: E402
from hypothesis.configuration import set_hypothesis_home_dir  # noqa: E402

set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "pi5_localnote_hypothesis"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # hailo_whisper 在 repo 根目錄

import summary_utils as su  # noqa: E402
import transcript_translate as tt  # noqa: E402
from hailo_whisper.engine import fix_meeting_terms  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=2000 if SLOW else 40, deadline=None if SLOW else 800, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large])

_FULL = str.maketrans("０１２３４５６７８９", "0123456789")


def asr_transcript(segs):
    """meeting_minutes 的即時稿 → 紀要用全文。"""
    out = ""
    prev = None
    for s in segs:
        c = su.clean_live_segment(s)
        if not c:
            continue
        out = c if prev is None else out + su.live_join_sep(prev, c) + c
        prev = c
    return fix_meeting_terms(su.tidy_live_transcript(out))


def _vals(s):
    """阿拉伯數字（含全形、千分位、小數）讀出的數值集合。"""
    s = (s or "").translate(_FULL)
    return {Decimal(m.replace(",", "")) for m in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", s)}


def _ints_from_pieces(s):
    """原文裡每一串數字的各種讀法：整數、小數、去掉千分位、拆開的每一段（「3 月 15 日」→ 3、15）。"""
    s = (s or "").translate(_FULL)
    out = set()
    for m in re.findall(r"[\d.,]+", s):
        for piece in re.split(r"[.,]", m) + [m.replace(",", "")]:
            if re.fullmatch(r"\d+(?:\.\d+)?", piece or ""):
                out.add(Decimal(piece))
    return out


NAMES = ["吳副理", "許經理", "李協理", "蔡組長", "王經理"]
WORDS = ["好的", "我們", "下一個議題", "決議", "待辦事項是", "請", "預算", "訂單", "報名", "樣品", "完成", "上線", "會議", "嗯", "那個"]
EN = ["okay", "the budget", "next week", "thank you", "so", "I think"]
_D = "零一二三四五六七八九"


def cn(n):
    if n == 0:
        return "零"
    out, zero = "", False
    for unit, v in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
        d = n // v % 10
        if d:
            out += ("零" if zero else "") + ("" if unit == "十" and d == 1 and n < 20 and not out else _D[d]) + unit
            zero = False
        elif out:
            zero = True
    return out


@st.composite
def number_token(draw):
    """(寫法, 真值或 None)。日期回 None（月份不算數值）。"""
    kind = draw(st.sampled_from(["digits", "comma", "full", "cn", "wan", "dec", "date", "dashdate", "dotdate", "spaced", "pct"]))
    n = draw(st.integers(1, 99999))
    if kind == "digits":
        return str(n), n
    if kind == "comma":
        return f"{n:,}", n
    if kind == "full":
        return str(n).translate(str.maketrans("0123456789", "０１２３４５６７８９")), n
    if kind == "cn":
        return cn(n % 10000 or 1), None                       # 國字：prepare 不換，數值檢查也不讀
    if kind == "wan":
        k = draw(st.integers(1, 999))
        return f"{k}萬", k * 10 ** 4
    if kind == "dec":
        return f"{n % 100}.{draw(st.integers(1, 9))}", None
    if kind == "pct":
        return f"{n % 100}%", n % 100
    m, d = draw(st.integers(1, 12)), draw(st.integers(1, 28))
    return {"date": f"{m}月{d}日", "dashdate": f"{m}-{d}日", "dotdate": f"{m}.{d}日", "spaced": f"{m} 月 {d} 日"}[kind], None


@st.composite
def segment(draw):
    parts = []
    for _ in range(draw(st.integers(1, 4))):
        parts.append(draw(st.sampled_from(WORDS + NAMES + EN)))
        if draw(st.booleans()):
            parts.append(draw(number_token())[0] + draw(st.sampled_from(["", "人", "台", "元", "個", "天", "前"])))
    sep = draw(st.sampled_from(["", " ", "，"]))
    junk = draw(st.text(alphabet="，。、!?…~ -嗯呃的了", max_size=4))
    return sep.join(parts) + junk


@CFG
@given(st.lists(segment(), min_size=1, max_size=8))
def test_asr_transcript_never_invents_numbers(segs):
    tr = asr_transcript(segs)
    extra = _vals(tr) - set().union(*(_ints_from_pieces(s) for s in segs))
    assert not extra, (segs, tr, extra)


@CFG
@given(st.lists(segment(), min_size=1, max_size=8))
def test_asr_transcript_stable(segs):
    tr = asr_transcript(segs)
    assert fix_meeting_terms(su.tidy_live_transcript(tr)) == tr, (segs, tr)


@CFG
@given(st.sampled_from(WORDS + NAMES), number_token(), st.sampled_from(["", "人", "台", "元", "個"]), st.sampled_from(WORDS + [""]))
def test_live_translate_source_kept_or_exact(pre, tok, unit, post):
    text, val = tok
    assume(val is not None)
    seg = fix_meeting_terms(su.clean_live_segment(pre + text + unit + post))
    p = tt.prepare_source(seg, "en")
    vals = tt.number_values(p)
    if p != seg:
        assert vals == [float(val)], (pre + text + unit + post, seg, p, vals)
    else:
        assert not vals or set(vals) <= {float(v) for v in _ints_from_pieces(seg)} | {float(val)}, (seg, vals)


GARBAGE = st.text(alphabet="0123456789０１２３一二三十百千萬月日號前.-,，。 abcXYZ的了是嗯待辦決議負責", max_size=60)


@CFG
@given(st.lists(GARBAGE, max_size=6))
def test_pipeline_never_crashes(segs):
    tr = asr_transcript(segs)
    for s in segs:
        tt.prepare_source(fix_meeting_terms(su.clean_live_segment(s)), "en")
    su.transcript_todo_rows(tr)
    su.ground_todo_table(su.ensure_sections(""), tr)


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
