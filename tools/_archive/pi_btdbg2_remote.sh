echo "===PAIR_500_TRACE==="; journalctl -u pi5-dispatcher-api.service -S "2026-10-22 09:58" -U "2026-10-22 10:02" --no-pager -o short-iso | grep -vE "GET /api|WebSocket" | tail -40
echo "===INFO_C0_42==="; bluetoothctl info C0:D1:2A:42:12:34 2>&1 | grep -vE "UUID|Manufacturer"
echo "===INFO_A0_42==="; bluetoothctl info A0:D1:2A:42:12:34 2>&1 | grep -vE "UUID|Manufacturer"
echo "===BREDR_ONLY_SCAN_12s==="; timeout 16 bluetoothctl --timeout 12 scan bredr 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "NEW|Name:|Alias:|Discovery|Failed|Invalid" | head -40
echo "===INFO_A0_42_AFTER==="; bluetoothctl info A0:D1:2A:42:12:34 2>&1 | grep -E "Name|Alias|Class|Icon|Paired|Trusted|Connected|RSSI"
echo "===BT_CONFIG==="; cat /home/pi/code_dispatcher/data/bluetooth_config.json
echo "===MAIN_CONF==="; grep -vE "^\s*#|^\s*$" /etc/bluetooth/main.conf 2>/dev/null | head -30
