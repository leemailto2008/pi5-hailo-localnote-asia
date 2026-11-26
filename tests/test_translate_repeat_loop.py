"""11-26 阿拉伯文即時翻譯：模型陷入重複迴圈（「這種情況，這種情況，…」寫滿 num_predict）。
postfix 把連續 4 次以上的重複收成一次；串流中偵測到就停止生成。正常的重複與數字不動。"""
import asyncio

import pytest

import transcript_translate as tt


@pytest.mark.parametrize("text,want", [
    ("我們必須承認，這種情況，這種情況，這種情況，這種情況，這種情況，", "我們必須承認，這種情況，"),
    ("前往與國際貿易與全球貿易與全球貿易與全球貿易與全球", "前往與國際貿易與全球"),
    ("而且，我們的結果，我們的結果，我們的結果，我們的結果", "而且，我們的結果"),
])
def test_collapse_loops(text, want):
    assert tt.collapse_repeats(text) == want


@pytest.mark.parametrize("text", ["對對對，好", "1,000,000,000,000,000", "----------", "……………………", "No, no, no, no.",
                                  "Thank you, thank you.", "謝謝謝謝", ""])
def test_keep_normal(text):
    assert tt.collapse_repeats(text) == text


def test_postfix_collapses():
    assert tt.postfix("x", "結果，結果，結果，結果，結果，", "zh") == "結果，"


def test_stream_stops_on_loop(monkeypatch):
    sent = []

    async def fake_stream(*_a, **_k):
        yield "我們必須承認，", False, "hailo"
        for _ in range(500):
            sent.append(1)
            yield "這種情況，", False, "hailo"

    monkeypatch.setattr(tt, "aiter_chat_stream", fake_stream)
    out = asyncio.run(tt._complete("p", "zh", 900, hailo_only=True, cpu_first=False, should_stop=lambda: False))
    assert len(sent) < 40 and tt.has_repeat_loop(out)
    assert tt.collapse_repeats(out) == "我們必須承認，這種情況，"
