# -*- coding: utf-8 -*-
import meeting_minutes as mm


def _manager():
    m = mm.MeetingJobManager.__new__(mm.MeetingJobManager)   # 不跑 __init__（會載回上一場會議、建偵測器）
    m.on_meeting_done = None
    return m


def test_meeting_done_calls_hook_with_job_id():
    m = _manager()
    m._meeting_done("m_1")          # 沒有掛勾：什麼都不做
    seen = []
    m.on_meeting_done = seen.append
    m._meeting_done("m_2")
    assert seen == ["m_2"]


def test_meeting_done_hook_errors_do_not_escape(capsys):
    m = _manager()

    def boom(job_id):
        raise RuntimeError("refine unavailable")

    m.on_meeting_done = boom
    m._meeting_done("m_3")
    assert "refine unavailable" in capsys.readouterr().out


def test_transcript_ready_calls_hook_and_swallows_errors(capsys):
    """紀要只用 Hailo 時逐字稿一收尾就通知 main.py 提早跑高精度逐字稿；掛勾出錯不影響紀要。"""
    m = _manager()
    m.on_transcript_ready = None
    m._transcript_ready("m_1")      # 沒有掛勾：什麼都不做
    seen = []
    m.on_transcript_ready = seen.append
    m._transcript_ready("m_2")
    assert seen == ["m_2"]

    def boom(job_id):
        raise RuntimeError("refine busy")

    m.on_transcript_ready = boom
    m._transcript_ready("m_3")
    assert "refine busy" in capsys.readouterr().out


def test_summary_may_use_cpu(monkeypatch):
    import llm_backend
    healthy = {"hailo": True}
    monkeypatch.setattr(llm_backend, "PREFERRED_BACKEND", "hailo")
    monkeypatch.setattr(llm_backend, "is_backend_healthy", lambda b, force_refresh=False: healthy["hailo"])
    monkeypatch.setattr(mm, "SUMMARY_DUAL_MAP", False)
    assert mm.summary_may_use_cpu("zh") is False      # 只用 Hailo：CPU 閒著
    assert mm.summary_may_use_cpu("en") is False
    monkeypatch.setattr(mm, "SUMMARY_DUAL_MAP", True)
    assert mm.summary_may_use_cpu("zh") is True       # 中文兩路同時：CPU 那一路會用
    assert mm.summary_may_use_cpu("en") is False      # 英文不走兩路同時
    monkeypatch.setattr(mm, "SUMMARY_DUAL_MAP", False)
    healthy["hailo"] = False
    assert mm.summary_may_use_cpu("zh") is True       # Hailo 不能用 → 紀要退回 CPU Ollama
    healthy["hailo"] = True
    monkeypatch.setattr(llm_backend, "PREFERRED_BACKEND", "cpu")
    assert mm.summary_may_use_cpu("zh") is True


def test_job_started_or_done():
    from single_job import job_started_or_done
    assert job_started_or_done({"state": "running", "job": "m_1"}, "m_1")
    assert job_started_or_done({"state": "done", "job": "m_1"}, "m_1")
    assert not job_started_or_done({"state": "done", "job": "m_0"}, "m_1")     # 上一場的結果
    assert not job_started_or_done({"state": "stopped", "job": "m_1"}, "m_1")  # 被中止：紀要做完再跑一次
    assert not job_started_or_done({"state": "error", "job": "m_1"}, "m_1")
    assert not job_started_or_done({"state": "idle"}, "m_1")
    assert not job_started_or_done({"state": "done", "job": ""}, "")


def test_broadcast_audio_ready_sends_peaks_and_swallows_errors(monkeypatch, capsys):
    """錄音後波形峰值改到背景算（4 小時母帶 21.9 s，原本算進逐字稿收尾）；算不出來只記 log。"""
    import asyncio
    import sys
    import types
    sent = []

    async def broadcast(kind, payload):
        sent.append((kind, payload))

    monkeypatch.setitem(sys.modules, "ws_manager", types.SimpleNamespace(ws_manager=types.SimpleNamespace(broadcast=broadcast)))
    monkeypatch.setitem(sys.modules, "two_layer_audio",
                        types.SimpleNamespace(extract_waveform_peaks=lambda path, n: [0.1] * n))
    m = _manager()
    asyncio.run(m._broadcast_audio_ready("m_9", "/dev/shm/audio_cache/m_9.ogg", 600))
    assert sent == [("audio_ready", {"job_id": "m_9", "audio_url": "/audio/m_9.ogg", "duration": 600, "peaks": [0.1] * 200})]

    def boom(path, n):
        raise RuntimeError("ffmpeg died")

    monkeypatch.setitem(sys.modules, "two_layer_audio", types.SimpleNamespace(extract_waveform_peaks=boom))
    asyncio.run(m._broadcast_audio_ready("m_10", "/x.ogg", 1))
    assert "ffmpeg died" in capsys.readouterr().out
    assert len(sent) == 1
