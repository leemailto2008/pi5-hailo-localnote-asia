set -e
mkdir -p /tmp/btnew && mv -f /tmp/bluetooth_manager_new.py /tmp/btnew/bluetooth_manager.py
cd /tmp/btnew
echo "===SCAN_TEST==="
python3 - <<'PY'
import sys, json, time, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
sys.path.insert(0, "/tmp/btnew")
import bluetooth_manager as bm
t=time.time()
devs = bm.scan_devices(10)
print(f"scan took {time.time()-t:.1f}s")
print(json.dumps(devs, ensure_ascii=False, indent=1))
PY
echo "===SESSION_RAW_TEST==="
python3 - <<'PY'
import sys; sys.path.insert(0, "/tmp/btnew")
import bluetooth_manager as bm
with bm.BluetoothctlSession() as s:
    s.send("show")
    print("show ->", s.wait_for([r"Powered:"], 3))
    s.send("scan bredr"); print("start ->", s.wait_for([r"Discovery started", r"Failed"], 4))
    print("rich ->", s.wait_for([r"RichChip"], 12))
    s.send("scan off"); print("stop ->", s.wait_for([r"Discovery stopped", r"Discovering: no"], 3))
    print("lines:", len(s.lines_since(0)))
PY
