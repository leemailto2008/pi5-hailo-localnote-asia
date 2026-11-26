"""voice_pipeline.clean_stt_segment()：Hailo NPU 切片輸出的解碼迴圈清理 (2026-11-02，228 10929 個切片中 23 個)。"""
import sys
import types

import pytest

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import voice_pipeline as vp  # noqa: E402


@pytest.mark.parametrize("raw,clean", [
    ("上線前先在二十臺裝置上是跑三天沒有問題再全面更新ZZZZZZZZ", "上線前先在二十臺裝置上是跑三天沒有問題再全面更新"),
    ("林主任會在 10月21日前提出改善報告ZZZZZZZZZZZZZzZzZzZ", "林主任會在 10月21日前提出改善報告"),
    ("聖珀日，三日中，三日，三日，三日，三日，三日,", "聖珀日，三日中，三日，三日,"),
    ("I'm a little bit of a little bit of a little bit of a little bit of a", ""),     # 沒有中文的英文迴圈：整段丟掉
    # 夾在中文之間的純小寫英文長片語 (2026-11-09 3 分鐘 digital E2E 逐字稿：「…，w to stop the time for 3 hours，…」)：Whisper 幻覺，整段拿掉
    ("今天就到這裡，w to stop the time for 3 hours，謝謝大家", "今天就到這裡，謝謝大家"),
    ("第二題是品質異常，w to stop the time for 3 hours。第三題是", "第二題是品質異常，第三題是"),
    # 中英夾雜但不符合上述條件 (有大寫、或不到 4 個詞)：不動
    ("這個 ok sure 好的，謝謝", "這個 ok sure 好的，謝謝"),
    ("我們先討論 Q3 預算，Please check the schedule before Friday，謝謝", "我們先討論 Q3 預算，Please check the schedule before Friday，謝謝"),
    # 正常內容不動
    ("測試的部分請御經理安排至少要做10輪回 測", "測試的部分請御經理安排至少要做10輪回 測"),
    ("名額30人目前已經報名22人還剩8個名", "名額30人目前已經報名22人還剩8個名"),
    ("對對對，好好好，我們先這樣", "對對對，好好好，我們先這樣"),
    # 單字 + 逗號的連續重複 (2026-11-10 45 分鐘 digital E2E 逐字稿：「車用的的，的，的，的，的，的，淨室」)：同一字 4 次以上壓成一次
    ("第九十二個議題是車用的的，的，的，的，的，的，淨室的部分", "第九十二個議題是車用的的，淨室的部分"),
    ("是，是，是，好", "是，是，是，好"),          # 3 次以下不動 (口語常見)
    ("We need two more engineers to finish the migration", "We need two more engineers to finish the migration"),
    ("no no no, that is not what I said", "no no no, that is not what I said"),
    ("yes yes yes I agree", "yes I agree"),             # 單字重複：壓成一次 (沿用原本的片語規則)，不會整段丟掉
    ("AAA 級的供應商", "AAA 級的供應商"),
    ("", ""),
])
def test_clean_stt_segment(raw, clean):
    assert vp.clean_stt_segment(raw) == clean


# 11-26 .229 Issue（馬來文／阿拉伯文經藍牙、SCO 到達 79–84%）：多詞片語連續 3 次以上只留一次
@pytest.mark.parametrize("raw,want", [
    ("I have a lot of questions. I have a lot of questions. I have a lot of questions. And I can be so best",
     "I have a lot of questions. And I can be so best"),
    ("و فيه شي و فيه شي و فيه شي و فيه شي", "و فيه شي"),
    ("Dewa vocal. Dewa vocal. Dewa vocal. Perasaannya gimana mas waktu", "Dewa vocal. Perasaannya gimana mas waktu"),
])
def test_multiword_loop_collapsed(raw, want):
    assert vp.clean_stt_segment(raw) == want


@pytest.mark.parametrize("raw", ["We need to check, we need to check the budget", "1 2 1 2 1 2", "bisa bisa bisa",
                                 "好的 好的 好的"])
def test_multiword_normal_kept(raw):
    assert vp.clean_stt_segment(raw) == raw
