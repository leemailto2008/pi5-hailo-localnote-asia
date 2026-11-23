"""sv_lang_guard.whisper_verdict：Whisper 寫俄文／阿拉伯文／印地文…（SenseVoice 不支援）要判外語。
2026-11-23 localnote@mac（S12 深度審查）：docstring 說「Whisper 寫中文／日文／韓文 → SenseVoice 支援的語言」，
程式卻是「不是拉丁字母就 ok」：西里爾、阿拉伯、天城、希伯來、希臘字母全判成 ok，這些語言的會議永遠不改用
Whisper，即時稿與高精度稿只留 SenseVoice 的亂碼。改成：其他文字（非拉丁、非中日韓、非泰文）過半 → 外語（同泰文的規則）。
"""
import pytest

import sv_lang_guard as g

SV_EN, SV_YUE = ("<|en|>", "Then I here limo on Alice"), ("<|yue|>", "今日我哋")


@pytest.mark.parametrize("text", [
    "Сегодня мы обсуждаем бюджет на следующий квартал",     # 俄文
    "نناقش اليوم ميزانية الربع القادم",                      # 阿拉伯文
    "आज हम अगली तिमाही के बजट पर चर्चा करेंगे",              # 印地文
    "היום אנחנו דנים בתקציב",                                # 希伯來文
    "Σήμερα συζητάμε τον προϋπολογισμό",                    # 希臘文
], ids=["ru", "ar", "hi", "he", "el"])
@pytest.mark.parametrize("sv", [SV_EN, SV_YUE], ids=["sv_en", "sv_yue"])
def test_other_scripts_are_foreign(text, sv):
    assert g.whisper_verdict(sv[0], sv[1], text) == "foreign"


@pytest.mark.parametrize("text,expect", [
    ("今天我們討論下一季的預算", "ok"),
    ("今日は次の四半期の予算について話します", "ok"),
    ("오늘은 다음 분기 예산을 논의합니다", "ok"),
    ("預算 budget 要再確認", "ok"),                           # 中英夾雜：照舊 ok
    ("วันนี้เราจะคุยเรื่องงบประมาณ", "foreign"),                # 泰文：照舊
    ("Heute besprechen wir das Budget für das nächste Quartal", "foreign"),
    ("ok", None),                                             # 字太少：照舊看不出來
])
def test_existing_verdicts_unchanged(text, expect):
    assert g.whisper_verdict(SV_EN[0], SV_EN[1], text) == expect


def test_russian_meeting_switches_to_whisper():
    guard = g.ForeignLangGuard(clock=lambda: 0.0)
    out = []
    for _ in range(4):
        assert guard.should_probe("<|en|>")
        out.append(guard.decide("<|en|>", "Then I here limo", "Сегодня мы обсуждаем бюджет на квартал"))
    assert guard.foreign_mode() and out[-1] == "whisper"


@pytest.mark.parametrize("text,lead_space", [
    ("Hallo zusammen", True), ("Сегодня мы", True), ("نناقش اليوم", True), ("आज हम", True),
    ("วันนี้เรา", False), ("今天我們", False), ("오늘은 예산", False),
], ids=["de", "ru", "ar", "hi", "th", "zh", "ko"])
def test_pseudo_tokens_lead_space_for_space_separated_scripts(text, lead_space):
    """改用 Whisper 的片接在前一片後面：用空白分詞的文字（拉丁、西里爾、阿拉伯、天城…）第一個字前要有空白，
    否則高精度稿裡跟前一片黏在一起；中文、日文、泰文不用空白分詞，不補。tokens 接起來 strip() 仍等於原文。"""
    toks, times = g.pseudo_tokens(text, 1.0, 2.0)
    assert toks[0].startswith(" ") is lead_space
    assert "".join(toks).strip() == text and len(times) == len(toks) and times[0] == 1.0
