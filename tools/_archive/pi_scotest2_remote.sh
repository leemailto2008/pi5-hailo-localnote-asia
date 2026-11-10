cat > /tmp/analyze.py <<'PY'
import sys, numpy as np
a=np.fromfile(sys.argv[1], dtype=np.int16); n=len(a); z=(a==0)
d=np.diff(np.concatenate(([0],z.astype(np.int8),[0]))); runs=(np.where(d==-1)[0]-np.where(d==1)[0])/16.0
print(f"  samples={n} ({n/16000:.1f}s) zero={z.mean()*100:.1f}%  runs>=20ms={int((runs>=20).sum())} runs>=100ms={int((runs>=100).sum())}  max_run={runs.max() if len(runs) else 0:.0f}ms  rms={20*np.log10(np.sqrt((a.astype(np.float32)**2).mean())/32768+1e-9):.1f}dB")
PY
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
srcname(){ pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"; }
echo "===WIFI==="; iw dev wlan0 info 2>/dev/null | grep -E "channel|txpower|ssid"; iw dev wlan0 link 2>/dev/null | grep -E "freq|signal|tx bitrate|rx bitrate"
echo "===HCI_FEATURES==="; hciconfig hci0 features 2>/dev/null | tr '\n' ' ' | grep -oE "<[^>]*(SCO|eSCO|EV[345]|EDR eSCO|3 slot eSCO)[^>]*>" | sort -u | tr '\n' ' '; echo; hciconfig hci0 revision 2>/dev/null | head -3; hciconfig hci0 version 2>/dev/null | grep -E "HCI Version|LMP Version"
echo "===BTMON 6s capture during mSBC recording (idle)==="
SRC=$(srcname); echo "source=$SRC"
sudo -n timeout 9 btmon -w /tmp/sco.snoop >/dev/null 2>&1 &
sleep 1; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 6 /tmp/m1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 3
echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/m1.raw
sudo -n btmon -r /tmp/sco.snoop 2>/dev/null > /tmp/sco.txt; echo "  SCO rx packets: $(grep -c '> SCO Data RX' /tmp/sco.txt)  tx: $(grep -c '< SCO Data TX' /tmp/sco.txt)"
echo "  SCO RX length histogram:"; grep -A0 '> SCO Data RX' /tmp/sco.txt | grep -oE "len [0-9]+" | sort | uniq -c | sort -rn | head -5
echo "  packet status flags:"; grep -A1 '> SCO Data RX' /tmp/sco.txt | grep -oE "(Packet status|flags)[^)]*\)?[^ ]*" | sort | uniq -c | head -5
grep -E "Synchronous Connection Complete|eSCO|Air Mode|Transmission Interval|Retransmission|Packet Type|Max Latency" /tmp/sco.txt | sort | uniq -c | head -12
echo "===SWITCH TO CVSD==="
DEV=$(pw-dump | python3 -c "import sys,json; print(next(n['id'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')))")
IDX=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next(p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='headset-head-unit-cvsd'))")
echo "device=$DEV cvsd_idx=$IDX"; wpctl set-profile $DEV $IDX; sleep 3
SRC=$(srcname); echo "source=$SRC"; pw-dump | python3 -c "import sys,json; [print('  node',n['id'],(n['info']['props']).get('node.name'),'codec=',(n['info']['props']).get('api.bluez5.codec')) for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')]"
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/c1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1
echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/c1.raw
echo "===SWITCH BACK TO MSBC==="
IDX2=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next(p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='headset-head-unit'))")
wpctl set-profile $DEV $IDX2; sleep 3; SRC=$(srcname); echo "source=$SRC"; pw-dump | python3 -c "import sys,json; [print('  node',n['id'],(n['info']['props']).get('node.name'),'codec=',(n['info']['props']).get('api.bluez5.codec')) for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')]"
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/m2.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1
echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/m2.raw
wpctl set-default $(pw-dump | python3 -c "import sys,json; print(next(n['id'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')))") 2>/dev/null; echo "default source restored"
