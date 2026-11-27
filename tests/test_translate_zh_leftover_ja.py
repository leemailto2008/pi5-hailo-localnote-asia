"""11-27 .229 Issue：日文→中文大半原樣留著日文卻算翻好；阿拉伯文→中文抄出提示詞、一長串「．」。"""
import asyncio

import pytest

import transcript_translate as tt

JA_ECHO = "なんで？すねなんでロシアに金油金置いてんの？っていうことですけど、制約があって"


@pytest.mark.parametrize("t", [JA_ECHO, "うち原預金が約36百億円。為何？すね、為何ロシア",
                               "原文未提供正確的阿拉伯語句子，請提供正確的句子以便翻譯。",
                               "台灣繁體中文，數字照原樣保留：M.一"])
def test_zh_leftover_rejected(t):
    assert tt.untranslated_left(t, "zh") and not tt.mostly_translated(t, "zh")


@pytest.mark.parametrize("t", ["三菱商事和三井物產在庫頁島推動液化天然氣開發。", "這款遊戲叫「ポケモン」，下週上市，預算 300 萬元。",
                               "請各部門在週四前把名單交給吳副理。", "請提供正確的報價。"])
def test_zh_normal_kept(t):
    assert not tt.untranslated_left(t, "zh") and tt.mostly_translated(t, "zh")


def test_dot_runs_collapsed():
    assert tt.collapse_repeats("伊本巴姆" + "．" * 80 + "領導者..") == "伊本巴姆……領導者.."
    assert tt.collapse_repeats("等一下...好") == "等一下...好"


def test_japanese_echo_not_accepted(monkeypatch):
    """模型每次都把日文原樣回傳：不能當成翻好 (保留原文、記入 fallback)。"""
    async def echo(prompt, *a, **k):
        return "1| " + JA_ECHO
    monkeypatch.setattr(tt, "_complete", echo)
    res = asyncio.run(tt._translate_flat([JA_ECHO], "zh", None, lambda: False, use_cpu=False, one_chunk=True))
    assert res["done"] == {} and res["fallback_units"] == 1


def test_kanji_heavy_japanese_not_treated_as_chinese():
    import live_translate as lt
    s = "2024年の全國平均家賃は 5萬3135円。"
    assert not tt.is_japanese(s) and tt.source_is_japanese(s)
    assert lt.target_for(s, "auto") == "zh" and not tt.in_target_language(s, "zh")


@pytest.mark.parametrize("s", ["這家「鮮の味」的合約下週簽。", "鮮の味の門市預算 300 萬元。", "請各部門在週四前把名單交給吳副理。"])
def test_chinese_with_single_hiragana_stays_chinese(s):
    import live_translate as lt
    assert not tt.source_is_japanese(s) and lt.target_for(s, "auto") == "en" and tt.in_target_language(s, "zh")
