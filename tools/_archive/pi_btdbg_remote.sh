echo "===BLUEZ_VER==="; bluetoothctl --version; bluetoothd --version 2>/dev/null
echo "===SHOW==="; bluetoothctl show
echo "===DEVICES_BEFORE==="; bluetoothctl devices
echo "===REC_ACTIVE==="; curl -s -m 3 http://127.0.0.1:80/api/status | head -c 200; echo
echo "===RAW_SCAN_10s (stdout piped, like the app)==="; timeout 14 bluetoothctl --timeout 10 scan on 2>&1 | cat -A | grep -vE "RSSI|ManufacturerData|TxPower|UUID" | head -80
echo "===DEVICES_AFTER==="; bluetoothctl devices
echo "===RICHCHIP_INFO==="; for m in $(bluetoothctl devices | awk '{print $2}'); do n=$(bluetoothctl info $m | grep -iE "Name:|Alias:" | head -1); echo "$m $n"; done | grep -i rich
echo "===API_SCAN==="; time curl -s -m 25 -X POST "http://127.0.0.1:80/api/bt/scan?timeout_sec=8" | head -c 1500; echo
echo "===JOURNAL_BT==="; journalctl -u pi5-dispatcher-api.service -S -30m --no-pager -o short-iso | grep -iE "scan|bluetooth|bt" | tail -20
echo "===BTD_ERR==="; journalctl -u bluetooth.service -S -30m --no-pager -o short-iso | tail -15
