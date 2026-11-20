import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))

import live_translate as lt  # noqa: E402


def test_target_for_auto_and_fixed():
    assert lt.target_for("第一個議題是預算", "auto") == "en"
    assert lt.target_for("We have a few topics to cover", "auto") == "zh"
    assert lt.target_for("Und dann haben wir hier Lemon", "auto") == "zh"
    assert lt.target_for("第一個議題", "zh") == "zh" and lt.target_for("hello there", "en") == "en"


def test_translator_batches_uses_hailo_only_and_joins(monkeypatch):
    calls = []

    async def fake_flat(units, target, on_progress, should_stop, use_cpu):
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
    async def fake_flat(units, target, on_progress, should_stop, use_cpu):
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
    for _ in range(5):
        tr.add("字" * 50)
    assert tr._next_batch(0) == [0, 1]          # 50+50 ≤ 120，再加一段超過


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
