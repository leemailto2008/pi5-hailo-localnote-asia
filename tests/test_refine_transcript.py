# -*- coding: utf-8 -*-
import refine_transcript as rt
from refine_transcript import Sentence


def test_assign_speakers_uses_longest_overlap_and_nearest_gap():
    sentences = [Sentence(0.0, 4.0, "甲"), Sentence(4.0, 6.0, "乙"), Sentence(10.2, 11.0, "丙"), Sentence(30.0, 31.0, "丁")]
    turns = [(0.0, 1.0, 5), (1.0, 4.5, 7), (4.5, 10.0, 5)]
    rt.assign_speakers(sentences, turns)
    # 甲：7 重疊 3 s > 5 重疊 1 s；乙：5 重疊 1.5 s > 7 重疊 0.5 s；丙：在空隙，0.2 s 內最近的是 5；丁：太遠 → None
    assert [s.speaker for s in sentences] == [7, 5, 5, None]


def test_format_transcript_numbers_speakers_by_first_appearance_and_merges_runs():
    sentences = [Sentence(0, 1, "好，我們開始。", 7), Sentence(1, 2, "第一個議題是公安", 7),
                 Sentence(2, 3, "收到。", 3), Sentence(3, 4, "繼續", 7)]
    text, speakers = rt.format_transcript(sentences)
    assert speakers == 2
    assert text == "說話人1：好，我們開始，第一個議題是公安\n說話人2：收到。\n說話人1：繼續"


def test_format_transcript_without_speakers_is_plain_text():
    text, speakers = rt.format_transcript([Sentence(0, 1, "第一句"), Sentence(1, 2, "第二句。"), Sentence(2, 3, "第三句")])
    assert speakers == 0
    assert text == "第一句，第二句，第三句"


def test_check_available_reports_missing_models(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "MODEL_DIR", str(tmp_path))
    reason = rt.check_available()
    assert reason is not None
    assert ("sherpa-onnx" in reason) or ("sensevoice_small_int8.onnx" in reason)


def test_refine_raises_clear_error_when_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(rt, "MODEL_DIR", str(tmp_path))
    try:
        rt.refine(str(tmp_path / "x.ogg"))
    except rt.RefineError as e:
        assert str(e)
    else:
        raise AssertionError("expected RefineError")


import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402


def _child(script):
    return [sys.executable, "-c", script]


_EMIT = "import json, sys, time; sys.stdout.reconfigure(encoding='utf-8')\ndef emit(o):\n    print(json.dumps(o, ensure_ascii=False), flush=True)\n"


def test_run_in_subprocess_relays_progress_and_returns_result():
    seen = []
    script = _EMIT + "emit({'progress': ['asr', 0.5]})\nemit({'partial': {'transcript': '甲'}})\nemit({'result': {'transcript': '說話人1：甲', 'speakers': 1}})\n"
    res = asyncio.run(rt.run_in_subprocess("x.ogg", on_progress=lambda p, f: seen.append((p, f)), cmd=_child(script)))
    assert res == {"transcript": "說話人1：甲", "speakers": 1}
    assert seen == [("asr", 0.5)]


def test_run_in_subprocess_stops_child_and_returns_partial(monkeypatch):
    monkeypatch.setattr(rt, "STOP_POLL_S", 0.05)
    # 子行程在 partial 之後送一行 progress；看到 progress 才要求停止，partial 一定已讀到。
    # （原本第 3 次輪詢就停，Windows 上子行程 0.15 s 內還沒啟動完，partial 是空的，偶發失敗。）
    script = _EMIT + ("emit({'partial': {'transcript': '還沒分人', 'speakers': 0}})\nemit({'progress': ['diarize', 0.0]})\n"
                      "time.sleep(30)\nemit({'result': {}})\n")
    seen = []

    def should_stop():
        return bool(seen)

    res = asyncio.run(asyncio.wait_for(rt.run_in_subprocess(
        "x.ogg", should_stop=should_stop, on_progress=lambda p, f: seen.append(p), cmd=_child(script)), 10))
    assert seen == ["diarize"]
    assert res["stopped"] is True and res["transcript"] == "還沒分人"


def test_run_in_subprocess_reports_child_error_message():
    script = _EMIT + "emit({'error': '缺少模型檔'})\nsys.exit(1)\n"
    try:
        asyncio.run(rt.run_in_subprocess("x.ogg", cmd=_child(script)))
    except rt.RefineError as e:
        assert str(e) == "缺少模型檔"
    else:
        raise AssertionError("expected RefineError")


def test_run_in_subprocess_reports_crash_with_stderr_tail():
    script = "import sys\nsys.stderr.write('Segmentation fault\\n')\nsys.exit(3)\n"
    try:
        asyncio.run(rt.run_in_subprocess("x.ogg", cmd=_child(script)))
    except rt.RefineError as e:
        assert "exit 3" in str(e) and "Segmentation fault" in str(e)
    else:
        raise AssertionError("expected RefineError")


def test_cli_emits_error_line_when_unavailable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rt, "MODEL_DIR", str(tmp_path))
    assert rt._cli(["refine_transcript", str(tmp_path / "x.ogg")]) == 1
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert "error" in json.loads(last)


def test_merge_short_pause_turns_sentence_period_into_comma():
    sentences = [Sentence(0.0, 3.0, "不良率從5%。", 1), Sentence(3.2, 5.0, "降到1%。", 1)]
    text, _ = rt.format_transcript(sentences)
    assert text == "說話人1：不良率從5%，降到1%。"


def test_long_pause_keeps_sentence_period():
    sentences = [Sentence(0.0, 3.0, "第一件事。", 1), Sentence(3.0 + rt.MERGE_GAP_S + 0.3, 6.0, "第二件事。", 1)]
    text, _ = rt.format_transcript(sentences)
    assert text == "說話人1：第一件事。第二件事。"


def test_question_and_exclamation_are_not_merged():
    sentences = [Sentence(0.0, 1.0, "你好嗎？", 1), Sentence(1.1, 2.0, "好！", 1)]
    text, _ = rt.format_transcript(sentences)
    assert text == "說話人1：你好嗎？好！"


def test_merge_does_not_cross_speakers():
    sentences = [Sentence(0.0, 1.0, "同意。", 1), Sentence(1.1, 2.0, "反對。", 2)]
    text, _ = rt.format_transcript(sentences)
    assert text == "說話人1：同意。\n說話人2：反對。"


def test_english_sentences_are_joined_with_spaces():
    # 11-11：英文會議原本接成「meeting.，We have」。
    sentences = [Sentence(0.0, 2.0, "Okay, let's start today's weekly meeting.", 1),
                 Sentence(2.2, 3.5, "We have a few topics to cover", 1),
                 Sentence(3.6, 5.0, "the first topic is training.", 1)]
    text, _ = rt.format_transcript(sentences)
    assert text == "說話人1：Okay, let's start today's weekly meeting. We have a few topics to cover the first topic is training."


def test_mixed_chinese_after_english_still_uses_fullwidth_comma():
    sentences = [Sentence(0.0, 1.0, "這次 release 延後", 1), Sentence(3.0, 4.0, "QA 下週再測", 1)]
    text, _ = rt.format_transcript(sentences)
    assert text == "說話人1：這次 release 延後，QA 下週再測"


def test_transcribe_passes_auto_language_to_sensevoice(monkeypatch):
    # 11-11：language="zh" 把英文會議辨成亂碼中文；預設改 auto。
    import types

    import pytest

    captured = {}

    class _Stop(Exception):
        pass

    def from_sense_voice(**kwargs):
        captured.update(kwargs)
        raise _Stop()

    fake = types.SimpleNamespace(OfflineRecognizer=types.SimpleNamespace(from_sense_voice=from_sense_voice))
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    with pytest.raises(_Stop):
        rt.transcribe([])
    assert rt.ASR_LANGUAGE == "auto"
    assert captured["language"] == "auto"

def _fake_sherpa(monkeypatch):
    """假的 sherpa_onnx：嵌入 = 該句第一個樣本值；分群 = 嵌入第一維取整。"""
    import types

    import numpy as np

    class Stream:
        def accept_waveform(self, sr, x):
            self.x = np.asarray(x)

        def input_finished(self):
            pass

    class Extractor:
        def __init__(self, config):
            pass

        def create_stream(self):
            return Stream()

        def compute(self, stream):
            return [float(stream.x[0]), 0.0]

    class Config:
        def __init__(self, **kw):
            pass

        def validate(self):
            return True

    class Clustering:
        def __init__(self, config):
            pass

        def __call__(self, feats):
            return [int(round(f[0])) for f in feats]

    fake = types.SimpleNamespace(SpeakerEmbeddingExtractorConfig=Config, SpeakerEmbeddingExtractor=Extractor,
                                 FastClusteringConfig=lambda **kw: kw, FastClustering=Clustering)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)


def _samples(spans, seconds=4):
    import numpy as np
    x = np.zeros(seconds * rt.SAMPLE_RATE, dtype=np.float32)
    for start, end, value in spans:
        x[int(start * rt.SAMPLE_RATE):int(end * rt.SAMPLE_RATE)] = value
    return x


def test_diarize_sentences_clusters_long_sentences_and_short_ones_borrow_nearest(monkeypatch):
    _fake_sherpa(monkeypatch)
    x = _samples([(0.0, 1.0, 0.0), (1.1, 1.3, 1.0), (2.0, 3.0, 1.0)])
    sents = [Sentence(0.0, 1.0, "甲說"), Sentence(1.1, 1.3, "好"), Sentence(2.0, 3.0, "乙說")]
    assert rt.diarize_sentences(x, sents) is True
    # 「好」只有 0.2 s，不算嵌入，借時間上最近的長句（甲）
    assert [s.speaker for s in sents] == [0, 0, 1]


def test_diarize_sentences_stop_leaves_speakers_empty(monkeypatch):
    _fake_sherpa(monkeypatch)
    x = _samples([(0.0, 1.0, 0.0)])
    sents = [Sentence(0.0, 1.0, "甲說")]
    assert rt.diarize_sentences(x, sents, should_stop=lambda: True) is False
    assert sents[0].speaker is None


def test_diarize_sentences_all_short_is_one_speaker(monkeypatch):
    _fake_sherpa(monkeypatch)
    sents = [Sentence(0.0, 0.3, "好"), Sentence(1.0, 1.2, "對")]
    assert rt.diarize_sentences(_samples([]), sents) is True
    assert [s.speaker for s in sents] == [0, 0]

def test_merge_close_clusters_joins_split_speaker_but_keeps_distinct_ones():
    # 群 0 與 1 中心幾乎同方向（同一人被拆開），群 2 方向不同
    emb = [[1.0, 0.0, 0.0], [0.98, 0.2, 0.0], [0.97, 0.1, 0.1], [0.0, 1.0, 0.0], [0.1, 0.99, 0.0]]
    labels = [0, 0, 1, 2, 2]
    assert rt.merge_close_clusters(labels, emb, 0.8) == [0, 0, 0, 2, 2]


def test_merge_close_clusters_leaves_dissimilar_and_single_cluster_alone():
    emb = [[1.0, 0.0], [0.0, 1.0]]
    assert rt.merge_close_clusters([0, 1], emb, 0.8) == [0, 1]
    assert rt.merge_close_clusters([3, 3], emb, 0.8) == [3, 3]

def test_split_at_pauses_cuts_at_token_nearest_the_pause():
    tokens = list("好我們開始") + ["，"] + list("請報告")
    times = [0.0, 0.3, 0.45, 0.6, 0.75, 0.9, 2.0, 2.15, 2.3]
    pieces = rt.split_at_pauses(0.0, 2.6, tokens, times, [1.5])
    # 最近的 token 起點是「請」(2.0)；切點取「，」(0.9) 與「請」的中點
    assert [(round(a, 2), round(b, 2), t) for a, b, t in pieces] == [(0.0, 1.45, "好我們開始，"), (1.45, 2.6, "請報告")]


def test_split_at_pauses_skips_cuts_near_edges_or_far_from_tokens():
    tokens, times = list("我們開始"), [0.0, 0.2, 0.4, 0.6]
    assert rt.split_at_pauses(0.0, 0.65, tokens, times, [0.6]) == [(0.0, 0.65, "我們開始")]    # 切點 0.5 離句尾不到 0.2 s
    assert rt.split_at_pauses(0.0, 5.0, tokens, times, [3.0]) == [(0.0, 5.0, "我們開始")]      # 附近沒有 token
    assert rt.split_at_pauses(0.0, 5.0, tokens, times[:3], [0.3]) == [(0.0, 5.0, "我們開始")]  # 數量不符


def test_split_at_pauses_merges_punctuation_only_piece_back():
    tokens, times = ["好", "的", "。"], [0.0, 0.3, 1.5]
    assert rt.split_at_pauses(0.0, 2.0, tokens, times, [1.2]) == [(0.0, 2.0, "好的。")]


def test_continuation_pieces_join_without_extra_comma():
    sentences = [Sentence(0.0, 1.4, "上線前先在100台設備上", 1), Sentence(1.4, 3.0, "試跑3天。", 1, cont=True),
                 Sentence(3.1, 4.0, "好", 2, cont=True), Sentence(4.0, 5.0, "沒問題。", 2, cont=True)]
    text, speakers = rt.format_transcript(sentences)
    assert text == "說話人1：上線前先在100台設備上試跑3天。\n說話人2：好沒問題。"
    assert speakers == 2


def test_continuation_english_pieces_keep_word_spacing():
    sentences = [Sentence(0.0, 1.0, "Okay,", 1), Sentence(1.0, 2.0, "let's start", 1, cont=True)]
    assert rt.format_transcript(sentences)[0] == "說話人1：Okay, let's start"

def test_window_runs_needs_two_consecutive_windows():
    assert rt.window_runs([0, 0, 1, 1, 1, 0], 0) == [(2, 1)]
    assert rt.window_runs([0, 1, 0, 0], 0) == []
    assert rt.window_runs([1, 1, 2, 2], 0) == [(0, 1), (2, 2)]


def test_split_by_windows_cuts_long_sentence_at_speaker_change():
    import numpy as np

    class Stream:
        def accept_waveform(self, sr, x):
            self.x = np.asarray(x)

        def input_finished(self):
            pass

    class Extractor:
        def create_stream(self):
            return Stream()

        def compute(self, stream):
            return [1.0, 0.0] if stream.x[0] < 0.5 else [0.0, 1.0]

    x = np.zeros(7 * rt.SAMPLE_RATE, dtype=np.float32)
    x[int(3.0 * rt.SAMPLE_RATE):int(6.0 * rt.SAMPLE_RATE)] = 1.0
    tokens = list("甲方先報告了乙方來補充")
    times = [i * 0.5 for i in range(len(tokens))]
    s = Sentence(0.0, 6.0, "".join(tokens), speaker=0, tokens=tokens, times=times)
    out = rt.split_by_windows(x, [s], Extractor(), {0: np.array([1.0, 0.0]), 1: np.array([0.0, 1.0])})
    assert [(o.speaker, o.cont, o.text) for o in out] == [(0, False, "甲方先報告了乙"), (1, True, "方來補充")]
    assert out[0].end == out[1].start


def test_split_by_windows_leaves_short_or_tokenless_sentences():
    import numpy as np
    s1 = Sentence(0.0, 2.0, "短句", speaker=0, tokens=["短", "句"], times=[0.0, 1.0])
    s2 = Sentence(2.0, 8.0, "沒有token", speaker=1)
    out = rt.split_by_windows(_samples([]), [s1, s2], None, {0: np.array([1.0, 0.0]), 1: np.array([0.0, 1.0])})
    assert out == [s1, s2]

def test_short_piece_borrows_from_its_own_vad_sentence_first(monkeypatch):
    _fake_sherpa(monkeypatch)
    monkeypatch.setattr(rt, "CLUSTER_MIN_UNITS", 1)   # 這裡甲只有一個單位；測的是短尾巴借同句，不是單位數門檻
    # 乙說完（0.0–1.3），甲的句子 1.3–2.8（長片段）＋短尾巴 3.2–3.5（cont）；尾巴時間上離乙的下一句 3.55–4.9 更近
    x = _samples([(0.0, 1.3, 1.0), (1.3, 2.8, 0.0), (3.2, 3.5, 2.0), (3.55, 4.9, 1.0)], seconds=6)
    sents = [Sentence(0.0, 1.3, "乙說"), Sentence(1.3, 2.8, "甲說"), Sentence(3.2, 3.5, "完", cont=True),
             Sentence(3.55, 4.9, "乙又說")]
    assert rt.diarize_sentences(x, sents) is True
    assert [s.speaker for s in sents] == [1, 0, 0, 1]


def test_split_piece_shorter_than_piece_min_borrows_instead_of_own_embedding(monkeypatch):
    _fake_sherpa(monkeypatch)
    # 甲的句子切成 0.0–1.6（長）與 1.6–2.65（1.05 s，< PIECE_MIN_EMBED_S）；後段若自己算嵌入會分到乙（值 1.0）
    x = _samples([(0.0, 1.6, 0.0), (1.6, 2.65, 1.0), (3.0, 4.3, 1.0)], seconds=6)
    sents = [Sentence(0.0, 1.6, "甲說"), Sentence(1.6, 2.65, "週五回報", cont=True), Sentence(3.0, 4.3, "乙說")]
    units, groups = rt.embedding_units(sents)
    assert [(a, b, idx) for a, b, idx in units] == [(0.0, 1.6, [0]), (3.0, 4.3, [2])]
    assert groups == [0, 0, 1]
    assert rt.diarize_sentences(x, sents) is True
    assert [s.speaker for s in sents] == [0, 0, 1]


def test_split_sentence_without_long_piece_is_embedded_as_a_whole(monkeypatch):
    _fake_sherpa(monkeypatch)
    # 甲的句子切成三段都短（共 1.5 s），整句當一個單位；後面的短句「名額」借它，不借時間上較遠的乙
    # 「名額」中點 2.0：整句單位中點 0.75（差 1.25），乙中點 3.55（差 1.55）；若整句不算嵌入，最近的單位就只剩乙
    x = _samples([(0.0, 1.5, 0.0), (2.9, 4.2, 1.0)], seconds=6)
    sents = [Sentence(0.0, 0.5, "3月8日"), Sentence(0.5, 1.0, "有一場", cont=True), Sentence(1.0, 1.5, "課程", cont=True),
             Sentence(1.6, 2.4, "名額"), Sentence(2.9, 4.2, "乙說")]
    units, _ = rt.embedding_units(sents)
    assert [(a, b, idx) for a, b, idx in units] == [(0.0, 1.5, [0, 1, 2]), (2.9, 4.2, [4])]
    assert rt.diarize_sentences(x, sents) is True
    assert [s.speaker for s in sents] == [0, 0, 0, 0, 1]

def test_cluster_of_only_short_units_is_not_a_speaker(monkeypatch):
    _fake_sherpa(monkeypatch)
    # 甲 0.0–1.6、乙 2.7–4.0 都夠長；中間 1.0 s 的「週五回報」自己分成一群（嵌入方向跟兩人都不同），
    # 那群最長單位 < CLUSTER_MIN_LONGEST_S，不算一個人，改借時間上最近的單位（乙）
    x = _samples([(0.0, 1.6, 0.0), (1.7, 2.7, 1.0), (2.7, 4.0, -1.0)])
    sents = [Sentence(0.0, 1.6, "甲說"), Sentence(1.7, 2.7, "週五回報"), Sentence(2.7, 4.0, "乙說")]
    assert rt.diarize_sentences(x, sents) is True
    assert [s.speaker for s in sents] == [0, -1, -1]

def test_pause_slices_cover_audio_and_respect_bounds():
    import numpy as np
    sr = rt.SAMPLE_RATE
    x = np.random.default_rng(0).normal(0, 0.1, 47 * sr).astype(np.float32)
    x[int(6.0 * sr):int(6.3 * sr)] = 0.0          # 一段停頓：第一刀應落在這裡
    sl = rt.pause_slices(x)
    assert sl[0][0] == 0 and sl[-1][1] == len(x)
    assert all(a[1] == b[0] for a, b in zip(sl, sl[1:]))                      # 連續、不重疊
    assert all((e - s) <= rt.ASR_SLICE_MAX_S * sr + 1 for s, e in sl)
    assert all((e - s) >= rt.ASR_SLICE_MIN_S * sr for s, e in sl[:-1])
    assert 6.0 * sr <= sl[0][1] <= 6.3 * sr
    assert rt.pause_slices(x[:3 * sr]) == [(0, 3 * sr)]


def test_assign_tokens_by_time_and_gap_goes_to_nearer_sentence():
    regions = [(0.0, 2.0), (3.0, 5.0)]
    toks = ["第", "一", "句", "停", "第", "二"]
    times = [0.1, 0.5, 1.9, 2.2, 3.1, 4.9]       # 2.2 落在兩句之間、離前句較近
    out = rt.assign_tokens(regions, toks, times)
    assert out[0] == (["第", "一", "句", "停"], [0.1, 0.5, 1.9, 2.2])
    assert out[1] == (["第", "二"], [3.1, 4.9])
    out = rt.assign_tokens(regions, ["前", "後"], [-0.5, 2.8])   # 第一句之前歸第一句；2.8 離後句較近
    assert out == [(["前"], [-0.5]), (["後"], [2.8])]
    assert rt.assign_tokens([], ["字"], [1.0]) == []


def test_assign_tokens_keeps_punctuation_with_previous_word():
    """2026-11-14：句尾「。」時間落在停頓裡、離下一句較近 → 原本分到下一句，高精度稿出現「…討論，。第一個」與行首「。」。"""
    regions = [(0.0, 2.0), (3.0, 5.0)]
    out = rt.assign_tokens(regions, ["討", "論", "。", "第", "一", "，", "個"], [0.5, 1.6, 2.8, 3.1, 3.4, 3.6, 3.8])
    assert out[0][0] == ["討", "論", "。"]
    assert out[1][0] == ["第", "一", "，", "個"]
    out = rt.assign_tokens(regions, ["。", "好"], [0.1, 0.4])   # 第一個字就是標點：照時間
    assert out[0][0] == ["。", "好"]
    # 上一片結尾「。」＋下一片開頭「，」（藍牙 10 分「財務部。，」）：連續標點只留一個、句末優先
    out = rt.assign_tokens(regions, ["部", "。", "，", "第"], [1.5, 1.8, 2.9, 3.1])
    assert out[0][0] == ["部", "。"] and out[1][0] == ["第"]
    out = rt.assign_tokens(regions, ["部", "，", "。", "第"], [1.5, 1.8, 2.9, 3.1])
    assert out[0] == (["部", "。"], [1.5, 2.9])
    # % 不是句讀：「良率是85%。」不能變「良率是85。」（c42dd09 第一版 A/B 抓到：5 分事實召回 0.925 → 0.866）
    out = rt.assign_tokens(regions, ["85", "%", "。", "第"], [1.5, 1.7, 2.9, 3.1])
    assert out[0][0] == ["85", "%", "。"]


def test_cluster_with_a_single_unit_is_not_a_speaker(monkeypatch):
    _fake_sherpa(monkeypatch)
    # 甲、乙各兩段；中間一段 1.3 s 的嵌入自成一群（只有 1 個單位）→ 不算一個人，借時間上最近的單位
    x = _samples([(0.0, 1.5, 0.0), (1.6, 3.1, 0.0), (3.2, 4.5, -1.0), (4.6, 6.1, 1.0), (6.2, 7.7, 1.0)], seconds=8)
    sents = [Sentence(0.0, 1.5, "甲一"), Sentence(1.6, 3.1, "甲二"), Sentence(3.2, 4.5, "外殼刮傷"),
             Sentence(4.6, 6.1, "乙一"), Sentence(6.2, 7.7, "乙二")]
    assert rt.diarize_sentences(x, sents) is True
    spk = [s.speaker for s in sents]
    assert len(set(spk)) == 2 and spk[0] == spk[1] and spk[3] == spk[4] and spk[2] in (spk[1], spk[3])
    monkeypatch.setattr(rt, "CLUSTER_MIN_UNITS", 1)                   # 原行為：自成第 3 人
    sents = [Sentence(s.start, s.end, s.text) for s in sents]
    assert rt.diarize_sentences(x, sents) is True
    assert len({s.speaker for s in sents}) == 3


def test_token_span_pads_and_stays_inside_slice():
    import pytest
    assert rt.token_span([4.5, 5.0, 5.2], 4.0, 9.5) == pytest.approx((4.4, 5.6))
    assert rt.token_span([0.05, 9.4], 0.0, 9.5) == pytest.approx((0.0, 9.5))
    assert rt.token_span([], 0.0, 1.0) is None


def test_add_missed_regions_only_fills_gaps_vad_did_not_cover():
    regions = [(1.0, 3.0), (10.0, 12.0)]
    spans = [(2.5, 5.0), (5.5, 8.0), (11.0, 11.5)]       # 第 1、3 個跟 VAD 句子重疊：不補
    assert rt.add_missed_regions(regions, spans) == [(1.0, 3.0), (5.5, 8.0), (10.0, 12.0)]
    assert rt.add_missed_regions([], [(4.0, 6.0), (0.5, 2.0)]) == [(0.5, 2.0), (4.0, 6.0)]
    assert rt.add_missed_regions(regions, []) == regions


def _fake_sherpa_asr(monkeypatch):
    """假的 sherpa_onnx：VAD 一句都抓不到（小聲錄音）；辨識：有聲音的片回「你好。」，沒聲音的片回底噪「그.」。"""
    import types

    import numpy as np

    class Vad:
        def __init__(self, cfg, buffer_size_in_seconds=0):
            pass

        def accept_waveform(self, x):
            pass

        def empty(self):
            return True

        def flush(self):
            pass

    class Stream:
        def accept_waveform(self, sr, x):
            self.x = np.asarray(x)

    class Rec:
        def create_stream(self):
            return Stream()

        def decode_stream(self, st):
            if np.max(np.abs(st.x)) > 0.001:
                st.result = types.SimpleNamespace(text="你好。", tokens=["你", "好", "。"], timestamps=[0.5, 0.8, 1.0],
                                                  lang="<|zh|>", emotion="<|NEUTRAL|>")
            else:
                st.result = types.SimpleNamespace(text="그.", tokens=["그", "."], timestamps=[0.2, 0.3],
                                                  lang="<|ko|>", emotion="<|EMO_UNKNOWN|>")

    def vad_config():
        return types.SimpleNamespace(silero_vad=types.SimpleNamespace(window_size=512), sample_rate=0, num_threads=0)

    fake = types.SimpleNamespace(OfflineRecognizer=types.SimpleNamespace(from_sense_voice=lambda **kw: Rec()),
                                 VadModelConfig=vad_config, VoiceActivityDetector=Vad)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)


def test_transcribe_keeps_recognized_text_when_vad_finds_nothing(monkeypatch):
    """2026-11-14 GS3 小聲實錄：Silero VAD 0 句，舊版字全部分不回句子 → 高精度稿整份空白。"""
    import numpy as np
    _fake_sherpa_asr(monkeypatch)
    monkeypatch.setattr(rt, "ASR_SEGMENTATION", "pause")
    sr = rt.SAMPLE_RATE
    t = np.arange(sr * 8) / sr
    speech = (0.01 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    samples = np.concatenate([speech, np.zeros(sr * 8, dtype=np.float32), speech])
    sentences = rt.transcribe(samples)
    assert sentences, "VAD 沒抓到句子時，辨識出的字不能整份丟掉"
    assert all("你好" in s.text for s in sentences)
    assert not any("그" in s.text for s in sentences)       # 底噪片不自成一句，也不黏到最近的句子


def test_transcribe_drops_noise_slices_next_to_real_sentences(monkeypatch):
    """2026-11-14 開頭 2 分鐘沒人講話：13 片底噪「.」原本全部歸到第一句，高精度稿開頭變成「................好，…」。"""
    import types

    import numpy as np
    _fake_sherpa_asr(monkeypatch)
    sr = rt.SAMPLE_RATE

    class Vad:   # 有聲音的地方都抓得到（一般音量）
        def __init__(self, cfg, buffer_size_in_seconds=0):
            self.pos, self.buf, self.out = 0, [], []

        def accept_waveform(self, x):
            self.buf.append((self.pos, np.asarray(x)))
            self.pos += len(x)

        def flush(self):
            start = None
            for p, x in self.buf + [(self.pos, np.zeros(1))]:
                loud = np.max(np.abs(x)) > 0.001
                if loud and start is None:
                    start = p
                elif not loud and start is not None:
                    self.out.append(types.SimpleNamespace(start=start, samples=np.zeros(p - start)))
                    start = None
            self.buf = []

        def empty(self):
            return not self.out

        @property
        def front(self):
            return self.out[0]

        def pop(self):
            self.out.pop(0)

    monkeypatch.setattr(sys.modules["sherpa_onnx"], "VoiceActivityDetector", Vad)
    monkeypatch.setattr(rt, "ASR_SEGMENTATION", "pause")
    t = np.arange(sr * 8) / sr
    speech = (0.01 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    samples = np.concatenate([np.zeros(sr * 40, dtype=np.float32), speech])
    sentences = rt.transcribe(samples)
    assert sentences and all("你好" in s.text for s in sentences)
    assert not any("그" in s.text for s in sentences)


def _is_quiet(x):
    from audio_splice import live_slice_is_quiet
    return live_slice_is_quiet(x)


def test_transcribe_drops_tiny_output_of_quiet_slices_even_if_not_flagged_as_noise(monkeypatch):
    """2026-11-14 背景噪音那場：開頭靜音 14 片裡 1 片吐「그.」卻標 NEUTRAL（躲過 sv_is_noise）→ 高精度稿第一句「그.」。
    靜音片（能量快篩）只吐 ≤ 3 個字 → 當底噪；吐出長句（很小聲的人）照收。"""
    import types

    import numpy as np
    _fake_sherpa_asr(monkeypatch)
    calls = []

    class Rec:
        def create_stream(self):
            return types.SimpleNamespace(accept_waveform=lambda sr, x: calls.append(np.asarray(x)))

        def decode_stream(self, st):
            x = calls[-1]
            peak = np.max(np.abs(x))
            if peak > 0.006:
                st.result = types.SimpleNamespace(text="你好。", tokens=["你", "好", "。"], timestamps=[0.5, 0.8, 1.0],
                                                  lang="<|zh|>", emotion="<|NEUTRAL|>")
            elif peak > 0.0001:   # 很小聲的人（快篩算靜音片）但辨識出一整句
                st.result = types.SimpleNamespace(text="請大家坐好。", tokens=["請", "大", "家", "坐", "好", "。"],
                                                  timestamps=[0.5, 0.7, 0.9, 1.1, 1.3, 1.5],
                                                  lang="<|zh|>", emotion="<|NEUTRAL|>")
            else:   # 靜音也吐字、而且標 NEUTRAL
                st.result = types.SimpleNamespace(text="그.", tokens=["그", "."], timestamps=[0.2, 0.3],
                                                  lang="<|ko|>", emotion="<|NEUTRAL|>")

    monkeypatch.setattr(sys.modules["sherpa_onnx"].OfflineRecognizer, "from_sense_voice", lambda **kw: Rec())
    monkeypatch.setattr(rt, "ASR_SEGMENTATION", "pause")
    sr = rt.SAMPLE_RATE
    t = np.arange(sr * 8) / sr
    speech = (0.01 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    faint = (0.0005 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)   # 峰值 -66 dB、RMS -69 dB：快篩算靜音片
    assert _is_quiet(faint)
    samples = np.concatenate([np.zeros(sr * 30, dtype=np.float32), faint, np.zeros(sr * 8, dtype=np.float32), speech])
    sentences = rt.transcribe(samples)
    text = "".join(s.text for s in sentences)
    assert "你好" in text and "請大家坐好" in text
    assert "그" not in text


def test_isolated_lang_flips_only_single_slice_between_major_language():
    """2026-11-14 藍牙 30 分：254 片裡 1 片人聲被判成韓文（前後都是中文）→ 用主要語言重解；連續兩片以上、中英夾雜不動。"""
    zh, en, ko, ja, yue = "<|zh|>", "<|en|>", "<|ko|>", "<|ja|>", "<|yue|>"
    assert rt.isolated_lang_flips([zh, zh, ko, zh, zh]) == (zh, [2])
    assert rt.isolated_lang_flips([zh, ko, ko, zh, zh]) == (zh, [])      # 連續兩片：真的換語言
    assert rt.isolated_lang_flips([zh, en, zh, yue, zh]) == (zh, [])     # 中英夾雜、粵語不重解
    assert rt.isolated_lang_flips([ko, zh, zh]) == (zh, [])              # 第一片沒有前一片可比
    assert rt.isolated_lang_flips([zh, zh, ja]) == (zh, [])              # 最後一片沒有後一片可比
    assert rt.isolated_lang_flips([ja, ja, ko, ja]) == (ja, [2])         # 日文會議裡單片判成韓文
    assert rt.isolated_lang_flips([zh, "", ko, zh]) == (zh, [])          # 沒有語言標記的鄰片不算主要語言
    assert rt.isolated_lang_flips([]) == ("", [])


def test_transcribe_redecodes_isolated_language_flip_with_major_language(monkeypatch):
    """前後都是中文、中間一片判成韓文亂碼 → 另建指定中文的辨識器重解那一片；沒有這種片時不建第二個辨識器。"""
    import types

    import numpy as np
    _fake_sherpa_asr(monkeypatch)
    created = []

    class Rec:
        def __init__(self, language):
            self.language = language
            created.append(language)

        def create_stream(self):
            st = types.SimpleNamespace()
            st.accept_waveform = lambda sr, x: setattr(st, "x", np.asarray(x))
            return st

        def decode_stream(self, st):
            peak = np.max(np.abs(st.x))
            if peak > 0.015 and self.language == "auto":   # 被判成韓文的那片
                st.result = types.SimpleNamespace(text="연봉責。", tokens=["연", "봉", "責", "。"],
                                                  timestamps=[0.5, 0.7, 0.9, 1.1], lang="<|ko|>", emotion="<|NEUTRAL|>")
            elif peak > 0.015:
                st.result = types.SimpleNamespace(text="楊工程師。", tokens=["楊", "工", "程", "師", "。"],
                                                  timestamps=[0.5, 0.7, 0.9, 1.1, 1.3], lang="<|zh|>",
                                                  emotion="<|NEUTRAL|>")
            elif peak > 0.001:
                st.result = types.SimpleNamespace(text="你好。", tokens=["你", "好", "。"], timestamps=[0.5, 0.8, 1.0],
                                                  lang="<|zh|>", emotion="<|NEUTRAL|>")
            else:
                st.result = types.SimpleNamespace(text="그.", tokens=["그", "."], timestamps=[0.2, 0.3],
                                                  lang="<|ko|>", emotion="<|EMO_UNKNOWN|>")

    monkeypatch.setattr(sys.modules["sherpa_onnx"].OfflineRecognizer, "from_sense_voice",
                        lambda **kw: Rec(kw["language"]))
    monkeypatch.setattr(rt, "ASR_SEGMENTATION", "pause")
    monkeypatch.setattr(rt, "ASR_LANGUAGE", "auto")
    sr = rt.SAMPLE_RATE
    t = np.arange(sr * 3) / sr   # 3 s 一段、中間停 6 s：每段剛好落在同一片
    speech = (0.01 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    loud = (0.02 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    gap = np.zeros(sr * 6, dtype=np.float32)

    text = "".join(s.text for s in rt.transcribe(np.concatenate([speech, gap, loud, gap, speech, gap])))
    assert "楊工程師" in text and "연" not in text and text.count("你好") == 2
    assert created == ["auto", "zh"]

    created.clear()   # 連續兩片都判成韓文：當成真的換語言，不重解、不建第二個辨識器
    text = "".join(s.text for s in rt.transcribe(np.concatenate([speech, gap, loud, gap, loud, gap, speech, gap])))
    assert text.count("연봉") == 2 and created == ["auto"]
