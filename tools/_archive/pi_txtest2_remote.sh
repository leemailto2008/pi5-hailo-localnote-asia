cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
cat > /tmp/nodes.py <<'PY'
import sys,json
nodes=json.load(sys.stdin); src=sink=""
for n in nodes:
    p=(n.get('info',{}).get('props',{}) or {})
    nm=p.get('node.name','')
    if 'bluez_input_internal' in nm: src=nm
    if nm.startswith('bluez_output.') and 'Audio/Sink' in p.get('media.class',''): sink=str(n['id'])+" "+nm
print(src); print(sink)
PY
read -r SRC < <(pw-dump | python3 /tmp/nodes.py | sed -n 1p); SINKLINE=$(pw-dump | python3 /tmp/nodes.py | sed -n 2p); SINKID=${SINKLINE%% *}; echo "source=$SRC sink=$SINKLINE"
[ -z "$SRC" ] && { echo "NO BT SOURCE"; exit 0; }
ffmpeg -nostdin -v error -y -f lavfi -i anullsrc=r=16000:cl=mono -t 16 -ar 16000 -ac 1 /tmp/sil16.wav
echo "===A: capture only (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/a.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/a.raw
echo "===B: capture + pw-play silence -> sink $SINKID (10s)==="
sudo -n timeout 15 btmon -w /tmp/sco3.snoop >/dev/null 2>&1 &
pw-play --target "$SINKID" /tmp/sil16.wav </dev/null >/tmp/pwplay.log 2>&1 & TXPID=$!; sleep 2
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/b.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/b.raw; wait $TXPID 2>/dev/null; cat /tmp/pwplay.log | head -3; sleep 3
sudo -n btmon -r /tmp/sco3.snoop 2>/dev/null > /tmp/sco3.txt; echo "  SCO rx=$(grep -c '> SCO Data RX' /tmp/sco3.txt) tx=$(grep -c '< SCO Data TX' /tmp/sco3.txt)"
echo "===C: capture only again (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/c.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/c.raw
