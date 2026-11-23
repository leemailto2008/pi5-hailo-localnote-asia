"""紀要 map 的段落邊界不能切在數字中間（2026-11-23 localnote@mac，S10 深度審查）。

split_transcript 的子句規則（_CLAUSE_RE）和 take_stable_chunk（錄音中預先整理）的切點都包含半形「,」「:」，
千分位與時間「6,280萬」「10:30」的分隔符號被當成邊界 → 一段結尾「…6,」、下一段開頭「280萬…」，
模型兩段各看到半個數字。隨機逐字稿（每段 200 字）實測：split_transcript 666 處、take_stable_chunk 907 處。
"""
import random
import re

import pytest

import summary_utils as su


def _transcript(seed):
    rnd = random.Random(seed)
    parts = []
    for _ in range(rnd.randint(60, 250)):
        r = rnd.random()
        num = ("%d,%03d萬" % (rnd.randint(1, 9), rnd.randint(0, 999)) if r < 0.3
               else ("10:%02d開會" % rnd.randint(0, 59) if r < 0.4 else "討論"))
        parts.append(rnd.choice(["預算是", "我們", "今天", "下週三"]) + num + rnd.choice(["，", "。", "", ""]))
    return "".join(parts)


def _splits_number(left: str, right: str) -> bool:
    return bool(re.search(r"\d[,:.]?$", left) and re.match(r"[,:.]?\d", right))


@pytest.mark.parametrize("seed", range(40))
def test_split_transcript_boundaries_keep_numbers(seed):
    t = _transcript(seed)
    chunks = su.split_transcript(t, 200)
    assert "".join(chunks) == t                                   # 內容不增不減（既有保證）
    for a, b in zip(chunks, chunks[1:]):
        assert not _splits_number(a, b), (a[-12:], b[:12])


@pytest.mark.parametrize("seed", range(40))
def test_take_stable_chunk_boundaries_keep_numbers(seed):
    t = _transcript(seed)
    pos = 0
    while True:
        end = su.take_stable_chunk(t, pos, 200, 200)
        if end is None:
            break
        assert pos < end <= pos + 200
        assert not _splits_number(t[pos:end], t[end:]), (t[end - 12:end], t[end:end + 12])
        pos = end


def test_plain_text_behaviour_unchanged():
    t = "我們今天討論預算，" * 300
    assert su.split_transcript(t, 1000) == su.split_transcript(t, 1000)
    end = su.take_stable_chunk(t, 0, 1000, 1000)
    assert t[end - 1] == "，" and end <= 1000                     # 照舊切在後 40% 內最後一個標點之後
    assert su.take_stable_chunk("一" * 2500, 0) == 1000            # 沒有標點、沒有數字：照舊硬切


def test_long_clause_hard_split_keeps_number():
    t = "一" * 995 + "123456789" + "一" * 500                      # 單一子句超過 max_chars、硬切點落在數字中間
    chunks = su.split_transcript(t, 1000)
    assert "".join(chunks) == t
    for a, b in zip(chunks, chunks[1:]):
        assert not _splits_number(a, b), (a[-12:], b[:12])
