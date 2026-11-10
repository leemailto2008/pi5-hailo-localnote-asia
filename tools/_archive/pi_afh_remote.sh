cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
H=$(hcitool con | grep -oE "handle [0-9]+" | awk '{print $2}'); echo "acl handle=$H"
afh(){ sudo -n hcitool cmd 0x05 0x0006 $(printf "0x%02X 0x%02X" $((H & 0xff)) $((H >> 8))) 2>/dev/null | tail -1; }
decode(){ python3 -c "
import sys; b=[int(x,16) for x in sys.argv[1].split()]
# reply: status, handle(2), mode(1), map(10)
st=b[0]; mode=b[3]; m=b[4:14]; bits=''.join(format(x,'08b')[::-1] for x in m)
n=bits.count('1'); print(f'  status={st} afh_mode={mode} usable_channels={n}/79'); print('  map(ch0..78):', bits[:79])
" "$1"; }
echo "===AFH MAP (current)==="; R=$(afh); echo "  raw: $R"; decode "$R"
echo "===ASSESSMENT MODE==="; sudo -n hcitool cmd 0x03 0x0048 2>/dev/null | tail -1
echo "===A: baseline (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/af1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/af1.raw
echo "===DISABLE controller channel assessment (0x03 0x0049 mode=0)==="; sudo -n hcitool cmd 0x03 0x0049 0x00 2>/dev/null | tail -1; sleep 3; R=$(afh); decode "$R"
echo "===B: assessment off (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/af2.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/af2.raw
echo "===SET host classification: all channels good (0x03 0x003F)==="; sudo -n hcitool cmd 0x03 0x003F 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0x7F 2>/dev/null | tail -1; sleep 3; R=$(afh); decode "$R"
echo "===C: host map all-good (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/af3.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/af3.raw
echo "===SET host classification: avoid WiFi ch1-6 region (ch 0-30 bad) ==="; sudo -n hcitool cmd 0x03 0x003F 0x00 0x00 0x00 0x80 0xFF 0xFF 0xFF 0xFF 0xFF 0x7F 2>/dev/null | tail -1; sleep 3; R=$(afh); decode "$R"
echo "===D: host map upper-half only (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/af4.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/af4.raw
echo "===RESTORE: assessment on, host map all-good==="; sudo -n hcitool cmd 0x03 0x003F 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0xFF 0x7F >/dev/null 2>&1; sudo -n hcitool cmd 0x03 0x0049 0x01 2>/dev/null | tail -1
