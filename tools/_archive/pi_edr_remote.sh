cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
MAC=A0:D1:2A:42:12:34; echo "rssi: $(hcitool rssi $MAC 2>&1)"
echo "===EDR read==="; sudo -n hcitool cmd 0x03 0x005A | tail -1
echo "===EDR enable==="; sudo -n hcitool cmd 0x03 0x005B 0x01 | tail -1; sudo -n hcitool cmd 0x03 0x005A | tail -1
echo "===REC 10s with EDR on + btmon==="
sudo -n timeout 14 btmon -w /tmp/sn4.snoop >/dev/null 2>&1 & sleep 1
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/e4.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 4; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/e4.raw
sudo -n cat /tmp/sn4.snoop > /tmp/sn4c.snoop; python3 /tmp/scostat.py /tmp/sn4c.snoop | grep -E "sco_rx|pkt_status|valid H2|CRC among valid|per second"
echo "===wireplumber log last 10s==="; journalctl -S "$S" -U "$E" --no-pager 2>/dev/null | grep -iE "bluez5|sco" | sed 's/.*wireplumber\[[0-9]*\]: //' | sort | uniq -c | head -5
echo "rssi: $(hcitool rssi $MAC 2>&1)"
