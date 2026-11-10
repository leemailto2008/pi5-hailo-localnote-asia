pw-dump | python3 -c "
import sys,json
for n in json.load(sys.stdin):
    p=(n.get('info',{}).get('props',{}) or {})
    if p.get('device.api')=='bluez5' and n.get('type','').endswith('Device'): print('DEVICE',n['id'],p.get('device.description'),'profile=',[x.get('name') for x in n['info']['params'].get('Profile',[])],'enum=',[x.get('name') for x in n['info']['params'].get('EnumProfile',[])])
    if 'bluez' in p.get('node.name','') and n.get('type','').endswith('Node'): print('NODE',n['id'],p.get('node.name'),p.get('media.class'),'codec=',p.get('api.bluez5.codec'))
"
DEV=$(pw-dump | python3 -c "import sys,json; print(next((n['id'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')),''))")
if [ -n "$DEV" ]; then IDX=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next((p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='headset-head-unit'),''))"); echo "device=$DEV hfp_idx=$IDX"; [ -n "$IDX" ] && wpctl set-profile $DEV $IDX; sleep 4; fi
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
[ "$SRC" = "default" ] && { echo "NO BT SOURCE"; exit 0; }
wpctl set-default $(pw-dump | python3 -c "import sys,json; print(next(n['id'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')))") 2>/dev/null
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
for r in 1 2 3; do echo "===TEST $r (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/p$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/p$r.raw; done
echo "===LOAD==="; uptime
