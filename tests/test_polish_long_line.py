"""潤稿：一位說話人連續講超過 MAX_CHUNK_CHARS（600 字）的一行（2026-11-23 localnote@mac，S9 深度審查）。

split_chunks 把超長的行切成幾塊分別送模型；原本結果用 "\\n\\n" 接回去 → 同一句話在中間斷成兩段，後半段沒有
「說話人N：」標籤（網頁顯示像另一個人、逐字稿翻譯 parse_lines 也當成沒有說話人）。
同一行切開的塊要原樣接回（不加分段），一般的塊照舊空一行。不呼叫 LLM（MacBERT 引擎換成照抄的假引擎）。
"""
import asyncio

import pytest

import csc_corrector as cc
import transcript_polish as tp

pytest.importorskip("pypinyin")


class _Echo:
    label = "echo"

    def __init__(self, *a, **k):
        pass

    def correct(self, text, should_stop=None):
        return text


@pytest.fixture
def echo_engine(monkeypatch):
    monkeypatch.setattr(cc, "CscCorrector", _Echo)
    monkeypatch.setattr(tp, "PRE_CSC", False)


def _long_line(n_sentences):
    return "說話人1：" + "".join(f"這是第{i}句話，我們要討論預算和時程。" for i in range(n_sentences))


def test_long_speaker_line_is_rejoined_without_break(echo_engine):
    line = _long_line(60)                                   # 約 1,100 字：切成 2–3 塊
    text = line + "\n說話人2：好，我同意。"
    assert len(tp.split_chunks(text)) >= 2
    res = asyncio.run(tp.polish_transcript(text, "fix", engine="csc"))
    out_lines = [l for l in res["polished"].split("\n") if l.strip()]
    assert out_lines[0] == line                             # 一整行，沒有在中間斷開
    assert out_lines[1] == "說話人2：好，我同意。"
    assert all(l.startswith("說話人") for l in out_lines)  # 每一段都有說話人標籤


def test_short_lines_keep_paragraph_breaks_between_chunks(echo_engine):
    lines = [f"說話人{1 + i % 2}：" + "我們今天討論第一個議題，預算還要再確認一次。" * 6 for i in range(8)]
    text = "\n".join(lines)
    chunks = tp.split_chunks(text)
    assert len(chunks) >= 2
    res = asyncio.run(tp.polish_transcript(text, "fix", engine="csc"))
    assert res["polished"] == "\n\n".join(chunks)          # 一般的塊照舊空一行（行為不變）


def test_segments_follow_the_same_join(echo_engine):
    text = _long_line(60)
    res = asyncio.run(tp.polish_transcript(text, "fix", engine="csc"))
    joined = "".join(seg[1] for seg in res["segments"] if seg[0] != "del")
    assert joined == res["polished"] == text               # 網頁標色接起來就是潤稿結果


def test_split_chunks_api_unchanged():
    text = _long_line(60)
    chunks = tp.split_chunks(text)
    assert "".join(chunks) == text                         # 切開的塊接起來就是原行（切點後的空白會被 lstrip，這裡沒有）
    assert all(len(c) <= tp.MAX_CHUNK_CHARS for c in chunks)
