cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
echo "===CONNECTED==="; bluetoothctl devices Connected; for m in $(bluetoothctl devices Connected | awk '{print $2}'); do bluetoothctl info $m | grep -E "Name|Paired|Trusted"; done
echo "===NODES==="; pw-dump | python3 -c "
import sys,json
for n in json.load(sys.stdin):
    p=(n.get('info',{}).get('props',{}) or {})
    if p.get('device.api')=='bluez5' and n.get('type','').endswith('Device'): print('DEVICE',n['id'],p.get('device.description'),'profile=',[x.get('name') for x in n['info']['params'].get('Profile',[])])
    if 'bluez_input_internal' in p.get('node.name',''): print('SRC',n['id'],p.get('node.name'),'codec=',p.get('api.bluez5.codec'))
"
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
MAC=$(bluetoothctl devices Connected | awk '{print $2}' | head -1); echo "rssi: $(hcitool rssi $MAC 2>&1) lq: $(hcitool lq $MAC 2>&1)"
echo "===REC 12s (please speak)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 12 /tmp/t4.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1
echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/t4.raw
ffmpeg -nostdin -v error -y -f s16le -ar 16000 -ac 1 -i /tmp/t4.raw -c:a libopus -b:a 64k /tmp/t4.ogg
echo "===STT (Hailo) on this clip==="; cd /home/pi/code_dispatcher && cat > /tmp/stt4.py <<'PY'
import sys; sys.path.insert(0,'/home/pi/telegram_agent'); sys.path.insert(0,'/home/pi/code_dispatcher')
from voice_pipeline import speech_to_text; print("TEXT:", speech_to_text('/tmp/t4.ogg'))
PY
python3 /tmp/stt4.py 2>&1 </dev/null | grep -E "TEXT|Hailo"
