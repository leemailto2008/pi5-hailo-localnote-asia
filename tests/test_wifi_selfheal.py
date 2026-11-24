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
    _stub(b, "systemctl", "exit 3")                         # 服務沒在跑 (curl 的 stub 一定有回應，用不到)
    active = "802-11-wireless:wlan0:Pi5-Hotspot" if active_ap else "802-11-wireless:wlan0:netplan-wlan0-My_5G_Guest1"
    _stub(b, "nmcli", f"""echo "$*" >> {calls}
case "$*" in
  "-t -f TYPE,DEVICE,NAME con show --active") echo '{active}';;
  "-t -f TYPE,AUTOCONNECT,NAME con show") printf '802-11-wireless:yes:netplan-wlan0-My_5G_Guest1\\n802-11-wireless:no:Pi5-Hotspot\\n';;
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


def _env2(tmp_path, *, curl_body, svc_active, sta_name="Home\\:5G", ap_name="Pi5-Hotspot", ap_active=False):
    """N12：nmcli -t 會把名稱裡的「:」寫成「\\:」；curl 可以模擬 API 沒回應 (exit 28)；systemctl is-active 可控。"""
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    calls = tmp_path / "calls.log"
    _stub(b, "curl", curl_body)
    _stub(b, "systemctl", "exit 0" if svc_active else "exit 3")
    _stub(b, "ip", "echo 'default via 192.168.50.1 dev wlan0'")
    _stub(b, "ping", "exit 1")
    _stub(b, "logger", "true")
    _stub(b, "sleep", "true")
    cur = ap_name if ap_active else sta_name                    # nmcli -t 的寫法（「:」寫成「\\:」）
    plain_sta, plain_ap = sta_name.replace("\\:", ":"), ap_name.replace("\\:", ":")
    _stub(b, "nmcli", f"""echo "$*" >> {calls}
if [ "$1" = "-t" ]; then
  case "$3" in
    NAME,TYPE,DEVICE) echo '{cur}:802-11-wireless:wlan0';;
    TYPE,DEVICE,NAME) echo '802-11-wireless:wlan0:{cur}';;
    NAME,TYPE,AUTOCONNECT) printf '%s\\n' '{sta_name}:802-11-wireless:yes' '{ap_name}:802-11-wireless:no';;
    TYPE,AUTOCONNECT,NAME) printf '%s\\n' '802-11-wireless:yes:{sta_name}' '802-11-wireless:no:{ap_name}';;
  esac
elif [ "$1" = "-g" ]; then
  if [ "$5" = "{plain_ap}" ]; then echo ap; else echo infrastructure; fi
fi""")
    st = tmp_path / "count"
    st.write_text("1", encoding="utf-8")
    env = dict(os.environ, PATH=f"{b}:{os.environ['PATH']}", SELFHEAL_STATE=str(st))
    return env, calls, st, plain_sta


def test_con_up_uses_full_name_with_colon(tmp_path):
    # 家用 Wi-Fi 設定名稱有「:」（nmcli -t 寫成 Home\\:5G）：con up 要用完整的「Home:5G」，不能切成「Home\\」
    env, calls, st, plain = _env2(tmp_path, curl_body="echo '{\"state\": \"idle\"}'", svc_active=True)
    _run(env)
    assert _nm_actions(calls) == [f"con up {plain}"], _nm_actions(calls)


def test_hotspot_with_colon_in_name_is_detected(tmp_path):
    env, calls, st, _ = _env2(tmp_path, curl_body="echo '{\"state\": \"idle\"}'", svc_active=True, ap_name="Pi5\\:AP", ap_active=True)
    r = _run(env)
    assert "skip: hotspot" in r.stdout and _nm_actions(calls) == []


def test_api_not_answering_while_service_active_skips(tmp_path):
    # API 沒回應 (curl 逾時) 但服務還在跑：可能正在錄音、event loop 忙，不能動 Wi-Fi
    env, calls, st, _ = _env2(tmp_path, curl_body="exit 28", svc_active=True)
    r = _run(env)
    assert "skip: api" in r.stdout and _nm_actions(calls) == [] and st.read_text() == "1"


def test_api_down_because_service_stopped_still_heals(tmp_path):
    env, calls, st, plain = _env2(tmp_path, curl_body="exit 7", svc_active=False)
    _run(env)
    assert _nm_actions(calls) == [f"con up {plain}"]
