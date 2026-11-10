echo "===KERNEL==="; uname -r; uptime
echo "===HAILO==="; lsmod | grep hailo; ls /dev/hailo* 2>/dev/null; timeout 10 hailortcli fw-control identify 2>&1 | grep -E "Firmware Version|Device Architecture|error" | head -3
echo "===SERVICES==="; systemctl is-active pi5-dispatcher-api.service hailo-ollama.service ollama.service bluetooth.service pi5-port8000-proxy.service
echo "===HEALTH==="; curl -s -m 8 http://127.0.0.1:80/health | head -c 300; echo
echo "===BT==="; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Connected"
for i in $(seq 1 12); do bluetoothctl info A0:D1:2A:42:12:34 | grep -q "Connected: yes" && break; bluetoothctl connect A0:D1:2A:42:12:34 >/dev/null 2>&1; sleep 3; done; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Connected"; sleep 3
pw-dump | python3 -c "
import sys,json
for n in json.load(sys.stdin):
    p=(n.get('info',{}).get('props',{}) or {})
    if 'bluez_input_internal' in p.get('node.name',''): print('SRC',n['id'],p.get('node.name'),'codec=',p.get('api.bluez5.codec'))
"
cat > /tmp/analyze.py <<'PY'
import sys, numpy as np
a=np.fromfile(sys.argv[1], dtype=np.int16); n=len(a); z=(a==0)
d=np.diff(np.concatenate(([0],z.astype(np.int8),[0]))); runs=(np.where(d==-1)[0]-np.where(d==1)[0])/16.0
print(f"  samples={n} ({n/16000:.1f}s) zero={z.mean()*100:.1f}%  runs>=20ms={int((runs>=20).sum())} runs>=100ms={int((runs>=100).sum())}  max_run={runs.max() if len(runs) else 0:.0f}ms  rms={20*np.log10(np.sqrt((a.astype(np.float32)**2).mean())/32768+1e-9):.1f}dB")
PY
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
[ "$SRC" = "default" ] && { echo "NO BT SOURCE"; exit 0; }
for r in 1 2 3; do echo "===TEST $r (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/p$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/p$r.raw; done
