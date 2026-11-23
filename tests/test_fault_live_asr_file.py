"""故障注入：即時切片結果檔（*.live_asr.json）內容格式不對（2026-11-23 localnote@mac，S7）。

load_live_asr／live_asr_language 原本只接 JSON 解不開（ValueError）：合法 JSON 但結構不對
（最外層是陣列、切片少欄位、數字欄位是字串）會拋 AttributeError／KeyError／TypeError，
讓整個高精度稿失敗。應該跟「檔案壞掉」一樣：回 None／"auto"，高精度稿整段重新辨識。
"""
import json

import pytest

import refine_transcript as rt


@pytest.fixture
def live_file(tmp_path, monkeypatch):
    path = tmp_path / "m_1.live_asr.json"
    monkeypatch.setattr(rt, "live_asr_path", lambda audio_path, suffix=rt.LIVE_ASR_SUFFIX: str(path))

    def write(obj):
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return write


@pytest.mark.parametrize("data", [
    ["not", "a", "dict"],                                  # 最外層不是物件
    {"slices": [{"n": 16000, "text": "缺 s"}]},             # 切片少欄位
    {"slices": [{"s": 0, "n": "abc"}]},                    # n 不是數字
    {"slices": "oops"},                                    # slices 不是陣列
    {"slices": [None]},                                    # 切片不是物件
    "just a string",
])
def test_malformed_live_asr_means_redecode(live_file, data):
    live_file(data)
    assert rt.load_live_asr("/x/m_1.ogg", 16000) is None


@pytest.mark.parametrize("data", [["zh"], "en", 42])
def test_malformed_language_means_auto(live_file, data):
    live_file(data)
    assert rt.live_asr_language("/x/m_1.ogg") == "auto"


def test_valid_file_still_works(live_file):
    live_file({"version": 1, "language": "zh", "slices": [{"s": 0, "n": 8000, "text": "好"}, {"s": 8000, "n": 8000}]})
    out = rt.load_live_asr("/x/m_1.ogg", 16000)
    assert [(s["s"], s["n"]) for s in out] == [(0, 8000), (8000, 8000)]
    assert rt.live_asr_language("/x/m_1.ogg") == "zh"
