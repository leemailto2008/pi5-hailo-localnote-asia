"""英文譯文的姓氏拼音要用姓氏讀音（2026-11-23 localnote@mac 審查 a8fc4bf 時找到）。

lazy_pinyin 取常用讀音：「曾」→ ceng、「覃」→ tan，但當姓讀 Zeng、Qin。結果：
- fix_name_zh_titles：模型已經翻對的「Zeng经理」被「原文唯一的姓」規則改成「Manager Ceng」；
- fix_cjk_name_titles：「覃小姐」→「Ms. Tan」；romanize_titled_names：「Mr. 曾」→「Mr. Ceng」。
"""
import pytest

import transcript_translate as tt

pytest.importorskip("pypinyin")


@pytest.mark.parametrize("src,translation,expect", [
    ("曾經理說明天開會", "Zeng经理 said the meeting is tomorrow.", "Manager Zeng said the meeting is tomorrow."),
    ("曾經理說明天開會", "Ceng经理 said the meeting is tomorrow.", "Manager Zeng said the meeting is tomorrow."),
    ("李先生明天來", "Li先生 will come tomorrow.", "Mr. Li will come tomorrow."),          # 一般姓不受影響
])
def test_fix_name_zh_titles_uses_surname_reading(src, translation, expect):
    assert tt.fix_name_zh_titles(src, translation, "en") == expect


@pytest.mark.parametrize("src,translation,expect", [
    ("覃小姐負責", "覃小姐 is responsible.", "Ms. Qin is responsible."),
    ("曾經理說", "曾经理 said so.", "Manager Zeng said so."),
    ("林小姐負責", "林小姐 is responsible.", "Ms. Lin is responsible."),
])
def test_fix_cjk_name_titles_uses_surname_reading(src, translation, expect):
    assert tt.fix_cjk_name_titles(src, translation, "en") == expect


@pytest.mark.parametrize("src,translation,expect", [
    ("請曾小明確認", "Please ask Mr. 曾小明 to confirm.", "Please ask Mr. Zeng Xiaoming to confirm."),
    ("請曾經理確認", "Please ask Manager 曾 to confirm.", "Please ask Manager Zeng to confirm."),
    ("請王小明確認", "Please ask Mr. 王小明 to confirm.", "Please ask Mr. Wang Xiaoming to confirm."),
])
def test_romanize_titled_names_uses_surname_reading(src, translation, expect):
    assert tt.romanize_titled_names(src, translation, "en") == expect


def test_surname_pinyin_helper():
    assert tt._surname_pinyin("曾") == "Zeng" and tt._surname_pinyin("覃") == "Qin"
    assert tt._surname_pinyin("蔡") == "Cai"


def test_section_chief_written_as_principal_is_fixed():
    # 11-25 重放：「劉課長」被模型寫成同音的「校长」→「Liu校长」
    out = tt.fix_name_zh_titles("文宣請劉課長,週一前交初稿", "Please have Liu校长 review the draft by Monday.", "en")
    assert out == "Please have Section Chief Liu review the draft by Monday."


def test_real_principal_is_kept():
    # 原文真的有「校長」就不換
    src = "請劉課長和王校長一起開會"
    out = tt.fix_name_zh_titles(src, "Please have Liu课长 and Wang校长 meet.", "en")
    assert "校长" in out and "Section Chief Liu" in out
