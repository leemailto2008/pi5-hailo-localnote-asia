"""deploy/wifi-selfheal/localnote-wifi-selfheal.sh 的離線行為測試（11-24；尚未安裝，等 Andrew 決定）。
curl／nmcli／ip／ping／logger／sleep 換成 PATH 最前面的 stub，nmcli 的呼叫記到 calls.log 檢查做了什麼。
需要 POSIX bash（Windows 跳過；Pi／Mac 會跑）。"""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "deploy", "wifi-selfheal", "localnote-wifi-selfheal.sh")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="需要 POSIX bash（Windows 跳過）")


def _stub(bin_dir, name, body):
    p = bin_dir / name
    p.write_text("#!/bin/bash\n" + body + "\n", encoding="utf-8")
    p.chmod(0o755)


def _env(tmp_path, *, state="idle", gw="192.168.50.1", ping_ok=False, active_ap=False, count=None):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    calls = tmp_path / "calls.log"
    _stub(b, "curl", f"echo '{{\"state\": \"{state}\"}}'")
    _stub(b, "ip", f"echo 'default via {gw} dev wlan0'" if gw else "true")
    _stub(b, "ping", "exit 0" if ping_ok else "exit 1")
    _stub(b, "logger", "true")
    _stub(b, "sleep", "true")
    active = "Pi5-Hotspot:802-11-wireless:wlan0" if active_ap else "netplan-wlan0-My_5G_Guest1:802-11-wireless:wlan0"
    _stub(b, "nmcli", f"""echo "$*" >> {calls}
case "$*" in
  "-t -f NAME,TYPE,DEVICE con show --active") echo '{active}';;
  "-t -f NAME,TYPE,AUTOCONNECT con show") printf 'netplan-wlan0-My_5G_Guest1:802-11-wireless:yes\\nPi5-Hotspot:802-11-wireless:no\\n';;
  "-g 802-11-wireless.mode con show Pi5-Hotspot") echo ap;;
  "-g 802-11-wireless.mode con show"*) echo infrastructure;;
esac""")
    st = tmp_path / "count"
    if count is not None:
        st.write_text(str(count), encoding="utf-8")
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", SELFHEAL_STATE=str(st))
    return env, calls, st


def _run(env):
    return subprocess.run([BASH, SCRIPT], env=env, capture_output=True, text=True, timeout=30)


def _nm_actions(calls):
    if not calls.exists():
        return []
    return [l for l in calls.read_text(encoding="utf-8").splitlines() if l.startswith(("con up", "radio"))]


def test_skips_while_recording(tmp_path):
    env, calls, st = _env(tmp_path, state="recording", count=4)
    r = _run(env)
    assert "skip: recording" in r.stdout and _nm_actions(calls) == [] and st.read_text() == "4"


def test_skips_in_hotspot_mode(tmp_path):
    env, calls, _ = _env(tmp_path, active_ap=True, count=4)
    assert "skip: hotspot Pi5-Hotspot" in _run(env).stdout and _nm_actions(calls) == []


def test_gateway_ok_resets_counter(tmp_path):
    env, calls, st = _env(tmp_path, ping_ok=True, count=3)
    _run(env)
    assert st.read_text().strip() == "0" and _nm_actions(calls) == []


def test_first_failure_only_counts(tmp_path):
    env, calls, st = _env(tmp_path)
    _run(env)
    assert st.read_text().strip() == "1" and _nm_actions(calls) == []


def test_second_failure_brings_home_wifi_up(tmp_path):
    env, calls, st = _env(tmp_path, count=1)
    _run(env)
    assert st.read_text().strip() == "2"
    assert _nm_actions(calls) == ["con up netplan-wlan0-My_5G_Guest1"]      # 不會挑到 Pi5-Hotspot（autoconnect no、mode ap）


def test_no_default_route_counts_as_failure(tmp_path):
    env, calls, _ = _env(tmp_path, gw="", count=1)
    _run(env)
    assert _nm_actions(calls) == ["con up netplan-wlan0-My_5G_Guest1"]


def test_many_failures_power_cycle_radio(tmp_path):
    env, calls, st = _env(tmp_path, count=4)
    _run(env)
    assert _nm_actions(calls) == ["radio wifi off", "radio wifi on"]
    assert st.read_text().strip() == "1"                                      # 下一輪失敗先試 con up
