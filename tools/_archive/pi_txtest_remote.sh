cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
SINK=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('node.name','').startswith('bluez_output.') and 'Audio/Sink' in (n['info']['props']).get('media.class','')),'')))"); echo "sink=$SINK"
[ "$SRC" = "default" ] && { echo "NO BT SOURCE"; exit 0; }
echo "===A: capture only (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/a.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/a.raw
echo "===B: capture + silence TX to sink (10s)==="
ffmpeg -nostdin -v error -f lavfi -i anullsrc=r=16000:cl=mono -t 14 -f pulse -device "$SINK" "silence-keepalive" </dev/null >/dev/null 2>&1 &
TXPID=$!; sleep 2
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/b.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/b.raw; wait $TXPID 2>/dev/null
echo "===C: capture only again (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/c.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/c.raw
echo "===D: capture + silence TX, btmon count (8s)==="
sudo -n timeout 12 btmon -w /tmp/sco2.snoop >/dev/null 2>&1 &
ffmpeg -nostdin -v error -f lavfi -i anullsrc=r=16000:cl=mono -t 12 -f pulse -device "$SINK" "silence-keepalive" </dev/null >/dev/null 2>&1 &
TXPID=$!; sleep 2; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 8 /tmp/d.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/d.raw; wait $TXPID 2>/dev/null; sleep 3
sudo -n btmon -r /tmp/sco2.snoop 2>/dev/null > /tmp/sco2.txt; echo "  SCO rx=$(grep -c '> SCO Data RX' /tmp/sco2.txt) tx=$(grep -c '< SCO Data TX' /tmp/sco2.txt)"
