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
    assert tr._next_batch(0) == [0, 1, 2, 3]    # 落後：一次最多 240 字 (4 段 200 字)


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
