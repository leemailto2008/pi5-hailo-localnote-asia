"""含漢字的日文不能當成中文（2026-11-23 localnote@mac，S14 深度審查）。
- transcript_translate.in_target_language(日文, "zh") 原本是 True：日文翻中文時，含漢字的句子被當成「已經是中文」照抄不翻
  （網頁按「中」、即時翻譯在語系選日文時 effective_mode=zh）。英文那邊早就用 _OTHER_SCRIPT_RE 排除假名，中文這邊漏了。
- live_translate.target_for(日文, "auto") 原本是 "en"：auto 模式下日文會議一句翻英文、一句翻中文交錯。
有假名（平假名、片假名）就是日文。
"""
import os
import sys
import types

import pytest

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import live_translate as lt  # noqa: E402
import transcript_translate as tt  # noqa: E402

JA = ["今日の会議を始めます。", "来月の予算は5万3135円です。", "それでは、次の議題に移りましょう。",
      "はい、そうです。", "プロジェクトの進捗を報告します。", "サーバーを更新しました"]
ZH = ["我們今天討論預算。", "第一個議題是出差安排", "預算 budget 要再確認", "好的，下一個"]


@pytest.mark.parametrize("s", JA)
def test_japanese_is_not_already_chinese(s):
    assert not tt.in_target_language(s, "zh")


@pytest.mark.parametrize("s", JA)
def test_auto_translates_japanese_to_chinese(s):
    assert lt.target_for(s, "auto") == "zh"


@pytest.mark.parametrize("s", ZH)
def test_chinese_unchanged(s):
    assert tt.in_target_language(s, "zh")
    assert lt.target_for(s, "auto") == "en"


def test_japanese_still_not_english():
    assert not tt.in_target_language("今日の会議を始めます。", "en")


@pytest.mark.parametrize("s", ["中文句子裡夾了一個キ字", "日本人である私にとって日本の製品やサービスが高く評価されることは",
                               "我們下週 review PR，QA 的 regression test 還沒 pass", "トヨタ的預算增加了"] + JA + ZH)
def test_same_rule_as_whisper_engine(s):
    """和 hailo_whisper.engine.text_language 的中日判斷一致（中文夾一個假名仍是中文）。"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from hailo_whisper.engine import text_language
    assert tt.is_japanese(s) == (text_language(s) == "ja")


def test_chinese_with_one_kana_is_still_chinese():
    assert tt.in_target_language("中文句子裡夾了一個キ字", "zh")
    assert lt.target_for("中文句子裡夾了一個キ字", "auto") == "en"
