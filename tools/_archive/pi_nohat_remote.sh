echo "===BOOT==="; uname -r; uptime; lspci | grep -ci hailo; echo "(0 = HAT absent)"
echo "===SERVICES==="; systemctl is-active pi5-dispatcher-api.service bluetooth.service hailo-ollama.service
cat > /tmp/analyze.py <<'PY'
import sys, numpy as np
a=np.fromfile(sys.argv[1], dtype=np.int16); n=len(a); z=(a==0)
d=np.diff(np.concatenate(([0],z.astype(np.int8),[0]))); runs=(np.where(d==-1)[0]-np.where(d==1)[0])/16.0
print(f"  samples={n} ({n/16000:.1f}s) zero={z.mean()*100:.1f}%  runs>=20ms={int((runs>=20).sum())} runs>=100ms={int((runs>=100).sum())}  max_run={runs.max() if len(runs) else 0:.0f}ms  rms={20*np.log10(np.sqrt((a.astype(np.float32)**2).mean())/32768+1e-9):.1f}dB")
PY
echo "===BT==="; for i in $(seq 1 15); do bluetoothctl info A0:D1:2A:42:12:34 | grep -q "Connected: yes" && break; bluetoothctl connect A0:D1:2A:42:12:34 >/dev/null 2>&1; sleep 3; done; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Connected"; sleep 3
DEV=$(pw-dump | python3 -c "import sys,json; print(next((n['id'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')),''))")
if [ -n "$DEV" ]; then IDX=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next((p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='headset-head-unit'),''))"); [ -n "$IDX" ] && wpctl set-profile $DEV $IDX; sleep 4; fi
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
[ "$SRC" = "default" ] && { echo "NO BT SOURCE"; exit 0; }
pw-dump | python3 -c "import sys,json; [print('  codec=',(n['info']['props']).get('api.bluez5.codec')) for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')]"
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
for r in 1 2 3; do echo "===TEST $r (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/n$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/n$r.raw; done
echo "===LOAD==="; uptime
