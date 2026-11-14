"""長會議逐段整理同時用 Hailo 與 CPU Ollama (2026-11-15)：Hailo 從前面、CPU 從後面，每段只整理一次、順序不亂；
開始錄音時 CPU 那一路停下、把那段交回 Hailo；關掉或 CPU 不可用時跟以前一樣全部給 Hailo。"""
import asyncio
import re
import sys
import types

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import meeting_minutes as mm  # noqa: E402


class _Backend:
    def __init__(self, hailo):
        self.is_hailo = hailo
        self.label = "Hailo-10H NPU fake" if hailo else "CPU Ollama fake"


def _transcript():
    topics = []
    for i in range(1, 19):
        topics.append(f"第{i}個議題是採購進度。" + f"供應商第{i}批零件預計下週到貨，請王專員追蹤交期並回報主管，" * 12)
    return "".join(topics)


def _setup(monkeypatch, dual=True, recording=lambda: False, cpu_stop_after=None):
    calls = {"hailo": [], "cpu": []}
    monkeypatch.setattr(mm, "map_user_prompt", lambda piece, idx, total, lang="zh": f"IDX={idx}")

    async def fake_hailo(prompt, keep_alive=None, hailo_only=False, lang="zh"):
        idx = int(re.search(r"IDX=(\d+)", prompt).group(1))
        calls["hailo"].append(idx)
        await asyncio.sleep(0.01)
        return f"- 第{idx}段重點：王專員追蹤交期", _Backend(True)

    async def fake_cpu(prompt, lang="zh", should_stop=None):
        idx = int(re.search(r"IDX=(\d+)", prompt).group(1))
        calls["cpu"].append(idx)
        await asyncio.sleep(0.025)
        if cpu_stop_after is not None and len(calls["cpu"]) > cpu_stop_after:
            return "", None, True
        return f"- 第{idx}段重點：王專員追蹤交期", _Backend(False), False

    monkeypatch.setattr(mm, "stream_map_notes", fake_hailo)
    monkeypatch.setattr(mm, "stream_map_notes_cpu", fake_cpu)
    monkeypatch.setattr(mm, "_recording_active", recording)
    monkeypatch.setattr(mm, "_dual_map_available", lambda: True)
    monkeypatch.setattr(mm, "SUMMARY_DUAL_MAP", dual)

    async def broadcast(*a, **k):
        return None
    monkeypatch.setitem(sys.modules, "ws_manager", types.SimpleNamespace(ws_manager=types.SimpleNamespace(broadcast=broadcast)))
    job = mm.MeetingJobManager.__new__(mm.MeetingJobManager)   # 跳過 __init__，避免硬體與背景任務
    job.status = mm.JobStatus()
    job._cancellation_token = None
    job._hailo_pinned = False
    job._premap_notes, job._premap_prefix = [], ""
    job.notify_status_update = lambda: None
    out = asyncio.run(job._hierarchical_summary_body(_transcript(), None))
    return job, calls, out


def test_dual_map_hailo_front_cpu_back_each_chunk_once(monkeypatch):
    job, calls, out = _setup(monkeypatch)
    total = job.status.metrics["summary_chunks"]
    assert total >= 4
    done = sorted(calls["hailo"] + calls["cpu"])
    assert done == list(range(1, total + 1))                     # 每段剛好一次
    assert calls["hailo"][0] == 1 and calls["cpu"][0] == total   # Hailo 從第一段、CPU 從最後一段
    assert max(calls["hailo"]) < min(calls["cpu"])               # 碰頭為止，不交錯
    assert job.status.metrics["summary_cpu_chunks"] == len(calls["cpu"]) >= 1
    found = [int(n) for n in re.findall(r"第(\d+)段重點", out)]
    assert found == sorted(found)                                # 紀要裡的順序跟逐字稿一樣


def test_dual_map_cpu_stops_when_recording_starts_and_hailo_takes_the_chunk(monkeypatch):
    job, calls, out = _setup(monkeypatch, cpu_stop_after=0)    # CPU 第一段就被錄音打斷
    total = job.status.metrics["summary_chunks"]
    assert calls["cpu"] == [total]
    assert sorted(calls["hailo"]) == list(range(1, total + 1))   # 交回的那段也由 Hailo 做完
    assert job.status.metrics["summary_cpu_chunks"] == 0
    assert f"第{total}段重點" in out


def test_dual_map_off_or_recording_uses_hailo_only(monkeypatch):
    job, calls, _ = _setup(monkeypatch, dual=False)
    assert calls["cpu"] == [] and calls["hailo"] == list(range(1, job.status.metrics["summary_chunks"] + 1))
    job, calls, _ = _setup(monkeypatch, recording=lambda: True)
    assert calls["cpu"] == [] and calls["hailo"] == list(range(1, job.status.metrics["summary_chunks"] + 1))


def test_stream_map_notes_cpu_cancels_request_when_recording_starts(monkeypatch):
    """CPU 預填沒有 token 的時候開始錄音，也要在 DUAL_MAP_POLL_S 內關掉請求。"""
    state = {"closed": False, "recording": False}

    async def slow_stream(prompt, **kwargs):
        try:
            await asyncio.sleep(5)
            yield "- 不該出現", False, _Backend(False)
        finally:
            state["closed"] = True

    monkeypatch.setattr(mm, "aiter_chat_stream", slow_stream)
    monkeypatch.setattr(mm, "DUAL_MAP_POLL_S", 0.02)

    async def run():
        async def start_recording():
            await asyncio.sleep(0.1)
            state["recording"] = True
        asyncio.ensure_future(start_recording())
        return await mm.stream_map_notes_cpu("IDX=1", should_stop=lambda: state["recording"])

    text, backend, stopped = asyncio.run(run())
    assert stopped and text == "" and backend is None
    assert state["closed"]
