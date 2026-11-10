export XDG_RUNTIME_DIR=/run/user/1000; systemctl --user daemon-reload 2>/dev/null
echo "waiting for headset..."; for i in $(seq 1 15); do bluetoothctl info A0:D1:2A:42:12:34 | grep -q "Connected: yes" && break; bluetoothctl connect A0:D1:2A:42:12:34 >/dev/null 2>&1; sleep 3; done
bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Connected"; sleep 3
pw-dump | python3 -c "
import sys,json
for n in json.load(sys.stdin):
    p=(n.get('info',{}).get('props',{}) or {})
    if p.get('device.api')=='bluez5' and n.get('type','').endswith('Device'): print('DEVICE',n['id'],p.get('device.description'),'profile=',[x.get('name') for x in n['info']['params'].get('Profile',[])])
    if 'bluez_input_internal' in p.get('node.name',''): print('SRC',n['id'],p.get('node.name'),'codec=',p.get('api.bluez5.codec'))
"
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
[ "$SRC" = "default" ] && { echo "NO BT SOURCE - abort"; exit 0; }
for r in 1 2 3; do echo "===TEST $r (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/u$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/u$r.raw; done
