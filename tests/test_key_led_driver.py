"""gpio_driver/key_led_driver 的邏輯（gpiozero 換成假的 Button／LED，subprocess／sleep 換成假的）：
不碰真的 GPIO、不改網路設定。

2026-11-23（localnote@mac）找到的 bug：check_is_hotspot_active 用 "ap" in conn.lower() 判斷熱點，
wlan0 連的是 Happy_Home、Taipei-5G、Laptop 這類家用 Wi-Fi 時被當成熱點 → LED5 恆亮、按 KEY5 反而去「切回 STA」
而不是開熱點（同 S2 修過的 hotspot_watchdog）；nmcli -t 會把名稱裡的 ":" 跳脫成 "\\:"，直接 split(":") 會切壞。
"""
import os
import sys
import threading
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeLED:
    def __init__(self, pin, initial_value=False):
        self.pin, self.is_lit, self.closed, self.history = pin, bool(initial_value), False, []

    def on(self):
        self.is_lit = True
        self.history.append(1)

    def off(self):
        self.is_lit = False
        self.history.append(0)

    def close(self):
        self.closed = True


class FakeButton:
    def __init__(self, pin, pull_up=True, bounce_time=None):
        self.pin, self.pull_up, self.bounce_time, self.closed = pin, pull_up, bounce_time, False
        self.when_pressed = self.when_released = None

    def close(self):
        self.closed = True


@pytest.fixture(scope="module")
def kld():
    fake = types.ModuleType("gpiozero")
    fake.Button, fake.LED = FakeButton, FakeLED
    saved = sys.modules.get("gpiozero")
    sys.modules["gpiozero"] = fake
    sys.path.insert(0, os.path.join(ROOT, "gpio_driver"))
    try:
        import key_led_driver
        yield key_led_driver
    finally:
        sys.path.remove(os.path.join(ROOT, "gpio_driver"))
        sys.modules.pop("key_led_driver", None)
        if saved is None:
            sys.modules.pop("gpiozero", None)
        else:
            sys.modules["gpiozero"] = saved


class _R:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def _nmcli(conn):
    return "\n".join(["eth0:ethernet:unavailable:", f"wlan0:wifi:connected:{conn}", "lo:loopback:connected (externally):lo"])


@pytest.mark.parametrize("conn,expect", [
    ("Pi5-Hotspot", True), ("raspi543_AI", True), ("Pi5_AP", True), ("AP-5G", True),
    ("Happy_Home", False), ("Taipei-Home-5G", False), ("Laptop", False), ("netplan-wlan0-My_5G_Guest1", False),
    ("Office\\:AP", True), ("Office\\:2F", False), ("", False),
])
def test_check_is_hotspot_active(kld, monkeypatch, conn, expect):
    monkeypatch.setattr(kld.subprocess, "run", lambda cmd, **kw: _R(_nmcli(conn)))
    assert kld.check_is_hotspot_active() is expect


def test_check_is_hotspot_active_without_nmcli_or_wlan0(kld, monkeypatch):
    def missing(cmd, **kw):
        raise FileNotFoundError("nmcli")
    monkeypatch.setattr(kld.subprocess, "run", missing)
    assert kld.check_is_hotspot_active() is False
    monkeypatch.setattr(kld.subprocess, "run", lambda cmd, **kw: _R("eth0:ethernet:connected:Wired"))
    assert kld.check_is_hotspot_active() is False


def test_follow_and_toggle_pairs(kld):
    cfg = kld.PIN_MAPPING[0]
    p = kld.KeyLedPair(cfg, mode="follow", bounce_time=0.1)
    assert (p.button.pin, p.led.pin, p.button.bounce_time) == (cfg["key_pin"], cfg["led_pin"], 0.1)
    p.button.when_pressed()
    assert p.led.is_lit
    p.button.when_released()
    assert not p.led.is_lit
    t = kld.KeyLedPair(cfg, mode="toggle")
    assert t.button.when_released is None
    t.button.when_pressed()
    t.button.when_pressed()
    t.button.when_pressed()
    assert t.led.is_lit and t.is_toggled_on
    t.close()
    assert t.led.closed and t.button.closed and not t.led.is_lit


@pytest.fixture
def hotspot(kld, monkeypatch):
    """HotspotKeyLedPair，背景同步執行緒不跑（_background_sync_loop 換成空函式）、sleep 不等。"""
    state = {"ap": False, "cmds": [], "popen": []}
    monkeypatch.setattr(kld, "check_is_hotspot_active", lambda: state["ap"])
    monkeypatch.setattr(kld.HotspotKeyLedPair, "_background_sync_loop", lambda self: None)

    def run(cmd, **kw):
        state["cmds"].append(cmd)
        if cmd[:4] == ["sudo", "nmcli", "connection", "up"] or "--revert" in cmd:
            state["ap"] = state.get("next_ap", not state["ap"])
        return _R("ok")
    monkeypatch.setattr(kld.subprocess, "run", run)
    monkeypatch.setattr(kld.subprocess, "Popen", lambda cmd, **kw: state["popen"].append(cmd))
    monkeypatch.setattr(kld, "time", types.SimpleNamespace(sleep=lambda s: None))
    h = kld.HotspotKeyLedPair(kld.PIN_MAPPING[4])
    state["pair"] = h
    yield state
    h.close()


def test_toggle_sta_to_ap(hotspot):
    h = hotspot["pair"]
    assert not h.led.is_lit
    h._execute_toggle_workflow()
    cmds = hotspot["cmds"]
    assert ["sudo", "nmcli", "connection", "up", "Pi5-Hotspot"] in cmds
    assert ["sudo", "nft", "-f", "/etc/nftables.hotspot_guard.nft"] in cmds
    assert hotspot["popen"][0][-2:] == ["--timeout", "180"]            # 先開 watchdog 再開熱點
    assert h.led.is_lit and h.is_transitioning is False


def test_toggle_ap_to_sta(hotspot):
    hotspot["ap"] = True
    h = hotspot["pair"]
    h._execute_toggle_workflow()
    assert ["sudo", "nft", "delete", "table", "inet", "hotspot_guard"] in hotspot["cmds"]
    assert any("--revert" in c for c in hotspot["cmds"])
    assert not h.led.is_lit and not h.is_transitioning


def test_toggle_timeout_and_exception_still_settle_led(hotspot, kld, monkeypatch):
    hotspot["next_ap"] = False                                           # 開熱點失敗：一直是 STA
    h = hotspot["pair"]
    h._execute_toggle_workflow()
    assert not h.led.is_lit and not h.is_transitioning

    def boom(cmd, **kw):
        raise OSError("sudo missing")
    monkeypatch.setattr(kld.subprocess, "run", boom)
    h._execute_toggle_workflow()
    assert not h.is_transitioning                                        # 例外也要解除切換中


def test_duplicate_press_is_ignored_while_transitioning(hotspot, kld, monkeypatch):
    h = hotspot["pair"]
    started = []
    monkeypatch.setattr(kld.threading, "Thread", lambda target, daemon=None, **kw: types.SimpleNamespace(
        start=lambda: started.append(target)))
    h._on_button_pressed()
    h._on_button_pressed()                                               # 切換中再按：不再開工作
    assert len(started) == 1 and h.is_transitioning


def test_blinking_starts_and_stops(kld, hotspot):
    h = hotspot["pair"]
    h._start_blinking()
    assert h._blink_thread is not None
    h._stop_blinking()
    assert h._blink_thread is None and len(h.led.history) >= 1


def test_driver_initialize_self_test_shutdown(kld, monkeypatch, hotspot):
    monkeypatch.setattr(kld, "HotspotKeyLedPair", lambda cfg, bounce_time=0.05: hotspot["pair"])
    d = kld.KeyLedDriver(mode="toggle", bounce_time=0.02)
    d.initialize()
    assert [p.cfg["id"] for p in d.standard_pairs] == [1, 2, 3, 4]
    assert all(p.mode == "toggle" for p in d.standard_pairs)
    d.self_test(cycles=1)
    assert all(not p.led.is_lit and p.led.history for p in d.standard_pairs)   # 追逐測試後全部熄滅
    d.shutdown()
    assert all(p.led.closed for p in d.standard_pairs) and d._running is False


@pytest.mark.parametrize("exc", ["timeout", "oserror"])
def test_toggle_falls_back_to_24ghz_when_5ghz_hangs(hotspot, kld, monkeypatch, exc):
    """11-27：5 GHz 的 nmcli up 逾時 (國家碼、驅動卡住) 原本直接拋出，不試 2.4 GHz (同 hotspot_controller P1)。"""
    band = []

    def run(cmd, **kw):
        hotspot["cmds"].append(cmd)
        if "modify" in cmd:
            band.append(cmd[cmd.index("802-11-wireless.band") + 1])
        if cmd[:4] == ["sudo", "nmcli", "connection", "up"]:
            if band[-1] == "a":
                raise kld.subprocess.TimeoutExpired(cmd, 25) if exc == "timeout" else OSError("busy")
            hotspot["ap"] = True
        return _R("ok")
    monkeypatch.setattr(kld.subprocess, "run", run)
    hotspot["pair"]._execute_toggle_workflow()
    assert band == ["a", "bg"] and hotspot["pair"].led.is_lit
    assert ["sudo", "nft", "-f", "/etc/nftables.hotspot_guard.nft"] in hotspot["cmds"]


@pytest.mark.parametrize("exc", [None, "timeout"])
def test_toggle_reverts_to_home_wifi_when_both_bands_fail(hotspot, kld, monkeypatch, exc):
    """P8：5 GHz 和 2.4 GHz 都開不起來時，馬上切回家用 Wi-Fi（同 hotspot_controller 的 Auto-reverting），
    不要等 watchdog 的 180 s：這段時間既沒熱點也沒家用網路。"""
    def run(cmd, **kw):
        hotspot["cmds"].append(cmd)
        if cmd[:4] == ["sudo", "nmcli", "connection", "up"]:
            if exc:
                raise kld.subprocess.TimeoutExpired(cmd, 25)
            return types.SimpleNamespace(returncode=10, stdout="", stderr="no device")
        return _R("ok")
    monkeypatch.setattr(kld.subprocess, "run", run)
    hotspot["pair"]._execute_toggle_workflow()
    cmds = hotspot["cmds"]
    assert any("--revert" in c for c in cmds)
    assert ["sudo", "nft", "-f", "/etc/nftables.hotspot_guard.nft"] not in cmds
    assert not hotspot["pair"].led.is_lit and not hotspot["pair"].is_transitioning
