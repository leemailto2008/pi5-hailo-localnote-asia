"""熱點 watchdog／controller 的 nmcli 解析與退回家用 Wi-Fi（subprocess 全換成假的，不碰網路設定）。

2026-11-23（localnote@mac）找到的 bug：排除熱點設定檔用 "ap" not in name.lower()，名稱裡只要有 a、p 相連
（Happy_Home、Taipei-5G、Capital、Laptop…）就被當成熱點排除，watchdog 逾時要退回家用網路時不會試它；
nmcli -t 會把名稱裡的 ":" 跳脫成 "\\:"，直接 split(":") 會把名稱切壞。
"""
import os
import time

import pytest

import hotspot_controller as hc
import hotspot_watchdog as hw

NMCLI = "\n".join([
    "Pi5-Hotspot:802-11-wireless",
    "Taipei-Home-5G:802-11-wireless",
    "Happy_Home:802-11-wireless",
    "Office\\:2F:802-11-wireless",
    "Wired connection 1:802-3-ethernet",
    "lo:loopback",
    "Pi5_AP:802-11-wireless",
    "my-hotspot-test:802-11-wireless",
    "",
])


class _R:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.returncode = stdout, returncode


def test_parse_keeps_wifi_names_with_ap_letters_and_escaped_colon():
    assert hw.parse_sta_profiles(NMCLI) == ["Taipei-Home-5G", "Happy_Home", "Office:2F"]


@pytest.mark.parametrize("name,is_ap", [
    ("Pi5-Hotspot", True), ("my-hotspot-test", True), ("Pi5_AP", True), ("ap", True), ("AP-5G", True),
    ("Happy_Home", False), ("Taipei-Home-5G", False), ("Laptop", False), ("Capital", False), ("netplan-wlan0-My_5G_Guest1", False),
])
def test_is_ap_profile_name(name, is_ap):
    assert hw.is_ap_profile_name(name) is is_ap


def test_get_sta_profiles_appends_defaults_once(monkeypatch):
    monkeypatch.setattr(hw.subprocess, "run", lambda cmd, **kw: _R("My_5G_Guest1:802-11-wireless\nHappy_Home:802-11-wireless"))
    profiles = hw.get_sta_profiles()
    assert profiles[:2] == ["My_5G_Guest1", "Happy_Home"]
    assert profiles.count("My_5G_Guest1") == 1 and "netplan-wlan0-My_5G_Guest1" in profiles


def test_get_sta_profiles_without_nmcli(monkeypatch):
    def missing(cmd, **kw):
        raise FileNotFoundError("nmcli")
    monkeypatch.setattr(hw.subprocess, "run", missing)
    assert hw.get_sta_profiles() == ["netplan-wlan0-My_5G_Guest1", "netplan-wlan0-My_2G_Guest1", "My_5G_Guest1"]


def test_revert_tries_profiles_in_order_until_success(monkeypatch, tmp_path):
    flag = tmp_path / "keepalive.flag"
    flag.write_text("1")
    monkeypatch.setattr(hw, "WATCHDOG_FLAG_FILE", str(flag))
    monkeypatch.setattr(hw, "get_sta_profiles", lambda: ["A", "A", "Happy_Home", "C"])
    cmds = []

    def run(cmd, **kw):
        cmds.append(cmd)
        if cmd[:4] == ["sudo", "nmcli", "connection", "up"]:
            return _R("ok", 0 if cmd[4] == "Happy_Home" else 4)
        return _R()
    monkeypatch.setattr(hw.subprocess, "run", run)
    assert hw.revert_to_sta() is True
    ups = [c[4] for c in cmds if c[:4] == ["sudo", "nmcli", "connection", "up"]]
    assert ups == ["A", "Happy_Home"]                       # 重複的只試一次、成功就停
    assert ["sudo", "nft", "delete", "table", "inet", "hotspot_guard"] in cmds
    assert not flag.exists()


def test_revert_all_fail(monkeypatch):
    monkeypatch.setattr(hw, "get_sta_profiles", lambda: ["A", "B"])

    def run(cmd, **kw):
        if cmd[3] == "up" and cmd[4] == "B":
            raise hw.subprocess.TimeoutExpired(cmd, 25)
        return _R("", 10)
    monkeypatch.setattr(hw.subprocess, "run", run)
    assert hw.revert_to_sta() is False


def test_keepalive_flag(monkeypatch, tmp_path):
    flag = tmp_path / "f"
    monkeypatch.setattr(hw, "WATCHDOG_FLAG_FILE", str(flag))
    assert hw.check_keepalive_flag() is False
    hw.touch_keepalive()
    assert hw.check_keepalive_flag() is True
    old = time.time() - 120
    os.utime(flag, (old, old))
    assert hw.check_keepalive_flag() is False


def test_has_connected_stations(monkeypatch, tmp_path):
    monkeypatch.setattr(hw.subprocess, "run", lambda cmd, **kw: _R("Station aa:bb:cc:dd:ee:ff (on wlan0)"))
    assert hw.has_connected_stations() is True
    monkeypatch.setattr(hw.subprocess, "run", lambda cmd, **kw: _R(""))
    monkeypatch.setattr(hw.os.path, "exists", lambda p: False)
    assert hw.has_connected_stations() is False


def test_controller_find_sta_profile_uses_same_rules(monkeypatch):
    monkeypatch.setattr(hc.subprocess, "run", lambda cmd, **kw: _R("Pi5-Hotspot:802-11-wireless\nHappy_Home:802-11-wireless"))
    assert hc.find_sta_profile() == "Happy_Home"
    monkeypatch.setattr(hc.subprocess, "run", lambda cmd, **kw: _R("Pi5-Hotspot:802-11-wireless"))
    assert hc.find_sta_profile() == "netplan-wlan0-My_5G_Guest1"


def test_bring_up_ap_prefers_5ghz_then_falls_back(monkeypatch):
    """11-27：熱點先 5 GHz ch36，開不起來再 2.4 GHz ch6。"""
    import subprocess
    import hotspot_controller as hc
    calls = []

    def fake_run(cmd, **_k):
        calls.append(cmd)
        if cmd[:4] == ["sudo", "nmcli", "connection", "up"]:
            ok = any(c[-3:] == ["bg", "802-11-wireless.channel", "6"] for c in calls if "modify" in c) and \
                [c for c in calls if "modify" in c][-1][-3] == "bg"
            return subprocess.CompletedProcess(cmd, 0 if ok else 4, "", "" if ok else "no 5GHz")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    res = hc.bring_up_ap()
    mods = [c for c in calls if "modify" in c]
    assert res.returncode == 0 and mods[0][-3:] == ["a", "802-11-wireless.channel", "36"] and mods[1][-3] == "bg"


def test_bring_up_ap_stops_at_first_success(monkeypatch):
    import subprocess
    import hotspot_controller as hc
    calls = []
    monkeypatch.setattr(hc.subprocess, "run", lambda cmd, **_k: (calls.append(cmd), subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    assert hc.bring_up_ap().returncode == 0
    assert [c for c in calls if "modify" in c][-1][-3] == "a" and sum("up" in c for c in calls) == 1


class _Clock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s
        assert self.t < 3600, "watchdog 沒有結束"


def _run_watchdog(monkeypatch, states, clients):
    """states：每一輪 hotspot_active() 的回傳（用完沿用最後一個）。回傳 (有沒有呼叫 revert, 經過秒數)。"""
    clk, reverted, seq = _Clock(), [], list(states)
    monkeypatch.setattr(hw, "time", clk)
    monkeypatch.setattr(hw, "hotspot_active", lambda: seq.pop(0) if len(seq) > 1 else seq[0])
    monkeypatch.setattr(hw, "has_connected_stations", lambda: clients)
    monkeypatch.setattr(hw, "check_keepalive_flag", lambda: False)
    monkeypatch.setattr(hw, "revert_to_sta", lambda: reverted.append(1))
    hw.run_watchdog(180)
    return bool(reverted), clk.t


def test_watchdog_exits_when_hotspot_closed_elsewhere(monkeypatch):
    """11-27：切回家用 Wi-Fi 後 station dump 列的是路由器 (clients=True)，看門狗原本永遠不結束。"""
    reverted, elapsed = _run_watchdog(monkeypatch, [True, True, False], clients=True)
    assert not reverted and elapsed < 60


def test_watchdog_reverts_without_clients(monkeypatch):
    reverted, elapsed = _run_watchdog(monkeypatch, [True], clients=False)
    assert reverted and 180 <= elapsed <= 200


def test_watchdog_never_saw_ap_still_reverts(monkeypatch):
    """熱點一直沒起來：路由器不算熱點客戶端，逾時照常復歸。"""
    reverted, _ = _run_watchdog(monkeypatch, [False], clients=True)
    assert reverted


def test_watchdog_single_glitch_does_not_exit(monkeypatch):
    reverted, elapsed = _run_watchdog(monkeypatch, [True, False, True], clients=False)
    assert reverted and elapsed >= 180


@pytest.mark.parametrize("rc,out,want", [(0, "Pi5-Hotspot\nlo\n", True), (0, "home\nlo\n", False), (8, "", None)])
def test_hotspot_active_parsing(monkeypatch, rc, out, want):
    monkeypatch.setattr(hw.subprocess, "run", lambda cmd, **kw: _R(out, rc))
    assert hw.hotspot_active() is want
