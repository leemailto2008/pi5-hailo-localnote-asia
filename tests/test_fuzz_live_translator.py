"""P16（2026-11-27 localnote@mac）：即時翻譯 LiveTranslator 的 hypothesis fuzz（假的 _translate_flat，不叫模型）。
隨機穿插：新段落、暫停／恢復（錄音結束讓 NPU 給紀要）、模型漏回、請求失敗（LLMError）、後處理意外錯誤、翻到一半被停。
性質：每段最後一定有輸出，不是那段的譯文就是原文（看不懂整串保留，不生出別的內容）；保留原文的段一定記原因；
kept 計數和保留原因一致；畫面文字只由這些輸出依序接起來；做完時 pending() 是 False；不卡住、不當掉。"""
import asyncio
import os
import sys
import tempfile
import types

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

hypothesis.configuration.set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "hyp_p16"))
sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="x", DATA_DIR=os.path.join(os.path.dirname(__file__), "_tmp_data")))
import live_translate as lt  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=800 if SLOW else 30, deadline=None, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])

SEG = st.sampled_from(["好，我們開始。", "第一個議題是預算 300 萬。", "Okay, next topic.", "請吳副理週五前完成。", "We ship 1,200 units.",
                       "嗯。", "第三季目標 30%。"])
OP = st.one_of(st.tuples(st.just("add"), SEG), st.tuples(st.sampled_from(["pause", "resume", "tick"]), st.just("")))
REPLY = st.sampled_from(["all", "none", "some", "llm_error", "error", "stopped"])


def _tr(u, target):
    return f"<{target}:{u}>"


@CFG
@given(st.lists(OP, max_size=25), st.lists(REPLY, min_size=1, max_size=20), st.sampled_from(["auto", "en", "zh"]))
def test_live_translator_every_segment_ends_translated_or_source(monkeypatch, ops, replies, mode):
    it = iter(replies)

    async def fake_flat(units, target, on_progress, should_stop, use_cpu, one_chunk=False):
        await asyncio.sleep(0)
        r = next(it, "all")
        if r == "llm_error":
            raise lt.tt.LLMError("boom")
        if r == "error":
            raise ValueError("postfix boom")
        if r == "none":
            return {"done": {}}
        if r == "some":
            return {"done": {k: _tr(u, target) for k, u in enumerate(units) if k % 2 == 0}}
        if r == "stopped":
            return {"done": {}, "stopped": True}
        return {"done": {k: _tr(u, target) for k, u in enumerate(units)}}
    monkeypatch.setattr(lt.tt, "_translate_flat", fake_flat)

    async def scenario():
        tr = lt.LiveTranslator(mode)
        task = asyncio.create_task(tr.run())
        for op, arg in ops:
            if op == "add":
                tr.add(arg)
            elif op == "pause":
                tr.pause()
            elif op == "resume":
                tr.resume()
            await asyncio.sleep(0)
        tr.close()
        tr.resume()
        await asyncio.wait_for(task, 5)
        return tr

    tr = asyncio.run(scenario())
    assert len(tr.out) == len(tr.src) and not tr.pending()
    kept = [i for i in range(len(tr.src)) if tr.out[i] == tr.src[i]]
    for i, s in enumerate(tr.src):
        assert tr.out[i] in (s, _tr(s, tr.targets[i])), (i, s, tr.out[i])
        assert (i in tr.kept_reason) == (tr.out[i] == s), (i, s, tr.out[i], tr.kept_reason)
    assert tr.kept == len(kept), (tr.kept, kept)
    sep = [" " if tr.targets.get(i) == "en" or tr.targets.get(i - 1) == "en" else "" for i in range(len(tr.src))]
    assert tr.text() == "".join((sep[i] if i else "") + tr.out[i] for i in range(len(tr.src)))
    d = tr.dump()
    assert d["live_tr_done"] == len(tr.src) and len(d["segments"]) == len(tr.src)
