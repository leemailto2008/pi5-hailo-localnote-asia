# -*- coding: utf-8 -*-
import asyncio

import pytest

import summary_utils
import transcript_polish as tp
from llm_backend import LLMError


@pytest.fixture(autouse=True)
def _no_rewrite_pre_csc(monkeypatch):
    monkeypatch.setattr(tp, "PRE_CSC", False)   # 測試不載入真的 MacBERT（Pi 上有裝）；要測的測試自己打開


class _FakeBackend:
    label = "CPU Ollama qwen2.5:3b-opt"


def _run(coro):
    return asyncio.run(coro)


def _stream(reply, seen=None):
    """aiter_chat_stream 的假版本：reply(prompt) 回傳整段文字（或 raise），一次吐出。seen 收集呼叫參數。"""
    async def fake(prompt, system=None, **kwargs):
        if seen is not None:
            seen.append({"prompt": prompt, "system": system, **kwargs})
        yield reply(prompt), True, _FakeBackend()
    return fake


def _chunk_of(prompt):
    return prompt.split("逐字稿片段：\n", 1)[1]


def test_split_chunks_respects_limit_and_keeps_all_text():
    text = "\n".join(["甲" * 250, "乙" * 250, "丙" * 250])
    chunks = tp.split_chunks(text, max_chars=600)
    assert chunks == ["甲" * 250 + "\n" + "乙" * 250, "丙" * 250]
    assert all(len(c) <= 600 for c in chunks)


def test_split_chunks_cuts_long_line_after_punctuation():
    line = "一" * 300 + "。" + "二" * 400
    chunks = tp.split_chunks(line, max_chars=600)
    assert chunks == ["一" * 300 + "。", "二" * 400]


def test_split_chunks_skips_blank_lines():
    assert tp.split_chunks("\n\n  \n", max_chars=600) == []


def test_accept_homophone_edits_keeps_homophones_and_one_char_insertions():
    out, st = tp.accept_homophone_edits("請李協里確認期，行成三天", "請李協理確認日期，行程三天")
    assert out == "請李協理確認日期，行程三天"     # 里→理、成→程（同音）、補「日」
    assert st == {"accepted": 3, "rejected": 0}


def test_accept_homophone_edits_rejects_rewrites_deletions_and_number_changes():
    out, _ = tp.accept_homophone_edits("我們今天就先討論到這裡", "今天的會議到此結束")
    assert out == "我們今天就先討論到這裡"           # 刪字、非同音的改寫都不收
    out, _ = tp.accept_homophone_edits("庫存。第十二個，吳副理", "庫存管理。第12個，吳部長")
    assert out == "庫存。第十二個，吳副理"           # 補 2 字、數字寫法、非同音（副理→部長）都不收


def test_accept_homophone_edits_never_touches_speaker_labels():
    src = "說話人1：大家好\n說話人2：李協里好"
    dst = "說話人3：大家好\n說話人2：李協理好"
    out, st = tp.accept_homophone_edits(src, dst, tp.protected_spans(src))
    assert out == "說話人1：大家好\n說話人2：李協理好"
    assert st == {"accepted": 1, "rejected": 1}


def test_accept_homophone_edits_rejects_insertions_at_line_or_chunk_end():
    src = "說話人3：所以我們在運\n說話人1：動激觸過程。因為畢竟是老師。"
    dst = "說話人3：所以我們在運動\n說話人1：動激觸過程。因為畢竟是老師。還"
    out, stats = tp.accept_homophone_edits(src, dst, tp.protected_spans(src))
    assert out == src
    assert stats == {"accepted": 0, "rejected": 2}


def test_accept_homophone_edits_keeps_original_layout():
    out, st = tp.accept_homophone_edits("第一行\n第二行", "第一行第二行")
    assert out == "第一行\n第二行" and st == {"accepted": 0, "rejected": 0}


def test_polish_fix_applies_per_chunk_and_keeps_original_on_llm_error(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        if len(calls) == 2:
            raise LLMError("boom")
        return _chunk_of(prompt).replace("行成", "行程")

    text = "\n".join(["行成" + "甲" * 590, "行成" + "乙" * 590])
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(reply))
    res = _run(tp.polish_transcript(text, "fix"))
    assert res["chunks"] == 2 and res["failed_chunks"] == 1
    assert res["backend"] == "CPU Ollama qwen2.5:3b-opt"
    assert res["polished"] == "行程" + "甲" * 590 + "\n\n" + "行成" + "乙" * 590
    assert res["accepted_edits"] == 1
    assert "".join(t for op, t, _ in res["segments"] if op != "del") == res["polished"]
    assert ["rep", "程", "成"] in res["segments"]
    assert res["diff_counts"] == {"rep": 1, "ins": 0, "del": 0}


def test_polish_fix_uses_cpu_first_and_strips_echoed_header(monkeypatch):
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "逐字稿片段：" + _chunk_of(p).replace("期", "日期"), seen))
    res = _run(tp.polish_transcript("確認期", "fix", source="refine"))
    assert res["polished"] == "確認日期"
    assert res["source"] == "refine"
    assert seen[0]["cpu_first"] is True
    assert seen[0]["system"] == tp.FIX_SYSTEM


def test_polish_rewrite_uses_hailo_first(monkeypatch):
    # 11-11 量測：rewrite 用 CPU qwen2.5:3b 會改掉人名，Hailo qwen3:1.7b 不會（見檔頭）。
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "二" * 80, seen))
    _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert seen[0]["cpu_first"] is False
    assert seen[0]["system"] == tp.REWRITE_SYSTEM


def test_polish_backend_is_chosen_per_mode(monkeypatch):
    seen = []
    monkeypatch.setattr(tp, "POLISH_BACKENDS", {"fix": "hailo", "rewrite": "cpu"})
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of, seen))
    _run(tp.polish_transcript("確認日期", "fix"))
    _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert [s["cpu_first"] for s in seen] == [False, True]


def test_polish_reports_progress_per_chunk(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of))
    seen = []
    text = "\n".join(["甲" * 590, "乙" * 590, "丙" * 590])
    res = _run(tp.polish_transcript(text, "fix", on_progress=lambda done, total: seen.append((done, total))))
    assert seen == [(1, 3), (2, 3), (3, 3)]
    assert res["stopped"] is False


def test_polish_stops_between_chunks_and_keeps_rest_original(monkeypatch):
    calls = []

    def reply(prompt):
        calls.append(prompt)
        return _chunk_of(prompt).replace("行成", "行程")

    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(reply))
    text = "\n".join(["行成" + "甲" * 590, "行成" + "乙" * 590, "行成" + "丙" * 590])
    # 第一段做完後「開始錄音」：第二段開始前就要停。
    done = []
    res = _run(tp.polish_transcript(text, "fix", on_progress=lambda d, t: done.append(d), should_stop=lambda: len(done) >= 1))
    assert len(calls) == 1
    assert res["stopped"] is True
    assert res["polished"] == "\n\n".join(["行程" + "甲" * 590, "行成" + "乙" * 590, "行成" + "丙" * 590])
    assert res["diff_counts"]["rep"] == 1   # 沒處理的段落不標


def test_polish_stops_mid_generation_and_closes_the_stream(monkeypatch):
    state = {"tokens": 0, "closed": False}

    async def slow_stream(prompt, system=None, **kwargs):
        try:
            for tok in ["改", "善", "甲"]:
                state["tokens"] += 1
                yield tok, False, _FakeBackend()
        finally:
            state["closed"] = True

    monkeypatch.setattr(tp, "aiter_chat_stream", slow_stream)
    res = _run(tp.polish_transcript("改報甲", "fix", should_stop=lambda: state["tokens"] >= 1))
    assert res["stopped"] is True
    assert res["polished"] == "改報甲"            # 生成中被打斷的那段保留原文
    assert state["closed"] is True and state["tokens"] == 1


def test_polish_rewrite_rejects_suspicious_length(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "短"))
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "一" * 100
    assert res["rejected_chunks"] == 1


def test_polish_rewrite_accepts_reasonable_output(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "二" * 80))
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "二" * 80
    assert res["rejected_chunks"] == 0


def test_polish_rejects_unknown_mode():
    with pytest.raises(ValueError):
        _run(tp.polish_transcript("abc", "summarize"))


class _FakeCC:
    """測試用的簡轉台灣繁體：只換本檔用到的字。"""

    def convert(self, text):
        return text.translate(str.maketrans({"没": "沒", "伤": "傷", "协": "協", "员": "員"}))


def test_polish_fix_ignores_script_only_changes(monkeypatch):
    # 模型把繁體「修」成簡體：轉回台灣繁體後與原文相同，不算修改；真正的修改仍保留且為繁體。
    monkeypatch.setattr(summary_utils, "_CC", _FakeCC())
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "没有人受伤，李协理"))
    res = _run(tp.polish_transcript("沒有人受傷，李協里", "fix"))
    assert res["polished"] == "沒有人受傷，李協理"
    assert res["diff_counts"] == {"rep": 1, "ins": 0, "del": 0}


def test_polish_rewrite_output_is_taiwan_traditional(monkeypatch):
    monkeypatch.setattr(summary_utils, "_CC", _FakeCC())
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "全员" + "二" * 80))
    res = _run(tp.polish_transcript("一" * 100, "rewrite"))
    assert res["polished"] == "全員" + "二" * 80


def test_polish_rewrite_keeps_original_when_numbers_change(monkeypatch):
    # 日期、數量被改掉 (或中文化) 的段落保留原文。
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "修正版預計十月十二日上線，先在一百臺裝置上試跑三天" + "。" * 10))
    text = "修正版 預記 10月11日上線，先在100臺裝置上市跑三天"
    res = _run(tp.polish_transcript(text, "rewrite"))
    assert res["polished"] == text
    assert res["fact_rejected_chunks"] == 1


def test_polish_rewrite_accepts_when_numbers_are_kept(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "修正版預計10月11日上線，先在100臺裝置上試跑三天"))
    text = "修正版 預記 10月11日上線，先在100臺裝置上市跑三天"
    res = _run(tp.polish_transcript(text, "rewrite"))
    assert res["polished"] == "修正版預計10月11日上線，先在100臺裝置上試跑三天"
    assert res["fact_rejected_chunks"] == 0


LABELLED = "說話人1：負責人是許經理。第三個議題是行銷活動。\n說話人2：攤位費15萬元。\n說話人1：週五回報。"


def test_split_labels_separates_speaker_labels():
    labels, bodies = tp.split_labels("說話人1：你好。\n沒有標籤\n說話人12：嗯。")
    assert labels == ["說話人1：", "", "說話人12："]
    assert bodies == ["你好。", "沒有標籤", "嗯。"]


def test_cut_like_restores_line_count_when_model_splits_a_line():
    src = ["負責人是許經理。第三個議題是行銷活動。", "攤位費15萬元。", "週五回報。"]
    out = "負責人是許經理。\n第三個議題是行銷活動。\n攤位費15萬元。\n週五回報。"
    assert tp.cut_like(src, out) == src


def test_cut_like_follows_edits_and_merged_lines():
    src = ["行成4天。", "預算抓12萬元。"]
    out = "行程4天。預算抓12萬元。"
    assert tp.cut_like(src, out) == ["行程4天。", "預算抓12萬元。"]


def test_cut_like_does_not_move_words_across_a_mid_sentence_speaker_change():
    # 高精度稿常在句中換人：原文那行沒有標點結尾時，不能把切點拉到前面的逗號（會把「所以你會」搬給下一個人）。
    src = ["塞到一兩百公時寬，所以你會", "走繞來繞走外觀，對你就會切啊。"]
    out = "塞到一兩百公時寬，所以你會走繞來繞走外觀，你就會切。"
    assert tp.cut_like(src, out) == ["塞到一兩百公時寬，所以你會", "走繞來繞走外觀，你就會切。"]


def test_polish_rewrite_keeps_speaker_labels_out_of_the_model(monkeypatch):
    seen = []
    # 模型照實錄行為：沒有標籤、在議題轉換處把一行拆成兩行、順手修錯字。
    reply = lambda p: "負責人是許經理。\n第三個議題是行銷活動。\n攤位費十五萬元。\n週五回報。".replace("十五", "15")
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(reply, seen))
    res = _run(tp.polish_transcript(LABELLED.replace("議題", "議體"), "rewrite", source="refine"))
    assert "說話人" not in _chunk_of(seen[0]["prompt"])
    assert res["polished"] == LABELLED
    assert res["rejected_lines"] == 0 and res["fact_rejected_chunks"] == 0


def test_polish_rewrite_keeps_only_the_line_whose_number_changed(monkeypatch):
    reply = lambda p: "負責人是許經理，第三個議題是行銷活動。\n攤位費16萬元。\n週五前回報。"
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(reply))
    res = _run(tp.polish_transcript(LABELLED, "rewrite", source="refine"))
    assert res["polished"].split("\n") == [
        "說話人1：負責人是許經理，第三個議題是行銷活動。", "說話人2：攤位費15萬元。", "說話人1：週五前回報。"]
    assert res["rejected_lines"] == 1


def test_revert_byte_slips_restores_same_block_replacements_only():
    # 殼 E6 AE BC → 殠 E6 AE A0（只差最後一個位元組）改回；成→程、體→題 是真的改字，保留。
    out, n = tp.revert_byte_slips("外殼刮傷，行成4天，議體", "外殠刮傷，行程4天，議題")
    assert out == "外殼刮傷，行程4天，議題"
    assert n == 1


def test_polish_rewrite_reverts_byte_slips(monkeypatch):
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "客訴主要是外殔刮傷。\n週五回報。"))
    res = _run(tp.polish_transcript("說話人1：客訴主要是外殼刮傷。\n說話人2：週五回報。", "rewrite", source="refine"))
    assert res["polished"] == "說話人1：客訴主要是外殼刮傷。\n說話人2：週五回報。"
    assert res["reverted_chars"] == 1


def test_csc_apply_predictions_takes_confident_single_char_swaps_only():
    import csc_corrector as cc
    trad = "行成4天，協理"
    piece = "行成4天，协理"                       # t2s 後的視窗
    offsets = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7)]
    preds = [("行", 0.99), ("程", 0.95), ("4", 0.9), ("天", 0.9), ("，", 0.9), ("协", 0.9), ("利", 0.4)]
    out = list(trad)
    n = cc.apply_predictions(trad, 0, piece, offsets, preds, lambda s: {"程": "程", "利": "利"}.get(s, s), out)
    assert "".join(out) == "行程4天，協理"       # 協理→協利 機率 0.4 < MIN_PROB 0.5，不收；数字、標點不動
    assert n == 1


class _SameText:
    def convert(self, s):
        return s


class _GrowsWhenJoined:
    def convert(self, s):
        return s + "x" if "\n" in s else s      # 接起來的全文長度變了 → 要退回逐行


def _csc_with_fake_model(t2s, seen):
    import csc_corrector as cc

    def predict(piece):
        seen.append(piece)
        offsets = [(i, i + 1) for i, ch in enumerate(piece) if not ch.isspace()]
        preds = [("程" if piece[s] == "成" and s > 0 and piece[s - 1] == "行" else piece[s], 0.9) for s, _ in offsets]
        return offsets, preds

    c = object.__new__(cc.CscCorrector)
    c._t2s, c._s2t, c._predict = t2s, _SameText(), predict
    return c


def test_csc_correct_runs_windows_across_lines_without_labels(monkeypatch):
    import csc_corrector as cc
    monkeypatch.setattr(cc, "WINDOW_CHARS", 8)
    text = "說話人1：今天的行成\n說話人2：行成4天\n沒有標籤的行成"
    want = "說話人1：今天的行程\n說話人2：行程4天\n沒有標籤的行程"
    seen = []
    assert _csc_with_fake_model(_SameText(), seen).correct(text) == want
    assert seen == ["今天的行成\n行成", "4天\n沒有標籤的", "行成"]     # 視窗跨行、標籤不送模型
    assert _csc_with_fake_model(_SameText(), []).correct(text, should_stop=lambda: True) is None
    seen = []
    assert _csc_with_fake_model(_GrowsWhenJoined(), seen).correct(text) == want
    assert seen == ["今天的行成", "行成4天", "沒有標籤的行成"]           # 長度對不上就逐行


class _FakeCsc:
    def __init__(self, *args, **kwargs):
        pass

    def correct(self, text, should_stop=None):
        if should_stop is not None and should_stop():
            return None
        return text.replace("行成", "行程").replace("確認", "確定")


def test_polish_fix_with_csc_engine_keeps_only_homophones(monkeypatch):
    import csc_corrector as cc
    monkeypatch.setattr(tp, "FIX_ENGINE", "csc")
    monkeypatch.setattr(cc, "CscCorrector", _FakeCsc)
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: pytest.fail("LLM 不該被呼叫")))
    res = _run(tp.polish_transcript("說話人1：行成4天，請協理確認。", "fix", source="refine"))
    assert res["polished"] == "說話人1：行程4天，請協理確認。"   # 認→定 不同音，同音過濾擋下
    assert res["backend"] == cc.LABEL
    assert res["accepted_edits"] == 1 and res["rejected_edits"] == 1


def test_polish_fix_with_csc_engine_stops_when_recording_starts(monkeypatch):
    import csc_corrector as cc
    monkeypatch.setattr(tp, "FIX_ENGINE", "csc")
    monkeypatch.setattr(cc, "CscCorrector", _FakeCsc)
    res = _run(tp.polish_transcript("行成4天", "fix", should_stop=lambda: True))
    assert res["stopped"] is True and res["polished"] == "行成4天"


def test_polish_fix_engine_can_be_chosen_per_call(monkeypatch):
    import csc_corrector as cc
    monkeypatch.setattr(cc, "CscCorrector", _FakeCsc)
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of, seen))
    monkeypatch.setattr(tp, "FIX_ENGINE", "llm")
    res = _run(tp.polish_transcript("行成4天", "fix", engine="csc"))       # 預設 llm，這次選 csc
    assert res["engine"] == "csc" and res["backend"] == cc.LABEL and not seen
    monkeypatch.setattr(tp, "FIX_ENGINE", "csc")
    res = _run(tp.polish_transcript("行成4天", "fix", engine="llm"))       # 預設 csc，這次選 llm
    assert res["engine"] == "llm" and len(seen) == 1
    res = _run(tp.polish_transcript("一" * 100, "rewrite", engine="csc"))  # rewrite 不看 engine
    assert res["engine"] is None


def _pre_csc_on(monkeypatch, available=True):
    import csc_corrector as cc
    monkeypatch.setattr(tp, "PRE_CSC", True)
    monkeypatch.setattr(cc, "CscCorrector", _FakeCsc)
    monkeypatch.setattr(cc, "unavailable_reason", lambda model_dir=None: None if available else "缺少模型檔 model.onnx")


def test_rewrite_runs_macbert_first_when_available(monkeypatch):
    _pre_csc_on(monkeypatch)
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of, seen))     # rewrite 照抄送進來的文字
    res = _run(tp.polish_transcript("說話人1：行成4天，請協理確認。", "rewrite", source="refine"))
    assert "行程4天" in _chunk_of(seen[0]["prompt"])                       # rewrite 拿到的是 MacBERT 修過的
    assert res["polished"] == "說話人1：行程4天，請協理確認。"               # 確認→確定 不同音，沒收
    assert res["pre_fix_engine"] == "csc" and res["pre_fix_edits"] == 1
    assert res["backend"] == _FakeBackend.label and res["diff_counts"]["rep"] == 1   # 標色對原文，含 MacBERT 的修改


def test_rewrite_skips_macbert_when_unavailable_or_switched_off(monkeypatch):
    _pre_csc_on(monkeypatch, available=False)
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of, seen))
    res = _run(tp.polish_transcript("行成4天，請協理確認。", "rewrite"))
    assert "行成4天" in _chunk_of(seen[0]["prompt"]) and res["pre_fix_engine"] is None and res["pre_fix_edits"] == 0
    _pre_csc_on(monkeypatch)
    monkeypatch.setattr(tp, "PRE_CSC", False)
    res = _run(tp.polish_transcript("行成4天，請協理確認。", "rewrite"))
    assert res["pre_fix_engine"] is None and res["polished"] == "行成4天，請協理確認。"


def test_rewrite_failure_keeps_macbert_fix(monkeypatch):
    _pre_csc_on(monkeypatch)

    def boom(prompt):
        raise LLMError("hailo down")

    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(boom))
    res = _run(tp.polish_transcript("行成4天，請協理確認。", "rewrite"))
    assert res["failed_chunks"] == 1 and res["polished"] == "行程4天，請協理確認。"


def test_llm_fix_runs_macbert_first_but_csc_engine_does_not_double_run(monkeypatch):
    _pre_csc_on(monkeypatch)
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of, seen))     # LLM 照抄送進來的文字
    res = _run(tp.polish_transcript("說話人1：行成4天，請協理確認。", "fix", source="refine", engine="llm"))
    assert "行程4天" in _chunk_of(seen[0]["prompt"])                       # LLM 拿到的是 MacBERT 修過的
    assert res["polished"] == "說話人1：行程4天，請協理確認。" and res["engine"] == "llm"
    assert res["pre_fix_engine"] == "csc" and res["pre_fix_edits"] == 1 and res["diff_counts"]["rep"] == 1
    res = _run(tp.polish_transcript("行成4天，請協理確認。", "fix", engine="csc"))
    assert res["pre_fix_engine"] is None and res["accepted_edits"] == 1     # 選 MacBERT 引擎就只跑一次


def test_rewrite_with_macbert_stops_when_recording_starts(monkeypatch):
    _pre_csc_on(monkeypatch)
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: pytest.fail("錄音中不該呼叫 LLM")))
    res = _run(tp.polish_transcript("行成4天", "rewrite", should_stop=lambda: True))
    assert res["stopped"] is True and res["polished"] == "行成4天"


def test_parse_glossary_splits_dedups_and_keeps_only_chinese_terms():
    raw = "李協理、宏遠科技，韌體\n韌體; 新版 ERP / 甲 / A1區 /楊工程師"
    assert tp.parse_glossary(raw) == ["李協理", "宏遠科技", "韌體", "新版", "楊工程師"]   # 「ERP」「甲」「A1區」不收
    assert tp.parse_glossary(["工安", " 課長 ", "工安"]) == ["工安", "課長"]
    assert tp.parse_glossary(None) == [] and len(tp.parse_glossary("、".join("甲乙" + chr(0x4e00 + i) for i in range(400)))) == 300


def test_apply_glossary_fixes_homophones_of_terms_only():
    terms = ["韌體", "楊工程師", "課長", "工程師"]
    text = "說話人1：任體更新請羊工程師處理，劉科長負責。\n說話人2：韌體沒問題，工程師也到了。"
    out, n = tp.apply_glossary(text, terms, tp.protected_spans(text))
    assert out == "說話人1：韌體更新請楊工程師處理，劉課長負責。\n說話人2：韌體沒問題，工程師也到了。"
    assert n == 3
    assert tp.apply_glossary("請陽工程師", ["楊工程師", "陽工程師"]) == ("請陽工程師", 0)   # 兩個詞彙同音：不互換
    assert tp.apply_glossary("任體", []) == ("任體", 0)
    assert tp.apply_glossary("重新", ["蟲新"])[0] == "蟲新"     # 原文的字有破音（重：zhong／chong）也算同音
    assert tp.apply_glossary("任題、議體", ["韌體", "議題"])[0] == "韌體、議題"   # 不計聲調（題 tí／體 tǐ 都算 ti）
    assert tp.apply_glossary("任務完成", ["韌體"]) == ("任務完成", 0)          # 不同音不改


def test_polish_applies_glossary_before_macbert_and_llm(monkeypatch):
    _pre_csc_on(monkeypatch)
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(_chunk_of, seen))
    res = _run(tp.polish_transcript("說話人1：任體行成4天，請協理確認。", "fix", source="refine", engine="llm",
                                    glossary=["韌體", "說話"]))
    assert "韌體行程4天" in _chunk_of(seen[0]["prompt"])             # LLM 拿到的是詞彙＋MacBERT 修過的
    assert res["polished"] == "說話人1：韌體行程4天，請協理確認。"     # 標籤「說話人1：」不被詞彙「說話」動到
    assert res["glossary_terms"] == 2 and res["glossary_edits"] == 1 and res["diff_counts"]["rep"] == 2
    res = _run(tp.polish_transcript("任體更新", "fix", engine="csc", glossary=["韌體"]))
    assert res["polished"] == "韌體更新" and res["glossary_edits"] == 1


def test_polish_rejects_unknown_fix_engine():
    with pytest.raises(ValueError):
        _run(tp.polish_transcript("abc", "fix", engine="gpt"))


def test_csc_unavailable_reason_reports_missing_model(monkeypatch, tmp_path):
    import importlib.util
    import csc_corrector as cc
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())   # 假裝套件都在
    assert "model.onnx" in cc.unavailable_reason(str(tmp_path))
    (tmp_path / "model.onnx").write_bytes(b"x")
    (tmp_path / "tokenizer.json").write_text("{}")
    assert cc.unavailable_reason(str(tmp_path)) is None


def test_output_timeout_grows_with_output_budget(monkeypatch):
    seen = []
    monkeypatch.setattr(tp, "aiter_chat_stream", _stream(lambda p: "二" * 500, seen))
    _run(tp.polish_transcript("一" * 590, "rewrite"))
    assert seen[0]["num_predict"] == 1180
    assert seen[0]["timeout"] >= 1180 / 4.5


def test_diff_segments_marks_replacement_insertion_and_deletion():
    segs = tp.diff_segments("請李協里確認期", "請李協理確認日期")
    assert segs == [["eq", "請李協", ""], ["rep", "理", "里"], ["eq", "確認", ""], ["ins", "日", ""], ["eq", "期", ""]]
    assert tp.diff_segments("好的好的，開始", "好的，開始") == [["del", "好的", ""], ["eq", "好的，開始", ""]]
    # 去掉 del 後接起來就是新文字
    src, dst = "第一個議題是公安", "第一個議題是工安。"
    assert "".join(t for op, t, _ in tp.diff_segments(src, dst) if op != "del") == dst
