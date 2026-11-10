echo "===A_NATIVE_12s==="; timeout 16 bluetoothctl --timeout 12 scan bredr 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "NEW|Discovery" 
echo "===B_SESSION_12s==="
python3 - <<'PY'
import sys; sys.path.insert(0, "/tmp/btnew")
import bluetooth_manager as bm, time
with bm.BluetoothctlSession() as s:
    c = s.cursor()
    s.send("scan bredr"); print("start ->", s.wait_for([r"Discovery started", r"Failed"], 4))
    time.sleep(12)
    s.send("scan off"); s.wait_for([r"Discovery stopped", r"Discovering: no"], 3)
    for l in s.lines_since(c):
        if "Device" in l or "Discover" in l: print(repr(l))
PY
