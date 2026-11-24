#!/bin/bash
# 家用 Wi-Fi 自救——**尚未安裝，等 Andrew 決定**（11-24 早報待決 7）。由 localnote-wifi-selfheal.timer 每 2 分鐘跑一次。
# 11-23 16:2x .228 Wi-Fi 斷線後 17 小時沒自己連回（系統一直在跑），只能到現場斷電重開。
# 規則：
#   - 錄音中（/api/status state=recording）一律跳過：Pi 5 的 Wi-Fi 與藍牙共用 CYW43455，錄音時動 Wi-Fi 可能讓 SCO 掉包（CLAUDE.md 重點一、八）。
#   - 熱點模式（有啟用中的 AP 連線，例如 Pi5-Hotspot）跳過：不能把現場的熱點踢掉。
#   - ping 閘道（沒有預設路由也算失敗）連續失敗 FAIL_BEFORE_UP 次 → nmcli con up 家用 Wi-Fi 設定；
#     之後再連續失敗到 FAIL_BEFORE_RADIO 次 → nmcli radio wifi off／on。成功一次就歸零。
#   - 動作都寫 syslog（logger -t localnote-wifi-selfheal）。計數放 /run（RAM，重開歸零）。
set -u
STATE=${SELFHEAL_STATE:-/run/localnote-wifi-selfheal.count}
API=${SELFHEAL_API:-http://127.0.0.1:8000}
FAIL_BEFORE_UP=${SELFHEAL_FAIL_BEFORE_UP:-2}       # 2 次 × 2 分鐘 ≈ 4 分鐘
FAIL_BEFORE_RADIO=${SELFHEAL_FAIL_BEFORE_RADIO:-5}  # 約 10 分鐘還不行就重開 Wi-Fi 電源
log() { logger -t localnote-wifi-selfheal "$*" 2>/dev/null; echo "$*"; }

state=$(curl -s -m 5 "$API/api/status" 2>/dev/null | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("state",""))
except Exception: print("")' 2>/dev/null)
if [ "$state" = "recording" ]; then echo "skip: recording"; exit 0; fi

active_ap=$(nmcli -t -f NAME,TYPE,DEVICE con show --active 2>/dev/null | while IFS=: read -r name type dev; do
  [ "$type" = "802-11-wireless" ] || continue
  mode=$(nmcli -g 802-11-wireless.mode con show "$name" 2>/dev/null)
  [ "$mode" = "ap" ] && { echo "$name"; break; }
done)
if [ -n "$active_ap" ]; then echo "skip: hotspot $active_ap"; exit 0; fi

gw=$(ip route show default 2>/dev/null | awk '/default/ {print $3; exit}')
if [ -n "$gw" ] && ping -c 3 -W 2 "$gw" > /dev/null 2>&1; then
  [ -f "$STATE" ] && [ "$(cat "$STATE" 2>/dev/null)" != "0" ] && log "ok: gateway $gw reachable again"
  echo 0 > "$STATE"; exit 0
fi

n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE"
log "fail $n: gateway '${gw:-none}' unreachable"

# 家用 Wi-Fi 設定：autoconnect=yes、不是 AP 的 wifi 連線，取第一個
sta=$(nmcli -t -f NAME,TYPE,AUTOCONNECT con show 2>/dev/null | while IFS=: read -r name type auto; do
  [ "$type" = "802-11-wireless" ] && [ "$auto" = "yes" ] || continue
  [ "$(nmcli -g 802-11-wireless.mode con show "$name" 2>/dev/null)" = "ap" ] && continue
  echo "$name"; break
done)

if [ "$n" -ge "$FAIL_BEFORE_RADIO" ]; then
  log "action: radio wifi off/on (fail $n)"
  nmcli radio wifi off; sleep 3; nmcli radio wifi on
  echo $(( FAIL_BEFORE_UP - 1 )) > "$STATE"     # 下一輪若還失敗，先試 con up 再算
elif [ "$n" -ge "$FAIL_BEFORE_UP" ] && [ -n "$sta" ]; then
  log "action: nmcli con up '$sta' (fail $n)"
  nmcli con up "$sta" > /dev/null 2>&1 || log "con up '$sta' failed"
fi
exit 0
