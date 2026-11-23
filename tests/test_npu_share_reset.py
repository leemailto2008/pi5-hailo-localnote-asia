"""npu_share.reset_group／maybe_reset 背景執行／shared_group 快取：systemctl、stt_worker 都換成假的，不碰 NPU。"""
import contextlib
import threading

import pytest

import npu_share as ns
import stt_worker as sw


@pytest.fixture
def fake_reset(monkeypatch):
    log = []

    @contextlib.contextmanager
    def paused():                      # 同 stt_worker.paused：with 區塊內出例外也會放開
        log.append("pause")
        try:
            yield
        finally:
            log.append("resume")
    monkeypatch.setattr(sw.stt_worker, "paused", paused)
    monkeypatch.setattr(ns, "_restart_hailo_ollama", lambda: log.append("restart"))
    monkeypatch.setattr(ns.time, "sleep", lambda s: log.append("sleep"))
    monkeypatch.setattr(ns, "_reset_state", {"running": False, "last_time": 0.0, "last": None})
    return log


def test_reset_group_success_waits_for_group_then_prewarms(fake_reset, monkeypatch):
    seq = iter([None, None, "G"])
    monkeypatch.setattr(ns, "shared_group", lambda force_refresh=False: next(seq))
    assert ns.reset_group("test", prewarm=lambda: fake_reset.append("prewarm")) is True
    assert fake_reset == ["pause", "restart", "sleep", "sleep", "resume", "prewarm"]
    st = ns.reset_status()
    assert st["ok"] is True and st["error"] is None and st["reason"] == "test" and st["duration_s"] >= 0


def test_reset_group_gives_up_waiting_after_30_tries(fake_reset, monkeypatch):
    monkeypatch.setattr(ns, "shared_group", lambda force_refresh=False: None)
    assert ns.reset_group("slow") is True
    assert fake_reset.count("sleep") == 30


def test_reset_group_restart_failure_skips_prewarm(fake_reset, monkeypatch):
    def boom():
        raise ns.subprocess.CalledProcessError(1, "systemctl")
    monkeypatch.setattr(ns, "_restart_hailo_ollama", boom)
    monkeypatch.setattr(ns, "shared_group", lambda force_refresh=False: "G")
    assert ns.reset_group("bad", prewarm=lambda: fake_reset.append("prewarm")) is False
    assert "prewarm" not in fake_reset and fake_reset[-1] == "resume"   # 失敗也要放開 STT
    assert ns.reset_status()["error"].startswith("CalledProcessError")


def test_reset_group_prewarm_failure_is_not_fatal(fake_reset, monkeypatch):
    monkeypatch.setattr(ns, "shared_group", lambda force_refresh=False: "G")

    def bad_prewarm():
        raise RuntimeError("hailo-ollama 500")
    assert ns.reset_group("x", prewarm=bad_prewarm) is True


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")   # 故意讓背景 reset 拋例外
def test_maybe_reset_background_clears_running_flag(monkeypatch):
    monkeypatch.setattr(ns, "_reset_state", {"running": False, "last_time": 0.0, "last": None})
    monkeypatch.setattr(ns, "shared_group", lambda force_refresh=False: "G")
    started, release = threading.Event(), threading.Event()

    def slow_reset(reason, prewarm=None):
        started.set()
        release.wait(5)
        raise RuntimeError("reset crashed")          # 例外也要清掉 running
    monkeypatch.setattr(ns, "reset_group", slow_reset)
    assert ns.maybe_reset(ns.RESET_MB + 1, npu_busy=False, llm_idle_sec=None, background=True) is True
    assert started.wait(5) and ns.is_resetting()
    release.set()
    for t in threading.enumerate():
        if t.name == "npu-group-reset":
            t.join(5)
    assert not ns.is_resetting()


def test_shared_group_cache_ttl(monkeypatch):
    monkeypatch.delenv("PI5_NPU_SHARE", raising=False)
    monkeypatch.setattr(ns, "_group_cache", {"time": 0.0, "value": None})
    scans = []
    monkeypatch.setattr(ns, "_scan_hailo_ollama_group", lambda: scans.append(1) or "G1")
    t = {"now": 10_000.0}
    monkeypatch.setattr(ns.time, "monotonic", lambda: t["now"])
    assert ns.shared_group() == "G1" and len(scans) == 1
    t["now"] += ns._GROUP_TTL_SEC - 1
    assert ns.shared_group() == "G1" and len(scans) == 1
    assert ns.shared_group(force_refresh=True) == "G1" and len(scans) == 2
    t["now"] += ns._GROUP_TTL_SEC + 1
    ns.shared_group()
    assert len(scans) == 3


def test_restart_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(ns.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw))
    ns._restart_hailo_ollama()
    assert seen["cmd"] == ["sudo", "-n", "systemctl", "restart", ns.HAILO_OLLAMA_SERVICE]
    assert seen["kw"]["check"] is True                 # 失敗要 raise，reset_group 才會記錄錯誤
