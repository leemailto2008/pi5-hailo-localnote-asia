cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
MAC=A0:D1:2A:42:12:34
for r in 1 2; do
echo "===REC $r (10s) rssi_before=$(hcitool rssi $MAC 2>&1 | grep -oE '[-0-9]+$')==="
sudo -n timeout 14 btmon -w /tmp/sd$r.snoop >/dev/null 2>&1 & sleep 1
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/d$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 4; echo "  decode_failed=$(cnt "$S" "$E")  rssi_after=$(hcitool rssi $MAC 2>&1 | grep -oE '[-0-9]+$')"; python3 /tmp/analyze.py /tmp/d$r.raw
sudo -n cat /tmp/sd$r.snoop > /tmp/sd${r}c.snoop; python3 /tmp/scostat.py /tmp/sd${r}c.snoop | grep -E "sco_rx|pkt_status|valid H2|CRC among valid"
done
