echo "===BREDR_ONLY_SCAN_12s==="; timeout 16 bluetoothctl --timeout 12 scan bredr 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "NEW|Name:|Alias:|Discovery|Failed" | head -40
echo "===INFO_A0_42==="; bluetoothctl info A0:D1:2A:42:12:34 2>&1 | grep -E "Device|Name|Alias|Class|Icon|Paired|Trusted|Connected|RSSI"
echo "===AUTO_SCAN_8s==="; timeout 12 bluetoothctl --timeout 8 scan on 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "NEW|Name:" | grep -viE "^\[NEW\] Device ([0-9A-F]{2}:){5}[0-9A-F]{2} ([0-9A-F]{2}-){5}[0-9A-F]{2}$" | head -30
