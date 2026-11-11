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
