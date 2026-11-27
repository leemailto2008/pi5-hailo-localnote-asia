"""P17（2026-11-27 localnote@mac）：紀要翻譯 translate_minutes／english_minutes_lines 的 hypothesis fuzz（假的 _translate_flat）。
性質：段落標題、空行、項目符號原樣保留；行數不變；模型沒翻好的行保留原文（看不懂整串保留）；
「無／none」換成目標語言的「None／無」；英文紀要只換外語條目、其他行一字不改。"""
import asyncio
import os
import tempfile

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

hypothesis.configuration.set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "hyp_p17"))
import transcript_translate as tt  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=1500 if SLOW else 40, deadline=None, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])

HEAD = st.sampled_from(["【摘要】", "【決議】", "【待辦】", "【Summary】", " 【摘要】 "])
BODY = st.sampled_from(["預算 300 萬元", "請吳副理週五前完成", "Q1 target 30%", "無", "none", "-", "Prix du pétrole à 20 dollars",
                        "第三季營收成長百分之十", "", "We ship 1,200 units"])
BUL = st.sampled_from(["• ", "- ", "* ", "", "  • ", "•"])


@st.composite
def minutes(draw):
    lines = []
    for _ in range(draw(st.integers(1, 4))):
        lines.append(draw(HEAD))
        for _ in range(draw(st.integers(0, 4))):
            b = draw(BODY)
            lines.append(draw(BUL) + b if b else "")
    return "\n".join(lines)


@CFG
@given(minutes(), st.sampled_from(["en", "zh"]), st.lists(st.booleans(), max_size=30))
def test_translate_minutes_keeps_structure(monkeypatch, md, target, keep):
    async def fake_flat(units, tgt, on_progress, should_stop, use_cpu, one_chunk=False):
        return {"done": {k: f"T{k}" for k in range(len(units)) if (keep[k] if k < len(keep) else True)}}
    monkeypatch.setattr(tt, "_translate_flat", fake_flat)
    out = asyncio.run(tt.translate_minutes(md, target))["text"]
    src_lines = md.strip().splitlines()
    got = out.splitlines()
    assert len(got) == len(src_lines), (md, out)
    for s, o in zip(src_lines, got):
        if not s.strip() or tt._MIN_HEAD_RE.match(s):
            assert o.strip() == s.strip(), (s, o)
            continue
        m = tt._MIN_BULLET_RE.match(s)
        bullet, body = (m.group(1), m.group(2).strip()) if m else ("", s.strip())
        assert o.startswith(bullet), (s, o)
        rest = o[len(bullet):]
        if body.lower() in tt._EMPTY_ITEM:
            assert rest == ("None" if target == "en" else "無"), (s, o)
        else:
            assert rest.startswith("T") or rest == tt._localize(body, target), (s, o)


@CFG
@given(st.lists(st.tuples(st.sampled_from(["- ", "* ", "", "## "]), BODY), max_size=10), st.lists(st.booleans(), max_size=10))
def test_english_minutes_lines_only_touches_foreign_bullets(monkeypatch, rows, keep):
    md = "\n".join(p + b for p, b in rows)

    async def fake_flat(units, tgt, on_progress, should_stop, use_cpu, one_chunk=False):
        return {"done": {k: f"EN{k}" for k in range(len(units)) if (keep[k] if k < len(keep) else True)}}
    monkeypatch.setattr(tt, "_translate_flat", fake_flat)
    out, n = asyncio.run(tt.english_minutes_lines(md))
    a, b = md.splitlines(), out.splitlines()
    assert len(a) == len(b)
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    assert len(changed) == n
    for i in changed:
        m = tt._MD_BULLET_RE.match(a[i])
        assert m and tt.foreign_minutes_line(m.group(2)) and b[i].startswith(m.group(1)), (a[i], b[i])
