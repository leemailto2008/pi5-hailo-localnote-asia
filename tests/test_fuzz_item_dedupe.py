"""P7（2026-11-27 localnote@mac）：紀要同一行的重複片段去重（collapse_item_loops／_dedupe_segments，08a761c＋5945d2e）的 fuzz。
性質：不生出新字（輸出的每個片段都來自輸入）、不弄丟不同的片段、整理兩次和一次一樣、不生出數字。"""
import os
import re
import tempfile

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings, strategies as st  # noqa: E402

hypothesis.configuration.set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "hyp_p7"))
import summary_utils as su  # noqa: E402

N = 2000 if os.environ.get("PI5_FUZZ_SLOW") else 40
SEG = st.sampled_from(["22% norm", "22% gain", "25% tax", "預算審核", "人力規劃", "Q3 出貨 1,200 台", "John", "待確認",
                       "3.5 億", "norm", "22% Norm", "預算審核。", "第 2 季", "ab"])
SEP = st.sampled_from([", ", "，", "、"])
LEAD = st.sampled_from(["", "- ", "* ", "• ", "  - ", "1. ", "2) ", "**決議**：", "- Owner: ", "- 22:30 "])
TAIL = st.sampled_from(["", "。", ".", " "])


@st.composite
def line(draw):
    segs = draw(st.lists(SEG, min_size=1, max_size=10))
    seps = [draw(SEP) for _ in segs[1:]]
    out = draw(LEAD) + segs[0] + "".join(p + s for p, s in zip(seps, segs[1:])) + draw(TAIL)
    return out


def _key(p):
    return re.sub(r"[\s.。|]+$", "", su._FIRST_SEG_PREFIX_RE.sub("", p)).strip().lower()


def _keys(s):
    return [_key(p) for p in su._ITEM_SEG_RE.split(s)[0::2]]


_NUM = re.compile(r"\d[\d,.]*")


@settings(max_examples=N, derandomize=not os.environ.get("PI5_FUZZ_SLOW"), deadline=None)
@given(line())
def test_dedupe_keeps_every_distinct_segment_and_invents_nothing(s):
    out = su.collapse_item_loops(s)
    ki, ko = _keys(s), _keys(out)
    assert set(ko) <= set(ki), (s, out)               # 不生出新片段
    assert set(ki) == set(ko), (s, out)               # 不同的片段一個都不丟
    assert set(_NUM.findall(out)) <= set(_NUM.findall(s))
    assert su.collapse_item_loops(out) == out, (s, out)
