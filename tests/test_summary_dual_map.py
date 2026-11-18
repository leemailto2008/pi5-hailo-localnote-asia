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


def _setup(monkeypatch, dual=True, recording=lambda: False, cpu_stop_after=None, cpu_template_only=False,
           transcript=None, premap=None, cpu_delay=0.025, hailo_delay=0.01, hailo_empty_for=()):
    calls = {"hailo": [], "cpu": [], "cpu_stopped": [], "hailo_cancelled": []}
    monkeypatch.setattr(mm, "map_user_prompt", lambda piece, idx, total, lang="zh": f"IDX={idx}")
    monkeypatch.setattr(mm, "DUAL_MAP_POLL_S", 0.005)

    async def fake_hailo(prompt, keep_alive=None, hailo_only=False, lang="zh"):
        idx = int(re.search(r"IDX=(\d+)", prompt).group(1))
        calls["hailo"].append(idx)
        try:
            await asyncio.sleep(hailo_delay(idx) if callable(hailo_delay) else hailo_delay)
        except asyncio.CancelledError:
            calls["hailo_cancelled"].append(idx)
            raise
        if idx in hailo_empty_for:
            return "", _Backend(True)
        return f"- 第{idx}段重點：王專員追蹤交期", _Backend(True)

    async def fake_cpu(prompt, lang="zh", should_stop=None):
        idx = int(re.search(r"IDX=(\d+)", prompt).group(1))
        calls["cpu"].append(idx)
        t_end = asyncio.get_running_loop().time() + cpu_delay
        while asyncio.get_running_loop().time() < t_end:   # 跟真的 stream_map_notes_cpu 一樣輪詢 should_stop
            await asyncio.sleep(0.005)
            if should_stop is not None and should_stop():
                calls["cpu_stopped"].append(idx)
                return "", None, True
        if cpu_stop_after is not None and len(calls["cpu"]) > cpu_stop_after:
            return "", None, True
        if cpu_template_only:   # 11-16 podcast：CPU 只照抄範例標籤
            return "- 教育訓練：-\n- 客戶訂單：-\n- 預算：", _Backend(False), False
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
    job._premap_notes, job._premap_prefix, job._premap_lang = premap or ([], "", "")
    job.notify_status_update = lambda: None
    out = asyncio.run(job._hierarchical_summary_body(transcript or _transcript(), None))
    return job, calls, out


def test_dual_map_hailo_front_cpu_back_each_chunk_once(monkeypatch):
    job, calls, out = _setup(monkeypatch)
    total = job.status.metrics["summary_chunks"]
    assert total >= 4
    assert sorted(set(calls["hailo"] + calls["cpu"])) == list(range(1, total + 1))   # 每段都做到
    both = set(calls["hailo"]) & set(calls["cpu"])
    assert len(both) <= 1                                        # 只有最後碰頭時 CPU 手上那段可能兩路同時做 (hailo_race)
    assert len(calls["hailo"]) == len(set(calls["hailo"])) and len(calls["cpu"]) == len(set(calls["cpu"]))
    assert calls["hailo"][0] == 1 and calls["cpu"][0] == total   # Hailo 從第一段、CPU 從最後一段
    assert max(set(calls["hailo"]) - both) < min(calls["cpu"])   # 碰頭為止，不交錯
    raced = job.status.metrics["summary_hailo_raced"]
    assert job.status.metrics["summary_cpu_chunks"] + raced == len(calls["cpu"]) and len(calls["cpu"]) >= 1
    found = [int(n) for n in re.findall(r"第(\d+)段重點", out)]
    assert found == sorted(found) and len(found) == len(set(found))   # 紀要裡順序跟逐字稿一樣、同一段不重複


def test_dual_map_cpu_stops_when_recording_starts_and_hailo_takes_the_chunk(monkeypatch):
    job, calls, out = _setup(monkeypatch, cpu_stop_after=0)    # CPU 第一段就被錄音打斷
    total = job.status.metrics["summary_chunks"]
    assert calls["cpu"] == [total]
    assert sorted(calls["hailo"]) == list(range(1, total + 1))   # 交回的那段也由 Hailo 做完
    assert job.status.metrics["summary_cpu_chunks"] == 0
    assert f"第{total}段重點" in out


def test_cpu_notes_with_only_template_labels_go_back_to_hailo(monkeypatch):
    job, calls, out = _setup(monkeypatch, cpu_template_only=True)
    total = job.status.metrics["summary_chunks"]
    assert calls["cpu"] == [total]                                  # CPU 第一段就只寫範例標籤 → 收工
    assert sorted(calls["hailo"]) == list(range(1, total + 1))      # 那段由 Hailo 重做
    assert job.status.metrics["summary_cpu_chunks"] == 0
    assert f"第{total}段重點" in out and "教育訓練" not in out


def _two_chunks():
    """錄音後只剩 2 段 (錄音中預先整理過前段) 的常見情況：Hailo 拿第 1 段、CPU 拿第 2 段。"""
    return "".join(f"第{i}個議題是採購進度。" + f"供應商第{i}批零件預計下週到貨，請王專員追蹤交期並回報主管，" * 28 for i in (1, 2))


def test_hailo_races_slow_cpu_chunk_and_wins(monkeypatch):
    # podcast 11-18 20:46：CPU 做最後一段 55 s 沒寫出重點才交回 Hailo；Hailo 閒著時應同時做那段，先寫完就用它的
    job, calls, out = _setup(monkeypatch, transcript=_two_chunks(), cpu_delay=1.0)
    total = job.status.metrics["summary_chunks"]
    assert total == 2
    assert calls["cpu"] == [2] and calls["cpu_stopped"] == [2]   # CPU 那一份被收掉
    assert calls["hailo"] == [1, 2]
    assert job.status.metrics["summary_hailo_raced"] == 1 and job.status.metrics["summary_cpu_chunks"] == 0
    assert "第1段重點" in out and "第2段重點" in out


def test_cpu_finishing_first_cancels_hailo_race(monkeypatch):
    job, calls, out = _setup(monkeypatch, transcript=_two_chunks(), cpu_delay=0.05,
                             hailo_delay=lambda idx: 0.01 if idx == 1 else 1.0)
    assert calls["hailo"] == [1, 2] and calls["hailo_cancelled"] == [2]   # Hailo 那一份被取消
    assert job.status.metrics["summary_cpu_chunks"] == 1 and job.status.metrics["summary_hailo_raced"] == 0
    assert out.count("第2段重點") == 1


def test_race_where_neither_writes_notes_still_keeps_the_chunk(monkeypatch):
    # CPU 只照抄範例標籤、Hailo 同時做也沒寫出重點：那段交回待辦，Hailo 一般流程再做一次 (失敗就保留原文開頭)
    job, calls, out = _setup(monkeypatch, transcript=_two_chunks(), cpu_delay=0.2, cpu_template_only=True,
                             hailo_empty_for=(2,))
    assert calls["cpu"] == [2]
    assert calls["hailo"].count(2) == 2          # 同時做一次＋交回後再一次
    assert "教育訓練" not in out and "第1段重點" in out
    assert "供應商第2批" in out                  # 第 2 段沒有在紀要中消失 (保留原文開頭)


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


def test_cpu_takes_last_chunk_only_if_it_finishes_earlier_than_hailo():
    """2026-11-15 服務內 GS3 30 分：Hailo 做完第 3 段的同一秒 CPU 搶到最後一段，CPU 做 58 s、Hailo 閒著。"""
    assert not mm.cpu_should_take_last([], [], None)              # 預設 Hailo 36 s、CPU 60 s，Hailo 閒著 → 給 Hailo
    assert mm.cpu_should_take_last([], [], 0.0)                   # Hailo 才剛開始一段：36 + 36 > 60 → CPU 接
    assert not mm.cpu_should_take_last([40.0], [58.0], 35.0)      # Hailo 快做完手上那段：5 + 40 < 58 → 給 Hailo
    assert mm.cpu_should_take_last([40.0], [20.0], None)          # CPU 比較快就給 CPU
    assert not mm.cpu_should_take_last([40.0], [58.0], 90.0)      # Hailo 已經超時：剩 0 s 估，40 < 58 → 給 Hailo


def test_summary_estimate_matches_measured_durations():
    """進度條的紀要預估：5 分（約 1,055 字）單次整理實測 74–126 s，舊估計 25 s；逐段＋兩路同時 30 分 146 s、120 分 561 s。"""
    assert 80 <= mm.estimate_summary_seconds(1055, False) <= 110
    assert mm.estimate_summary_seconds(100, False) == 25.0
    assert 130 <= mm.estimate_summary_seconds(6000, True, dual=True) <= 180
    assert 500 <= mm.estimate_summary_seconds(25000, True, dual=True) <= 620
    # 只用 Hailo（預設）：11-14 實測 30 分約 6,050 字 185–196 s、120 分約 24,940 字 826–868 s、240 分 48,627 字 1,660 s
    assert 180 <= mm.estimate_summary_seconds(6050, True) <= 220
    assert 800 <= mm.estimate_summary_seconds(24940, True) <= 880
    assert 1600 <= mm.estimate_summary_seconds(48627, True) <= 1720


def test_dual_map_and_premap_are_on_by_default():
    """2026-11-16 使用者決定：兩路同時（多約 2 GB，e2e RAM 門檻跟著調）與錄音中預先整理預設開；=0 關閉。"""
    import os

    import pytest
    if "PI5_SUMMARY_DUAL_MAP" in os.environ or "PI5_SUMMARY_PREMAP" in os.environ:
        pytest.skip("環境變數已指定 PI5_SUMMARY_DUAL_MAP／PI5_SUMMARY_PREMAP")
    assert mm.SUMMARY_DUAL_MAP is True
    assert mm.SUMMARY_PREMAP is True


def test_english_meeting_uses_hailo_only(monkeypatch):
    """英文長會議不開 CPU 那一路（CPU 模型的英文重點會寫成子項目，見 meeting_minutes 註解）。"""
    monkeypatch.setattr(mm, "detect_language", lambda text: "en")
    job, calls, _ = _setup(monkeypatch)
    assert calls["cpu"] == [] and len(calls["hailo"]) == job.status.metrics["summary_chunks"]


def test_last_part_prompt_only_for_recap_chunk():
    # 11-16 podcast：沒有總結的最後一段照「事項與負責人」寫成「- 新興技術應用：-」→ 只有真的是結尾總結才用總結提示
    plain = mm.map_user_prompt("當我從例行工作釋放出時間，可以做更有價值的事。", 10, 10)
    assert "會議最後一段" not in plain and plain.endswith("請條列本段重點：")
    recap = mm.map_user_prompt("最後總結一下。訓練方面，決議是九月二日開課。", 7, 7)
    assert "會議最後一段" in recap and "事項與負責人" in recap
    en = mm.map_user_prompt("So that is it, thanks everyone.", 5, 5, lang="en")
    assert "the last part" not in en
    assert "the last part" in mm.map_user_prompt("To wrap up, John will send the report by Friday.", 5, 5, lang="en")


def test_premap_notes_reused_only_when_language_matches(monkeypatch):
    """錄音中預先整理的提示詞語言跟錄音後整份逐字稿不同就不沿用 (2026-11-18：德文會議前段重點被寫成中文)。"""
    zh = _transcript()
    prefix = zh[:1000]
    job, calls, out = _setup(monkeypatch, dual=False, transcript=zh, premap=(["- 預先整理的重點：王專員"], prefix, "zh"))
    assert job.status.metrics["summary_premap_used"] == 1 and 1 not in calls["hailo"] and "預先整理的重點" in out
    en = ("We reviewed the supplier schedule and the parts will arrive next week, so Wang will track the delivery dates. " * 60)
    job, calls, out = _setup(monkeypatch, dual=False, transcript=en, premap=(["- 中文重點：不該沿用"], en[:1000], "zh"))
    assert job.status.metrics["summary_premap_used"] == 0 and calls["hailo"][0] == 1 and "不該沿用" not in out
