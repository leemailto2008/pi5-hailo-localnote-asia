import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import live_translate as lt  # noqa: E402


def test_target_for_auto_and_fixed():
    assert lt.target_for("第一個議題是預算", "auto") == "en"
    assert lt.target_for("We have a few topics to cover", "auto") == "zh"
    assert lt.target_for("Und dann haben wir hier Lemon", "auto") == "zh"
    assert lt.target_for("第一個議題", "zh") == "zh" and lt.target_for("hello there", "en") == "en"


def test_translator_batches_uses_hailo_only_and_joins(monkeypatch):
    calls = []

    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        calls.append((list(units), target, use_cpu))
        return {"done": {k: f"<{target}:{u}>" for k, u in enumerate(units)}}
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)
    updates = []

    async def on_update(tr):
        updates.append(tr.text())

    async def scenario():
        tr = lt.LiveTranslator("auto", on_update=on_update)
        task = asyncio.create_task(tr.run())
        for t in ("好，我們開始。", "第一個議題是預算。", "Okay, next topic."):
            tr.add(t)
        tr.close()
        await asyncio.wait_for(task, 2)
        return tr

    tr = asyncio.run(scenario())
    assert all(c[2] is False for c in calls)                       # 錄音中只用 Hailo
    assert calls[0] == (["好，我們開始。", "第一個議題是預算。"], "en", False)   # 同目標語言合成一次請求
    assert calls[1][1] == "zh"
    assert tr.text() == "<en:好，我們開始。> <en:第一個議題是預算。> <zh:Okay, next topic.>"
    st = tr.stats()
    assert st["live_tr_segments"] == 3 and st["live_tr_done"] == 3 and st["live_tr_requests"] == 2 and st["live_tr_kept"] == 0
    assert updates[-1] == tr.text()


def test_translator_keeps_source_when_not_translated(monkeypatch):
    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        return {"done": {}}
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)

    async def scenario():
        tr = lt.LiveTranslator("en")
        task = asyncio.create_task(tr.run())
        tr.add("預算是80萬元")
        tr.close()
        await asyncio.wait_for(task, 2)
        return tr

    tr = asyncio.run(scenario())
    assert tr.text() == "預算是80萬元" and tr.kept == 1


def test_batch_char_limit():
    tr = lt.LiveTranslator("en")
    tr.add("字" * 50)
    tr.add("字" * 50)
    assert tr._next_batch(0) == [0, 1]          # 跟得上 (還沒翻的 ≤ 120 字)：一次 ≤ 120 字
    for _ in range(10):
        tr.add("字" * 50)
    assert tr._next_batch(0) == list(range(9))  # 落後：一次最多 480 字 (9 段 450 字)
    tr2 = lt.LiveTranslator("en", npu_shared=lambda: True)
    for _ in range(12):
        tr2.add("字" * 50)
    assert tr2._next_batch(0) == [0, 1, 2, 3]   # 即時稿也用 NPU：最多 240 字


def test_preference_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(lt, "LIVE_TR_PATH", str(tmp_path / "live_translate.json"))
    assert lt.load_live_translate_preference() == lt.LIVE_TR_DEFAULT
    lt.save_live_translate_preference("zh")
    assert lt.load_live_translate_preference() == "zh"
    try:
        lt.save_live_translate_preference("fr")
        raise AssertionError("should reject")
    except ValueError:
        pass


def test_pause_holds_new_requests_until_resume(monkeypatch):
    calls = []

    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        calls.append(list(units))
        return {"done": {k: "x" for k, _u in enumerate(units)}}
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)

    async def scenario():
        tr = lt.LiveTranslator("en")
        tr.pause()
        task = asyncio.create_task(tr.run())
        tr.add("第一段")
        tr.close()
        await asyncio.sleep(0.05)
        held = list(calls)
        tr.resume()
        await asyncio.wait_for(task, 2)
        return held

    assert asyncio.run(scenario()) == [] and calls == [["第一段"]]


def test_waits_while_npu_busy(monkeypatch):
    calls = []

    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        calls.append(list(units))
        return {"done": {k: "x" for k, _u in enumerate(units)}}
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)
    busy = [True]

    async def scenario():
        tr = lt.LiveTranslator("en", npu_busy=lambda: busy[0])
        task = asyncio.create_task(tr.run())
        tr.add("第一段")
        tr.close()
        await asyncio.sleep(0.4)
        held = list(calls)
        busy[0] = False
        await asyncio.wait_for(task, 2)
        return held

    assert asyncio.run(scenario()) == [] and calls == [["第一段"]]


def test_pause_interrupts_in_flight_batch_and_retries(monkeypatch):
    calls = []

    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        calls.append(list(units))
        for _ in range(50):                      # 模擬長請求，暫停時中止
            if should_stop():
                return {"done": {}}
            await asyncio.sleep(0.01)
        return {"done": {k: "ok" for k, _u in enumerate(units)}}
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)

    async def scenario():
        tr = lt.LiveTranslator("en")
        task = asyncio.create_task(tr.run())
        tr.add("第一段")
        await asyncio.sleep(0.05)
        tr.pause()                               # 進行中的請求被中止，不算翻好
        tr.close()
        await asyncio.sleep(0.1)
        assert tr.out == {}
        tr.resume()
        await asyncio.wait_for(task, 3)
        return tr

    tr = asyncio.run(scenario())
    assert tr.out == {0: "ok"} and tr.kept == 0 and len(calls) == 2 and tr.requests == 1


def test_saved_live_translation_keeps_recent_files(tmp_path, monkeypatch):
    import meeting_minutes as mm
    import refine_transcript as rt
    cache = tmp_path / "audio_cache"
    cache.mkdir()
    monkeypatch.setattr(mm, "AUDIO_CACHE_DIR", str(cache))
    for k in range(rt.LIVE_ASR_KEEP + 3):
        p = mm._save_live_translation(f"m_{k}", {"segments": []})
        os.utime(p, (k, k))
    left = sorted(os.listdir(tmp_path / "localnote_state"))
    assert len(left) == rt.LIVE_ASR_KEEP and f"m_{rt.LIVE_ASR_KEEP + 2}.live_tr.json" in left


def test_effective_mode_follows_asr_language():
    assert lt.effective_mode("auto", "auto") == "auto"
    assert lt.effective_mode("auto", "zh") == "en"
    assert lt.effective_mode("auto", "en") == "zh" and lt.effective_mode("auto", "fr") == "zh" and lt.effective_mode("auto", "es") == "zh"
    assert lt.effective_mode("en", "zh") == "en" and lt.effective_mode("off", "fr") == "off"


def test_premap_preference_default_and_independent_of_target(tmp_path, monkeypatch):
    monkeypatch.setattr(lt, "LIVE_TR_PATH", str(tmp_path / "live_translate.json"))
    assert lt.load_premap_with_translate() is True                 # 預設維持原本做法
    lt.save_live_translate_preference("zh")
    lt.save_premap_with_translate(False)
    assert lt.load_live_translate_preference() == "zh" and lt.load_premap_with_translate() is False
    lt.save_live_translate_preference("en")                         # 改目標語言不影響 premap
    assert lt.load_premap_with_translate() is False
    (tmp_path / "live_translate.json").write_text('{"target": "auto", "premap": "no"}', encoding="utf-8")
    assert lt.load_premap_with_translate() is True                  # 值不對時用預設


def test_prep_for_translate_applies_term_fixes_and_glossary(monkeypatch):
    import meeting_minutes as mm
    monkeypatch.setattr(mm, "fix_meeting_terms", lambda t: t.replace("任體", "韌體"))
    monkeypatch.setattr(mm, "apply_meeting_glossary", lambda t: (t.replace("黃專元", "黃專員"), 1))
    assert mm.MeetingJobManager._prep_for_translate("黃專元說任體更新") == "黃專員說韌體更新"

    def boom(t):
        raise ValueError("bad glossary")
    monkeypatch.setattr(mm, "apply_meeting_glossary", boom)
    assert mm.MeetingJobManager._prep_for_translate("原文") == "原文"   # 修不了照原文


def test_next_recording_lets_previous_tail_finish(monkeypatch):
    """11-21 W14：紀要出來 24 s 後就開下一場，上一場最後 4 段沒翻到。下一場開始時，已錄完的上一場在背景翻完；取消錄音照舊停掉。"""
    import meeting_minutes as mm

    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        await asyncio.sleep(0.05)
        return {"done": {k: "x" for k, _u in enumerate(units)}}
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)

    async def scenario(closed, keep_tail):
        m = mm.MeetingJobManager.__new__(mm.MeetingJobManager)
        tr = lt.LiveTranslator("en")
        tr.add("最後一段")
        if closed:
            tr.close()
        tr.pause()                      # 錄音結束後暫停、紀要後才補翻
        m._live_tr, m._live_tr_task = tr, asyncio.create_task(tr.run())
        task = m._live_tr_task
        await asyncio.sleep(0.01)
        m._stop_live_translate(keep_tail=keep_tail)
        assert m._live_tr is None and m._live_tr_task is None
        try:
            await asyncio.wait_for(task, 2)
        except asyncio.CancelledError:
            return "cancelled"
        return tr.out

    assert asyncio.run(scenario(closed=True, keep_tail=True)) == {0: "x"}
    assert asyncio.run(scenario(closed=True, keep_tail=False)) == "cancelled"     # 取消錄音
    assert asyncio.run(scenario(closed=False, keep_tail=True)) == "cancelled"     # 還在錄 (沒 close) 不留


def _run_one(monkeypatch, fake_flat, text="預算是80萬元"):
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)

    async def scenario():
        tr = lt.LiveTranslator("en")
        task = asyncio.create_task(tr.run())
        tr.add(text)
        tr.close()
        await asyncio.wait_for(task, 2)
        return tr
    return asyncio.run(scenario())


def test_kept_reason_rejected_when_unit_not_returned(monkeypatch):
    """11-24：保留原文的段要記原因，事後才查得出是請求失敗還是沒通過檢查。"""
    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        return {"done": {}}
    tr = _run_one(monkeypatch, fake_flat)
    segs = tr.dump()["segments"]
    assert segs[0]["kept"] == "rejected" and segs[0]["out"] == segs[0]["src"]


def test_kept_reason_llm_error_when_batch_fails(monkeypatch):
    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        raise lt.tt.LLMError("hailo 500")
    tr = _run_one(monkeypatch, fake_flat)
    assert tr.dump()["segments"][0]["kept"] == "llm_error"


def test_translated_segment_has_no_kept_field(monkeypatch):
    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        return {"done": {0: "The budget is 800,000 yuan."}}
    tr = _run_one(monkeypatch, fake_flat)
    assert "kept" not in tr.dump()["segments"][0]
