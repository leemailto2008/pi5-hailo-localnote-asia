cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
MAC=A0:D1:2A:42:12:34
echo "===LINK POLICY / MODE now==="; sudo -n hcitool lp $MAC 2>&1; hcitool con
echo "===A: btmon during 10s rec (policy as-is)==="
sudo -n timeout 14 btmon -w /tmp/sn1.snoop >/dev/null 2>&1 & sleep 1
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/s1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 4; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/s1.raw
sudo -n btmon -r /tmp/sn1.snoop 2>/dev/null > /tmp/sn1.txt
echo "  events:"; grep -E "^(<|>|=) HCI Event|^> HCI Event" /tmp/sn1.txt | grep -vE "Number of Completed|Command Complete|Command Status" | sed 's/ *#.*//' | sort | uniq -c | sort -rn | head -8
echo "  mode/role/sniff lines:"; grep -iE "Mode Change|Sniff|Role Change|Link Supervision|QoS|Flow Spec|Max Slots|Connection Packet Type" /tmp/sn1.txt | head -12
echo "  SCO RX count: $(grep -c '> SCO Data RX' /tmp/sn1.txt)"
echo "  SCO RX inter-arrival gaps >50ms (timestamp list):"; grep '> SCO Data RX' /tmp/sn1.txt | grep -oE "[0-9]+\.[0-9]{6}$" | python3 -c "
import sys; t=[float(x) for x in sys.stdin]; gaps=[(t[i]-t[i-1],t[i-1]) for i in range(1,len(t)) if t[i]-t[i-1]>0.05]
print('   n=',len(t),'gaps>50ms:',len(gaps)); [print(f'   at {b:.3f}s gap {g*1000:.0f}ms') for g,b in gaps[:15]]"
echo "===B: disable SNIFF in link policy (keep RSWITCH) and exit sniff if in it==="
sudo -n hcitool lp $MAC RSWITCH 2>&1; sudo -n hciconfig hci0 lp RSWITCH 2>&1; sleep 1; sudo -n hcitool lp $MAC
sudo -n timeout 14 btmon -w /tmp/sn2.snoop >/dev/null 2>&1 & sleep 1
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/s2.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 4; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/s2.raw
sudo -n btmon -r /tmp/sn2.snoop 2>/dev/null > /tmp/sn2.txt; echo "  mode lines:"; grep -iE "Mode Change|Sniff" /tmp/sn2.txt | head -5; echo "  SCO RX count: $(grep -c '> SCO Data RX' /tmp/sn2.txt)"
echo "===C: repeat with sniff disabled (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/s3.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/s3.raw
