"""summary_utils 的邊界分支：OpenCC 不存在／轉換失敗、空輸入、單字差異判斷、逐字稿切段的尾段合併。
OpenCC 換成假的，不需要 opencc 套件。"""
import sys
import types

import pytest

import summary_utils as su


@pytest.fixture
def reset_cc(monkeypatch):
    monkeypatch.setattr(su, "_CC", None)
    yield
    su._CC = None


def test_to_taiwan_traditional_with_fake_opencc(monkeypatch, reset_cc):
    class CC:
        def __init__(self, cfg):
            assert cfg == "s2twp.json"

        def convert(self, s):
            return s.replace("软件", "軟體")
    monkeypatch.setitem(sys.modules, "opencc", types.SimpleNamespace(OpenCC=CC))
    assert su.to_taiwan_traditional("软件更新") == "軟體更新"
    assert su.to_taiwan_traditional("") == "" and su.to_taiwan_traditional(None) == ""


def test_to_taiwan_traditional_without_opencc_or_failing(monkeypatch, reset_cc):
    monkeypatch.setitem(sys.modules, "opencc", None)                 # import 失敗：之後都原樣回傳
    assert su.to_taiwan_traditional("软件") == "软件"
    assert su._CC is False

    class Boom:
        def convert(self, s):
            raise RuntimeError("bad dict")
    monkeypatch.setattr(su, "_CC", Boom())
    assert su.to_taiwan_traditional("软件") == "软件"                 # 轉換失敗：原樣回傳


def test_english_share_and_detect_language():
    assert su.english_share("") == 0.0 and su.english_share("一二三") == 0.0
    assert su.english_share("We will ship it to the team") == 1.0
    assert su.detect_language("We will ship it to the team on Monday and we can test it there") == "en"
    assert su.detect_language("這個 release 的 schedule 要 delay，QA 的 regression test 還沒 pass") == "zh"


@pytest.mark.parametrize("a,b,expect", [
    ("Monday", "Monday", True), ("Mondy", "Monday", True), ("Monday", "Mondey", True),
    ("abc", "abcd", True), ("abcd", "abc", True), ("ab", "ba", False), ("abc", "a", False),
    ("Tuesday", "Thursday", False), ("", "a", True), ("", "", True),
])
def test_edit1(a, b, expect):
    assert su._edit1(a, b) is expect


def test_split_transcript_merges_short_tail():
    body = "第一段的內容比較長，" * 9                                   # 約 90 字
    tail = "好。"
    chunks = su.split_transcript(body + "。" + tail, max_chars=100)
    assert chunks[-1].endswith(tail)
    assert all(c for c in chunks)
    assert "".join(chunks).replace(" ", "") == (body + "。" + tail).replace(" ", "")


def test_empty_inputs_pass_through():
    assert su.to_internal_sections("") == ""
    assert su.drop_unspoken_years("", "x") == ""
    assert su.split_transcript("") == []
