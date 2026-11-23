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
