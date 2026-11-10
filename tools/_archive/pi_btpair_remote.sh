cd /tmp/btnew
echo "===SCAN==="
python3 - <<'PY'
import sys, json, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
sys.path.insert(0, "/tmp/btnew")
import bluetooth_manager as bm
devs = bm.scan_devices(10)
print(json.dumps(devs, ensure_ascii=False))
PY
echo "===PAIR==="
python3 - <<'PY'
import sys, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
sys.path.insert(0, "/tmp/btnew")
import bluetooth_manager as bm
ok, msg = bm.pair_and_trust("A0:D1:2A:42:12:34")
print("OK=", ok); print(msg)
PY
echo "===INFO_AFTER==="; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Name|Paired|Bonded|Trusted|Connected"
echo "===WPCTL==="; wpctl status 2>/dev/null | grep -iA3 "Sources:" | head -8
