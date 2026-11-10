cat > /tmp/analyze.py <<'PY'
import sys, numpy as np
a=np.fromfile(sys.argv[1], dtype=np.int16); n=len(a); z=(a==0)
d=np.diff(np.concatenate(([0],z.astype(np.int8),[0]))); runs=(np.where(d==-1)[0]-np.where(d==1)[0])/16.0
print(f"  samples={n} ({n/16000:.1f}s) zero={z.mean()*100:.1f}%  runs>=100ms={int((runs>=100).sum())}  max_run={runs.max() if len(runs) else 0:.0f}ms  rms={20*np.log10(np.sqrt((a.astype(np.float32)**2).mean())/32768+1e-9):.1f}dB")
PY
cat > /tmp/scostat.py <<'PY'
import sys, struct, collections
VALID={0x08,0x38,0xC8,0xF8}
f=open(sys.argv[1],'rb'); f.read(16); pk=[]
while True:
    r=f.read(24)
    if len(r)<24: break
    olen,ilen,flags,drops,ts=struct.unpack('>IIIIq',r); d=f.read(ilen)
    if (flags&0xffff)==7 and len(d)>=4:
        h=struct.unpack('<H',d[0:2])[0]; pk.append(((h>>12)&3,d[3:3+d[2]]))
if not pk: print("  sco_rx=0"); sys.exit()
st=collections.Counter(p[0] for p in pk); ok=sum(1 for p in pk if len(p[1])>2 and p[1][0]==1 and p[1][1] in VALID and p[1][2]==0xAD)
print(f"  sco_rx={len(pk)} pkt_status={dict(st)} flagged_bad={100*(len(pk)-st.get(0,0))/len(pk):.0f}%  msbc_header_valid={100*ok/len(pk):.0f}%")
PY
cat > /tmp/loop2.sh <<'INNER'
#!/bin/bash
exec > /tmp/loop2.txt 2>&1
MAC=A0:D1:2A:42:12:34; export XDG_RUNTIME_DIR=/run/user/1000
sudo -n hcitool cmd 0x03 0x005B 0x01 >/dev/null 2>&1
rssi(){ for i in 1 2 3 4 5; do printf "%s " "$(hcitool rssi $MAC 2>&1 | grep -oE '[-0-9]+$')"; sleep 0.4; done; echo; }
src(){ pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"; }
codec(){ pw-dump | python3 -c "import sys,json; print(next(((n['info']['props']).get('api.bluez5.codec') for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'?'))"; }
reconnect(){ bluetoothctl disconnect $MAC >/dev/null 2>&1; sleep 3; for i in $(seq 1 8); do bluetoothctl connect $MAC >/dev/null 2>&1; sleep 3; bluetoothctl info $MAC | grep -q "Connected: yes" && break; done; sleep 2
  DEV=$(pw-dump | python3 -c "import sys,json; print(next((n['id'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')),''))")
  IDX=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next((p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='headset-head-unit'),''))"); [ -n "$IDX" ] && wpctl set-profile $DEV $IDX; sleep 4; }
trial(){ echo "######## $1  $(date +%T)  codec=$(codec)  rssi_delta: $(rssi)"
  S=$(src); sudo -n timeout 14 btmon -w /tmp/l.snoop >/dev/null 2>&1 & sleep 1
  taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$S" -t 10 -f s16le -ac 1 -ar 16000 /tmp/l.raw; sleep 3
  python3 /tmp/analyze.py /tmp/l.raw; sudo -n cat /tmp/l.snoop > /tmp/lc.snoop; python3 /tmp/scostat.py /tmp/lc.snoop
  curl -s -m 60 -H "Content-Type: application/json" -X POST http://127.0.0.1:80/api/voice/record_and_transcribe -d '{"duration_sec":12}' > /tmp/l.json
  python3 -c "import json; d=json.load(open('/tmp/l.json')); print('  TEXT:', d.get('transcribed_text') or d.get('message'))"; }
echo "=== position: NEW (moved close) ==="
trial "A CVSD (current config)"
trial "B CVSD (repeat)"
echo "=== switch to mSBC (temporarily disable CVSD conf) ==="
sudo -n mv /etc/wireplumber/wireplumber.conf.d/51-bluez-cvsd.conf /tmp/51-bluez-cvsd.conf.off; systemctl --user restart wireplumber; sleep 4; reconnect
trial "C mSBC"
trial "D mSBC (repeat)"
echo "=== decide ==="
BAD=$(python3 /tmp/scostat.py /tmp/lc.snoop | grep -oE "msbc_header_valid=[0-9]+" | grep -oE "[0-9]+$")
if [ -n "$BAD" ] && [ "$BAD" -ge 97 ]; then echo "KEEP mSBC (header_valid=${BAD}%)"; else echo "RESTORE CVSD (msbc header_valid=${BAD}%)"; sudo -n mv /tmp/51-bluez-cvsd.conf.off /etc/wireplumber/wireplumber.conf.d/51-bluez-cvsd.conf; systemctl --user restart wireplumber; sleep 4; reconnect; trial "E CVSD (restored)"; fi
echo "ALLDONE $(date +%T)"
INNER
chmod +x /tmp/loop2.sh; rm -f /tmp/loop2.txt; setsid nohup /tmp/loop2.sh >/dev/null 2>&1 </dev/null & echo "launched $!"
