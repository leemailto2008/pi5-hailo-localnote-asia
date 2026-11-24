"""N5（2026-11-24 localnote@mac）：翻譯流程的小函式邊界（突變測試：160 個突變原本存活 55 個）。
in_target_language／untranslated_left／mostly_translated 的門檻照 docstring；parse_lines、group_chunks、build_prompt、
assemble（逐段顯示 upto）、_num_predict。"""
import pytest

import transcript_translate as tt


@pytest.mark.parametrize("text,want", [
    ("...", True), ("。", True), ("12,500", True),                         # 只有標點／數字：照抄
    ("the plan is good and the team agreed", True),
    ("we will ship it de", True),                                        # 5 個字 1 個外語功能詞：foreign*5 <= words
    ("we will ship it de la", False),                                    # 6 個字 2 個：超過
    ("plan budget review done", True),                                   # 4 個字、沒有外語功能詞：紀要條目算英文
    ("plan budget review", False),                                       # 3 個字：送翻
    ("Wunderbar.", False), ("café meeting is done now", False),          # 帶附加符號的拉丁字母：不是英文
    ("Привет all team members", False), ("会議 is done", False),
])
def test_in_target_language_en(text, want):
    assert tt.in_target_language(text, "en") is want


@pytest.mark.parametrize("text,want", [("中文abcd", True), ("中文abcde", False), ("abc", False), ("今日の会議を始めます", False),
                                       ("開會", True)])
def test_in_target_language_zh(text, want):
    assert tt.in_target_language(text, "zh") is want                     # 中文字 ×2 ≥ 英文字母、不是日文


@pytest.mark.parametrize("text,want", [("IBM", False), ("IBMX", True), ("中" + "a" * 12, True), ("中文" + "a" * 8, False),
                                       ("中文三" + "a" * 12, False), ("中文" + "a" * 11, False), ("中文" + "a" * 12, True)])
def test_untranslated_left_zh(text, want):
    # 翻中文：沒有中文字時英文字母 ≥ 4 算沒翻；有中文字時英文字母 ≥ 12 而且 > 中文字 ×4 才算
    assert tt.untranslated_left(text, "zh") is want


@pytest.mark.parametrize("text,want", [("abc中ab", True), ("中中中abcdefg", True), ("中中中中abcdef", False), ("abc", True)])
def test_mostly_translated_boundary(text, want):
    assert tt.mostly_translated(text, "en") is want                     # 中文字 ≤ 30%


def test_build_prompt_heads():
    assert tt.build_prompt([(0, "今天開會")], "en").startswith("Translate into English:\n1| ")
    assert tt.build_prompt([(0, "We meet today")], "zh") == "翻成繁體中文：\n1| We meet today"


def test_parse_lines_labels_and_blank_lines():
    rows = tt.parse_lines("說話人1：你好。\n\n   \nSpeaker 2: Hello there.\n沒有標籤的一行")
    assert rows == [("1", ["你好。"]), ("2", ["Hello there."]), ("", ["沒有標籤的一行"])]


def test_group_chunks_exact_limit_stays_together():
    units = [(0, "a" * 60), (1, "b" * 60), (2, "c" * 1)]
    assert [len(c) for c in tt.group_chunks(units, limit=200)] == [2, 1]     # 第一個請求剛好 120 字 (FIRST_CHUNK_CHARS)
    units = [(0, "a" * 100), (1, "b" * 100), (2, "c" * 160), (3, "d" * 1)]
    assert [len(c) for c in tt.group_chunks(units, limit=260)] == [1, 2, 1]


def test_assemble_upto_stops_mid_row_and_at_row_start():
    rows = [("1", ["a", "b", "c"]), ("2", ["d"])]
    assert tt.assemble(rows, {0: "A"}, "en", upto=1) == "Speaker 1: A"
    assert tt.assemble(rows, {0: "A", 1: "B", 2: "C"}, "en", upto=3) == "Speaker 1: A B C"   # 剛好到行尾：下一行不出現
    assert tt.assemble(rows, {}, "zh", upto=None) == "說話人1：abc\n說話人2：d"


@pytest.mark.parametrize("chars,target,want", [(100, "en", 136), (100, "zh", 120), (300, "zh", 216), (1000, "en", 900),
                                               (80, "en", 120)])
def test_num_predict(chars, target, want):
    assert tt._num_predict([(0, "x" * chars)], target) == want            # 中翻英 1.3／英翻中 0.7 token 每字＋每行 6，限 120–900


def test_more_language_boundaries():
    assert tt.in_target_language("Привет", "zh") is False                 # 沒有中文字也沒有英文字母：不是中文
    assert tt.in_target_language("好", "zh") is True                       # 一個中文字也算
    assert tt.in_target_language("we will ship it to them today de la", "en") is False   # 9 個字 2 個外語功能詞
    assert tt.untranslated_left("中文三" + "a" * 13, "zh") is True          # 13 > 3×4


def test_parse_output_ignores_line_zero():
    assert tt.parse_output("0| zero\n1| one", 1) == {1: "one"}
