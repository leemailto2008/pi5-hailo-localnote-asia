"""live_translate 補測：翻譯失敗顯示原文、網頁推送失敗不影響翻譯、暫停時整批重翻、NPU 忙碌時等候、停止、
延遲百分位、設定檔壞掉。transcript_translate._translate_flat 換成假的，不呼叫 LLM。"""
import asyncio
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "code_dispatcher"))
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))

import live_translate as lt  # noqa: E402


def _run_translator(tr, feed, timeout=3):
    async def scenario():
        task = asyncio.create_task(tr.run())
        await feed(tr)
        await asyncio.wait_for(task, timeout)
    asyncio.run(scenario())
    return tr


async def _add_and_close(tr, *texts):
    for t in texts:
        tr.add(t)
    tr.close()


def test_llm_error_keeps_source(monkeypatch):
    async def boom(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        raise lt.tt.LLMError("hailo-ollama 500")
    monkeypatch.setattr(lt.tt, "_translate_flat", boom)
    tr = _run_translator(lt.LiveTranslator("en"), lambda tr: _add_and_close(tr, "預算八十萬", "下週開會"))
    assert tr.text() == "預算八十萬 下週開會" and tr.kept == 2 and tr.stats()["live_tr_done"] == 2


def test_on_update_failure_does_not_stop_translation(monkeypatch):
    async def ok(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        return {"done": {k: u.upper() for k, u in enumerate(units)}, "llm_calls": 2}
    monkeypatch.setattr(lt.tt, "_translate_flat", ok)

    async def bad_update(tr):
        raise ConnectionResetError("ws gone")
    tr = _run_translator(lt.LiveTranslator("zh", on_update=bad_update), lambda tr: _add_and_close(tr, "hello team"))
    assert tr.text() == "HELLO TEAM" and tr.llm_calls == 2


def test_pause_during_request_retranslates_batch(monkeypatch):
    calls = []

    async def flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        calls.append(list(units))
        if len(calls) == 1:
            tr.pause()                         # 請求進行中被暫停（紀要要用 NPU）
            assert should_stop() is True       # interrupted 回報 True，讓翻譯中途停
        return {"done": {k: f"<{u}>" for k, u in enumerate(units)}}
    monkeypatch.setattr(lt.tt, "_translate_flat", flat)
    tr = lt.LiveTranslator("en")

    async def feed(t):
        t.add("第一段")
        await asyncio.sleep(0.05)
        assert t.text() == ""                  # 暫停中的那批不採用
        t.resume()
        t.close()
    _run_translator(tr, feed)
    assert calls == [["第一段"], ["第一段"]] and tr.text() == "<第一段>"
    assert tr.requests == 1                    # 被中斷的那次不算


def test_waits_while_npu_busy_then_stops(monkeypatch):
    seen = []

    async def flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        seen.append(units)
        return {"done": {}}
    monkeypatch.setattr(lt.tt, "_translate_flat", flat)
    state = {"busy": True, "stop": False}
    tr = lt.LiveTranslator("en", npu_busy=lambda: state["busy"], should_stop=lambda: state["stop"])

    async def feed(t):
        t.add("一段")
        await asyncio.sleep(0.4)
        assert seen == []                      # NPU 忙：不送請求
        state["stop"] = True                   # 新錄音開始：直接結束
    _run_translator(tr, feed)
    assert seen == [] and tr.text() == ""


def test_dump_and_percentiles():
    tr = lt.LiveTranslator("auto")
    for t in ("好", "hello"):
        tr.add(t)
    tr.out, tr.targets, tr.latencies = {0: "OK", 1: "你好"}, {0: "en", 1: "zh"}, [1.0, 2.0, 9.0]
    d = tr.dump()
    assert d["segments"] == [{"src": "好", "out": "OK", "target": "en"}, {"src": "hello", "out": "你好", "target": "zh"}]
    assert d["live_tr_lat_p50"] == 2.0 and d["live_tr_lat_p90"] == 9.0 and d["live_tr_lat_max"] == 9.0
    assert tr.text() == "OK 你好"
    assert lt._percentile([], 0.5) is None
    empty = lt.LiveTranslator("en").stats()
    assert empty["live_tr_lat_max"] is None and empty["live_tr_segments"] == 0


def test_add_ignores_blank_and_closed_flag():
    tr = lt.LiveTranslator("en")
    tr.add("   ")
    tr.add("")
    assert tr.src == [] and tr.closed is False
    tr.close()
    assert tr.closed is True


def test_preference_file_unreadable_uses_defaults(monkeypatch, tmp_path):
    p = tmp_path / "live_tr.json"
    p.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(lt, "LIVE_TR_PATH", str(p))
    assert lt._read_pref() == {}
    p.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert lt._read_pref() == {}
    monkeypatch.setattr(lt, "LIVE_TR_PATH", str(tmp_path / "missing.json"))
    assert lt._read_pref() == {}
