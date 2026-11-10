cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
srcname(){ pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"; }
codec(){ pw-dump | python3 -c "import sys,json; print(next(((n['info']['props']).get('api.bluez5.codec') for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'?'))"; }
setprof(){ DEV=$(pw-dump | python3 -c "import sys,json; print(next(n['id'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')))"); IDX=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next(p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='$1'))"); wpctl set-profile $DEV $IDX; sleep 4; wpctl set-default $(pw-dump | python3 -c "import sys,json; print(next(n['id'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')))") 2>/dev/null; }
cat > /tmp/scostat2.py <<'PY'
import sys, struct, collections
f=open(sys.argv[1],'rb'); f.read(16); pk=[]
while True:
    r=f.read(24)
    if len(r)<24: break
    olen,ilen,flags,drops,ts=struct.unpack('>IIIIq',r); d=f.read(ilen)
    if (flags&0xffff)==7 and len(d)>=4:
        h=struct.unpack('<H',d[0:2])[0]; pk.append((ts,(h>>12)&3,d[3:3+d[2]]))
print("  sco_rx=",len(pk)," sizes=",dict(collections.Counter(len(p[2]) for p in pk)))
print("  pkt_status_flags:",dict(collections.Counter(p[1] for p in pk)))
print("  all-zero payloads:",sum(1 for p in pk if all(b==0 for b in p[2])), " payload byte-entropy sample:", collections.Counter(pk[len(pk)//2][2]).most_common(3) if pk else None)
PY
sudo -n hcitool cmd 0x03 0x005B 0x01 >/dev/null 2>&1
echo "===SWITCH TO CVSD==="; setprof headset-head-unit-cvsd; SRC=$(srcname); echo "source=$SRC codec=$(codec)"
for r in 1 2; do echo "===CVSD REC $r (10s)==="; sudo -n timeout 14 btmon -w /tmp/cv$r.snoop >/dev/null 2>&1 & sleep 1; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/cv$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 4; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/cv$r.raw; sudo -n cat /tmp/cv$r.snoop > /tmp/cv${r}c.snoop; python3 /tmp/scostat2.py /tmp/cv${r}c.snoop; done
echo "===wireplumber msgs==="; journalctl -S -2m --no-pager 2>/dev/null | grep -iE "bluez5" | sed 's/.*wireplumber\[[0-9]*\]: //' | sort | uniq -c | sort -rn | head -5
echo "===BACK TO MSBC==="; setprof headset-head-unit; echo "codec=$(codec)"
