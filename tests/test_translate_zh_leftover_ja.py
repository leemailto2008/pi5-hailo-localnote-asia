"""11-27 .229 Issue：日文→中文大半原樣留著日文卻算翻好；阿拉伯文→中文抄出提示詞、一長串「．」。"""
import asyncio
import os
import sys
import types

import pytest

# live_translate 要 import config（telegram_agent/config.py，不在 conftest 的路徑裡）：單獨跑這個檔時沒有別的測試先放進
# sys.modules，4 項 ModuleNotFoundError（P14）。照 test_live_translate 的做法放一個替身
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import transcript_translate as tt  # noqa: E402

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


# P14（localnote@mac）：dffce74 的門檻邊界（突變測試補強）
@pytest.mark.parametrize("ch", list("．.·・。"))
def test_dot_run_threshold_each_char(ch):
    assert tt.collapse_repeats("好" + ch * 6) == "好……"         # 6 個起收
    assert tt.collapse_repeats("好" + ch * 5) == "好" + ch * 5    # 5 個不動


def test_japanese_left_boundaries():
    assert tt.japanese_left("のはが" + "中" * 22)          # 3 個平假名、比例 3/25 = 0.12 剛好成立
    assert not tt.japanese_left("のは" + "中" * 10)         # 只有 2 個平假名
    assert not tt.japanese_left("のはが" + "中" * 23)      # 3/26 < 0.12


def test_prompt_leak_each_phrase():
    for p in ("數字照原樣保留", "翻成繁體中文：", "原文未提供正確的", "請提供正確的句子"):
        assert tt.prompt_leaked("好的。" + p)
    assert not tt.prompt_leaked("字照原樣")
