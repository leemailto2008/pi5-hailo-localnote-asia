# -*- coding: utf-8 -*-
"""SenseVoice 不支援的語言改用 Hailo Whisper 的文字 (2026-11-18，sv_lang_guard)。例句取自 .cc_scratch/sv_lang 的實測輸出。"""
import re
import sys
import types

import numpy as np

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import refine_transcript as rt  # noqa: E402
import stt_worker as stw  # noqa: E402
import sv_lang_guard as g  # noqa: E402
import sv_worker as svw  # noqa: E402
import voice_pipeline as vp  # noqa: E402

DE_SV = "Then I' here, Limo on Alice Muley here. skipped about our coffee tea.."
DE_WH = "Then we have here Lemon und alles möglich. Wir gibt aber auch Kaffee."
EN = "We will hold three more interviews next week, led by Linda."
TH_SV = "夾住於仲攞起身嚟就當到便氣啊美婷話睇聽近，系咪啊。"
TH_WH = "กับ ชีวิ 200 ชัไอ่ตร้นกันเป็นไอบ เป็"
VI_WH = "Tiếp thêm sự tụ tin, để toàn nội thi đấu tập trung"


def test_whisper_verdict():
    assert g.whisper_verdict("<|en|>", DE_SV, DE_WH) == "foreign"     # 亂碼和德文沒有共同單字
    assert g.whisper_verdict("<|en|>", EN, EN) == "ok"                # 真英文：兩邊同一句
    assert g.whisper_verdict("<|en|>", "We will hold three more interviews next week.", EN) == "ok"
    assert g.whisper_verdict("<|yue|>", TH_SV, TH_WH) == "foreign"    # 泰文
    assert g.whisper_verdict("<|yue|>", "一聽速度點你趕到鐵路", VI_WH) == "foreign"   # 越南文
    assert g.whisper_verdict("<|yue|>", "我哋今日講下澳洲", "我們今天講一下澳洲的物價") == "ok"   # 真粵語
    assert g.whisper_verdict("<|en|>", "OK.", "OK.") is None          # 太短看不出來
    assert g.whisper_verdict("<|en|>", "The.", "") is None


def test_guard_needs_majority_and_skips_chinese():
    guard = g.ForeignLangGuard(clock=lambda: 0.0)
    assert not guard.should_probe("<|zh|>")                            # 中文會議不叫 Whisper
    assert guard.should_probe("<|en|>")
    assert guard.decide("<|en|>", DE_SV, DE_WH) is None                # 第 1、2 片：還不夠
    assert guard.decide("<|en|>", DE_SV, DE_WH) is None
    assert guard.decide("<|en|>", DE_SV, DE_WH) == "whisper"           # 第 3 片起改用 Whisper
    assert guard.should_probe("<|zh|>")                                 # 判定外語後每片都比對（SenseVoice 標什麼都一樣）
    assert guard.decide("<|en|>", EN, EN) is None                      # 這片是真英文：照用 SenseVoice


def test_guard_single_odd_slice_does_not_switch():
    """台語偶爾被 Whisper 寫成泰文：單片不換。"""
    guard = g.ForeignLangGuard(clock=lambda: 0.0)
    for _ in range(3):
        assert guard.decide("<|yue|>", "我哋今日講下", "我們今天講一下") is None
    assert guard.decide("<|yue|>", TH_SV, TH_WH) is None


def test_guard_probes_less_once_meeting_is_clearly_supported():
    guard = g.ForeignLangGuard(clock=lambda: 0.0)
    for _ in range(8):
        assert guard.should_probe("<|en|>")
        guard.decide("<|en|>", EN, EN)
    probes = [guard.should_probe("<|en|>") for _ in range(8)]
    assert probes == [False, False, False, True] * 2


def test_refine_choices_use_whole_meeting_window():
    foreign = {"sv_lang": "<|en|>", "sv_text": DE_SV, "wtext": DE_WH}
    ok = {"sv_lang": "<|en|>", "sv_text": EN, "wtext": EN}
    # 開頭兩片即時稿還不夠多數 → 高精度稿看得到後面，也換
    assert g.refine_whisper_choices([foreign, foreign, foreign, {}, ok]) == [0, 1, 2]
    assert g.refine_whisper_choices([ok, ok, ok, foreign, ok, ok]) == []   # 單片不換


def test_pseudo_tokens_join_back_to_text():
    toks, times = g.pseudo_tokens(" Wir gibt aber auch ", 1.0, 3.0)
    assert "".join(toks) == " Wir gibt aber auch" and times == [1.0, 1.5, 2.0, 2.5]
    toks, times = g.pseudo_tokens("กับชีวิ", 0.0, 1.0)
    assert "".join(toks) == "กับชีวิ" and len(times) == len(toks)
    assert g.pseudo_tokens("", 0.0, 1.0) == ([], [])


def test_apply_whisper_choices_replaces_and_restores_noise_dropped_slices():
    sr = rt.SAMPLE_RATE
    slices = [(0, 5 * sr), (5 * sr, 10 * sr), (10 * sr, 15 * sr), (15 * sr, 20 * sr)]
    live = [{"src": "sv", "text": DE_SV, "lang": "<|en|>", "wtext": DE_WH, "ts": [0.5, 3.0]} for _ in range(3)]
    live.append({"src": "tail"})
    decoded = [(0, 5 * sr, DE_SV, "<|en|>", [DE_SV], [0.5]), (10 * sr, 15 * sr, DE_SV, "<|en|>", [DE_SV], [0.5]),
               (15 * sr, 20 * sr, "尾巴", "<|zh|>", ["尾巴"], [0.1])]   # 第 2 片 SenseVoice 輸出被當底噪丟掉
    out = rt.apply_whisper_choices(decoded, slices, live)
    assert [d[0] for d in out] == [0, 5 * sr, 10 * sr, 15 * sr]
    assert [d[2] for d in out[:3]] == [DE_WH] * 3 and out[3][2] == "尾巴"
    assert all("".join(d[4]).strip() == d[2] and len(d[4]) == len(d[5]) for d in out)
    assert out[0][5][0] == 0.5 and out[0][5][-1] < 3.4
    # 沒有比對過的會議：原樣
    plain = [{"src": "sv", "text": "好", "lang": "<|zh|>"}] * 3 + [{"src": "tail"}]
    assert rt.apply_whisper_choices(decoded, slices, plain) is decoded


def test_speech_to_text_live_switches_to_whisper_for_unsupported_language(monkeypatch):
    audio = np.zeros(16000, dtype=np.float32)
    sv_res = {"text": DE_SV, "raw_text": DE_SV, "lang": "<|en|>", "emotion": "<|EMO_UNKNOWN|>",
              "tokens": ["Then"], "timestamps": [0.1], "inference_time_ms": 300}
    monkeypatch.setattr(svw.sv_worker, "transcribe", lambda a: dict(sv_res))
    probes = []
    monkeypatch.setattr(stw.stt_worker, "transcribe",
                        lambda a, language=None: probes.append(language) or {"text": DE_WH, "model": "Whisper-Small"})
    monkeypatch.setattr(vp, "speech_to_text", lambda *a, **k: "不該呼叫")
    guard = g.ForeignLangGuard(clock=lambda: 0.0)
    outs, infos = [], []
    for _ in range(3):
        out, info = {}, {}
        assert vp.speech_to_text_live(audio, "sensevoice", info_out=info, sv_out=out, lang_guard=guard) in (DE_SV, DE_WH)
        outs.append(out)
        infos.append(info)
    assert probes == [None, None, None]                                  # 自動偵測語言
    assert [o.get("use") for o in outs] == [None, None, "whisper"] and all(o["wtext"] == DE_WH for o in outs)
    assert "SenseVoice 不支援的語言" in infos[2]["engine"] and infos[0]["engine"].startswith("SenseVoiceSmall")


def test_speech_to_text_live_keeps_sensevoice_when_npu_unavailable(monkeypatch):
    audio = np.zeros(16000, dtype=np.float32)
    monkeypatch.setattr(svw.sv_worker, "transcribe",
                        lambda a: {"text": DE_SV, "raw_text": DE_SV, "lang": "<|en|>", "emotion": "<|HAPPY|>",
                                   "tokens": [], "timestamps": []})

    def boom(a, language=None):
        raise RuntimeError("stt worker transcribe failed")
    monkeypatch.setattr(stw.stt_worker, "transcribe", boom)
    monkeypatch.setattr(vp, "speech_to_text", lambda *a, **k: "不該呼叫（不可退到 CPU Whisper）")
    out = {}
    assert vp.speech_to_text_live(audio, "sensevoice", sv_out=out, lang_guard=g.ForeignLangGuard()) == DE_SV
    assert "wtext" not in out


def test_apply_whisper_live_maps_live_slices_onto_redecoded_sensevoice():
    """即時稿選 Whisper：即時切片（位置跟高精度稿的切片不同）對到同時段的 SenseVoice 輸出再判斷。"""
    sr = rt.SAMPLE_RATE
    # 高精度稿切片 0–6、6–12、12–18 s；即時切片 0–4、4–10、10–16、16–18 s
    toks = re.findall(r"\s*\S+", DE_SV)
    decoded = [(k * 6 * sr, (k + 1) * 6 * sr, DE_SV, "<|en|>", toks, [0.4 * i for i in range(len(toks))]) for k in range(3)]
    live = [{"s": 0, "n": 4 * sr, "wtext": DE_WH}, {"s": 4 * sr, "n": 6 * sr, "wtext": DE_WH},
            {"s": 10 * sr, "n": 6 * sr, "wtext": DE_WH}, {"s": 16 * sr, "n": 2 * sr, "src": "tail"}]
    out = rt.apply_whisper_live(decoded, live)
    whisper = [d for d in out if d[3] == rt.WHISPER_LANG_TAG]
    assert [d[0] for d in whisper] == [0, 4 * sr, 10 * sr] and all(d[2] == DE_WH for d in whisper)
    assert all("".join(d[4]).strip() == d[2].strip() and len(d[4]) == len(d[5]) for d in out)
    starts = [d[0] / sr + d[5][0] for d in out if d[5]]
    assert starts == sorted(starts)
    # 換掉的範圍內不留 SenseVoice 的字；16 s 之後（tail 沒有 Whisper 文字）照用 SenseVoice
    for d in out:
        if d[3] != rt.WHISPER_LANG_TAG:
            assert all(d[0] / sr + t >= 16.0 for t in d[5])
    # 支援的語言（Whisper 跟 SenseVoice 寫同一句英文）：原樣回傳
    en = "We will meet again next Tuesday to review the budget"
    en_toks = re.findall(r"\s*\S+", en)
    dec_en = [(i * 6 * sr, (i + 1) * 6 * sr, en, "<|en|>", en_toks, [0.3 * k for k in range(len(en_toks))]) for i in range(3)]
    live_en = [{"s": i * 6 * sr, "n": 6 * sr, "wtext": en} for i in range(3)]
    assert rt.apply_whisper_live(dec_en, live_en) is dec_en
    # 中文（SenseVoice 標 zh）即使 Whisper 寫英文也不比對（即時稿同規則）
    dec_zh = [(i * 6 * sr, (i + 1) * 6 * sr, "我們下週二再開會", "<|zh|>", list("我們下週二再開會"), [0.2 * k for k in range(8)])
              for i in range(3)]
    live_zh = [{"s": i * 6 * sr, "n": 6 * sr, "wtext": "We will meet again next Tuesday"} for i in range(3)]
    assert rt.apply_whisper_live(dec_zh, live_zh) is dec_zh


def test_live_whisper_file_round_trip(tmp_path):
    sr = rt.SAMPLE_RATE
    cache = tmp_path / "audio_cache"
    cache.mkdir()
    ogg = str(cache / "m_1.ogg")
    slices = [{"s": 0, "n": 5 * sr, "src": "other", "wtext": "Hallo"}, {"s": 5 * sr, "n": 5 * sr, "src": "other"}]
    p = rt.save_live_asr(ogg, slices, 10 * sr, rt.LIVE_WHISPER_SUFFIX)
    assert p.endswith("m_1.live_whisper.json")
    assert rt.load_live_asr(ogg, 10 * sr) is None                       # 不會被當成 SenseVoice 結果沿用
    got = rt.load_live_asr(ogg, 10 * sr, rt.LIVE_WHISPER_SUFFIX)
    assert [s.get("wtext") for s in got] == ["Hallo", None]
