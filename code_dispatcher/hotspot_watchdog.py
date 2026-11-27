# f:\12_prj_raspi5\code_dispatcher\hotspot_watchdog.py
"""
Fail-Safe Hotspot Watchdog for Raspberry Pi 5.
Ensures that if Pi 5 is switched to standalone Hotspot mode (AP),
it will NEVER get bricked or permanently stranded.
If no client connects within TIMEOUT seconds, it automatically reverts to home Wi-Fi.
"""

import os
import re
import time
import subprocess
import sys
import argparse
import logging
_log = logging.getLogger(__name__)

WATCHDOG_FLAG_FILE = "/tmp/hotspot_keepalive.flag"
STA_PROFILE = "My_5G_Guest1"
AP_PROFILE = "Pi5-Hotspot"

def has_connected_stations() -> bool:
    """Check if any mobile phone or device is connected to the AP."""
    try:
        res = subprocess.run(["iw", "dev", "wlan0", "station", "dump"], capture_output=True, text=True, timeout=3)
        if "Station " in res.stdout:
            return True
    except Exception as _exc:
        _log.debug("hotspot_watchdog.py:25 略過：%s", _exc)

    # Check DHCP leases
    lease_paths = [
        "/run/NetworkManager/dnsmasq-wlan0.leases",
        "/var/lib/misc/dnsmasq.leases",
        "/var/lib/NetworkManager/dnsmasq-wlan0.leases"
    ]
    for lp in lease_paths:
        if os.path.exists(lp) and os.path.getsize(lp) > 0:
            return True
    return False

def hotspot_active():
    """熱點設定檔現在有沒有啟用；nmcli 讀不到回 None (不知道)。"""
    try:
        res = subprocess.run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        _log.warning("[Watchdog] cannot read active connections: %s", e)
        return None
    if res.returncode != 0:
        return None
    return AP_PROFILE in res.stdout.splitlines()


def check_keepalive_flag() -> bool:
    """Check if Web UI or user sent a keepalive signal within the last 60 seconds."""
    if os.path.exists(WATCHDOG_FLAG_FILE):
        mtime = os.path.getmtime(WATCHDOG_FLAG_FILE)
        if time.time() - mtime < 60:
            return True
    return False

def touch_keepalive():
    """Touch keepalive file."""
    with open(WATCHDOG_FLAG_FILE, "w") as f:
        f.write(str(time.time()))

_AP_TOKEN_RE = re.compile(r"(?<![a-z0-9])ap(?![a-z0-9])")


def is_ap_profile_name(name: str) -> bool:
    """熱點 (AP) 設定檔：名稱含 hotspot，或有獨立的 ap 字詞 (Pi5_AP、AP-5G)。
    2026-11-23 修正：原本是 "ap" in name，Happy_Home、Taipei-5G、Laptop 這類家用 Wi-Fi 也被排除。"""
    n = name.lower()
    return "hotspot" in n or bool(_AP_TOKEN_RE.search(n))


def parse_sta_profiles(nmcli_terse: str) -> list:
    """解析 `nmcli -t -f NAME,TYPE connection show`，回傳 Wi-Fi 用戶端 (非熱點) 設定檔名稱。
    -t 輸出會把名稱裡的 ":" 跳脫成 "\\:"、"\\" 跳脫成 "\\\\"。"""
    profiles = []
    for line in nmcli_terse.strip().splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 2:
            continue
        name = parts[0].replace("\\:", ":").replace("\\\\", "\\")
        if "wireless" in parts[1] and not is_ap_profile_name(name):
            profiles.append(name)
    return profiles


def get_sta_profiles() -> list:
    """Dynamically get all configured Wi-Fi client connections from nmcli."""
    profiles = []
    try:
        res = subprocess.run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], capture_output=True, text=True, timeout=5)
        profiles = parse_sta_profiles(res.stdout)
    except Exception as _exc:
        _log.debug("hotspot_watchdog.py:65 略過：%s", _exc)
    
    # Priority defaults
    defaults = ["netplan-wlan0-My_5G_Guest1", "netplan-wlan0-My_2G_Guest1", "My_5G_Guest1"]
    for d in defaults:
        if d not in profiles:
            profiles.append(d)
    return profiles

def revert_to_sta():
    """Safely revert Pi 5 back to home Wi-Fi station mode."""
    candidates = get_sta_profiles()
    seen = set()
    unique_candidates = [x for x in candidates if not (x in seen or seen.add(x))]

    for prof in unique_candidates:
        print(f"[Watchdog] Reverting Pi 5 back to home Wi-Fi: {prof}...")
        try:
            res = subprocess.run(["sudo", "nmcli", "connection", "up", prof], capture_output=True, text=True, timeout=25)
            if res.returncode == 0:
                print(f"[Watchdog] Successfully connected to {prof}: {res.stdout.strip()}")
                subprocess.run(["sudo", "nft", "delete", "table", "inet", "hotspot_guard"], capture_output=True)
                if os.path.exists(WATCHDOG_FLAG_FILE):
                    os.remove(WATCHDOG_FLAG_FILE)
                return True
        except Exception as e:
            print(f"[Watchdog] Revert error on {prof}: {e}")
    return False

def run_watchdog(timeout_sec: int = 180):
    print(f"[Watchdog] Starting Fail-Safe Hotspot Watchdog with {timeout_sec}s timeout.")
    start_time = time.time()

    # Wait 10 seconds for initial AP stabilization
    time.sleep(10)

    seen_ap, gone = False, 0
    while True:
        # 熱點已經被別的方式關掉 (網頁／按鍵切回、手動 nmcli) 就結束。11-27 .228：切回家用 Wi-Fi 後 iw station dump
        # 列的是家用路由器，被當成「有人連著熱點」→ 看門狗永遠不結束，行程一直留著
        active = hotspot_active()
        if active:
            seen_ap, gone = True, 0
        elif active is False and seen_ap:
            gone += 1
            if gone >= 2:       # 連續兩次 (約 10 s) 都不在，避免切換頻段的瞬間誤判
                print("[Watchdog] Hotspot is no longer active. Watchdog exits.")
                return

        elapsed = time.time() - start_time
        remaining = timeout_sec - elapsed

        # Check if connected or keepalive active
        has_client = active is not False and has_connected_stations()   # 不在熱點模式時 station dump 是上游路由器
        has_alive = check_keepalive_flag()

        if has_client or has_alive:
            # Active user connected! Reset countdown or extend
            print(f"[Watchdog] Client active (station={has_client}, keepalive={has_alive}). Watchdog paused.")
            start_time = time.time()  # Reset countdown as long as user is connected
        else:
            print(f"[Watchdog] No client connected. Revert countdown: {remaining:.0f}s remaining...")

        if remaining <= 0:
            print("[Watchdog] Timeout expired with no connected clients! Auto-reverting...")
            revert_to_sta()
            break

        time.sleep(5)

if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)     # 輸出接到服務的 journal：不逐行送出的話整段都看不到
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=180, help="Timeout in seconds before auto-reverting")
    parser.add_argument("--revert", action="store_true", help="Immediately revert to STA")
    parser.add_argument("--touch", action="store_true", help="Touch keepalive flag")
    args = parser.parse_args()

    if args.revert:
        revert_to_sta()
    elif args.touch:
        touch_keepalive()
    else:
        run_watchdog(args.timeout)
