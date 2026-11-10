set -e
cd /home/pi/code_dispatcher
cp -f bluetooth_manager.py /tmp/bluetooth_manager.bak.$(date +%s).py
mv -f /tmp/bluetooth_manager_new.py bluetooth_manager.py
python3 -m py_compile bluetooth_manager.py && echo "remote compile ok"
sed -i 's/def scan_bt_devices(timeout_sec: int = 8)/def scan_bt_devices(timeout_sec: int = 10)/' main.py
bluetoothctl remove C0:D1:2A:42:12:34 2>&1 || true
sudo -n systemctl restart pi5-dispatcher-api.service && echo "restarted"
sleep 4
systemctl is-active pi5-dispatcher-api.service
echo "===API_SCAN==="; curl -s -m 30 -X POST "http://127.0.0.1:80/api/bt/scan" | head -c 1200; echo
echo "===API_PAIR==="; curl -s -m 60 -X POST "http://127.0.0.1:80/api/bt/pair" -H "Content-Type: application/json" -d '{"target":"A0:D1:2A:42:12:34"}' | head -c 1500; echo
echo "===INFO==="; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Name|Paired|Bonded|Trusted|Connected"
echo "===JOURNAL==="; journalctl -u pi5-dispatcher-api.service -n 20 --no-pager -o short-iso | grep -viE "GET /api|WebSocket"
