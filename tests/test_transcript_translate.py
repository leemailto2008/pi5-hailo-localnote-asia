"""完整逐字稿翻譯 (transcript_translate)：切單位、保留說話人、已是目標語言照抄、對不上的單位重翻、錄音開始時停下。"""
import asyncio
import re
import sys
import types

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import transcript_translate as tt  # noqa: E402

REFINE = ("說話人1：好，我們開始今天的週會。第一個議題是教育訓練。\n"
          "說話人2：Okay, the training course is on September 2nd.\n"
          "說話人1：目前已經報名22人，還剩8個名額。")


def _fake(responses=None, drop=(), stop_after=None):
    """假的模型：把每行「N| 原文」翻成「N| EN(原文)」；drop 裡的原文故意不輸出 (測重翻)；stop_after 段後回 None (錄音開始)。"""
    calls = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        calls.append((prompt, hailo_only, cpu_first))
        if stop_after is not None and len(calls) > stop_after:
            return None
        await asyncio.sleep(0.001)
        out = []
        for m in re.finditer(r"^(\d+)\| (.*)$", prompt, re.M):
            if m.group(2) in drop and "\n" in prompt.split("\n", 1)[1]:   # 只在多行請求裡漏掉，單獨重翻時給
                continue
            out.append(f"{m.group(1)}| {'EN' if target == 'en' else '中'}({m.group(2)})")
        return "\n".join(out)
    return complete, calls


def test_parse_lines_keeps_speakers_and_splits_sentences():
    rows = tt.parse_lines(REFINE)
    assert [s for s, _ in rows] == ["1", "2", "1"]
    assert rows[0][1] == ["好，我們開始今天的週會。", "第一個議題是教育訓練。"]
    assert tt.parse_lines("一段沒有標點" + "很長的逐字稿，" * 40)[0][1][0].endswith("，")   # 超過 UNIT_CHARS 在逗號切
    assert all(len(u) <= tt.UNIT_CHARS for u in tt.parse_lines("字" * 500)[0][1])


def test_target_language_units_are_copied_not_sent(monkeypatch):
    fake, calls = _fake()
    monkeypatch.setattr(tt, "_complete", fake)
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=False))
    lines = res["text"].splitlines()
    assert lines[0] == "Speaker 1: EN(好，我們開始今天的週會。) EN(第一個議題是教育訓練。)"
    assert lines[1] == "Speaker 2: Okay, the training course is on September 2nd."     # 英文句照抄
    assert lines[2].startswith("Speaker 1: EN(目前已經報名22人")
    assert res["kept_units"] == 1 and res["fallback_units"] == 0 and not res["stopped"]
    assert all("Okay, the training" not in p for p, _h, _c in calls)


def test_to_chinese_keeps_label_and_uses_taiwan_wording(monkeypatch):
    fake, _ = _fake()
    monkeypatch.setattr(tt, "_complete", fake)
    res = asyncio.run(tt.translate_transcript(REFINE, "zh", use_cpu=False))
    lines = res["text"].splitlines()
    assert lines[0] == "說話人1：好，我們開始今天的週會。第一個議題是教育訓練。"            # 已是中文照抄
    assert lines[1] == "說話人2：中(Okay, the training course is on September 2nd.)"


def test_missing_numbered_line_is_retranslated_alone(monkeypatch):
    fake, calls = _fake(drop=("第一個議題是教育訓練。",))
    monkeypatch.setattr(tt, "_complete", fake)
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=False))
    assert "EN(第一個議題是教育訓練。)" in res["text"]
    assert any(p.count("\n") == 1 and "第一個議題" in p for p, _h, _c in calls)                # 單獨重翻那一句


def test_stops_between_chunks_when_recording_starts_and_keeps_rest(monkeypatch):
    fake, _ = _fake(stop_after=1)
    monkeypatch.setattr(tt, "_complete", fake)
    monkeypatch.setattr(tt, "CHUNK_CHARS", 20)                                                   # 每句一段
    progress = []
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=False,
                                              on_progress=lambda d, t, p: progress.append((d, t, p))))
    assert res["stopped"] and res["translated_chunks"] == 1
    assert "EN(好，我們開始今天的週會。)" in res["text"] and "目前已經報名22人" in res["text"]   # 沒翻到的保留原文
    assert progress[-1][0] == 1 and "第一個議題" not in progress[-1][2]                         # 逐段顯示只到連續翻好的前段


def test_two_workers_hailo_and_cpu_split_chunks_in_order(monkeypatch):
    fake, calls = _fake()
    monkeypatch.setattr(tt, "_complete", fake)
    monkeypatch.setattr(tt, "CHUNK_CHARS", 20)
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=True))
    assert {(h, c) for _p, h, c in calls} == {(True, False), (False, True)}                     # 兩路都有拿到段
    assert res["translated_chunks"] == res["chunks"] == 3
    t = res["text"]
    assert t.index("今天的週會") < t.index("教育訓練") < t.index("報名22人")                     # 順序照原文


def test_parse_output_tolerates_formats():
    got = tt.parse_output("1| Hello\n2. World\n 3：Third\nnoise\n4| ", 3)
    assert got == {1: "Hello", 2: "World", 3: "Third"}
