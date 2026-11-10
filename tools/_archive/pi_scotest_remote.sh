SRC=$(pw-dump | python3 -c "import sys,json; print(next(n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')))")
echo "source=$SRC"
echo "===AFFINITY==="; for p in bluetoothd pipewire wireplumber; do pid=$(pgrep -x $p | head -1); echo "$p pid=$pid $(taskset -pc $pid 2>&1 | sed 's/.*: //') nice=$(ps -o ni= -p $pid)"; done; apipid=$(systemctl show -p MainPID --value pi5-dispatcher-api.service); echo "api pid=$apipid $(taskset -pc $apipid | sed 's/.*: //') nice=$(ps -o ni= -p $apipid) threads=$(ls /proc/$apipid/task | wc -l)"; hpid=$(systemctl show -p MainPID --value hailo-ollama.service); echo "hailo-ollama pid=$hpid $(taskset -pc $hpid | sed 's/.*: //')"
analyze(){ python3 /tmp/analyze.py "$1"; }
cat > /tmp/analyze.py <<'PY'
import sys, numpy as np
a=np.fromfile(sys.argv[1], dtype=np.int16); n=len(a); z=(a==0)
d=np.diff(np.concatenate(([0],z.astype(np.int8),[0]))); runs=(np.where(d==-1)[0]-np.where(d==1)[0])/16.0
print(f"  samples={n} ({n/16000:.1f}s) zero={z.mean()*100:.1f}%  runs>=20ms={int((runs>=20).sum())} runs>=100ms={int((runs>=100).sum())}  max_run={runs.max() if len(runs) else 0:.0f}ms  rms={20*np.log10(np.sqrt((a.astype(np.float32)**2).mean())/32768+1e-9):.1f}dB")
PY
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
echo "===RUN1: idle, ffmpeg pinned 0,1 nice -18 (same as app) 15s==="
S1=$(date "+%Y-%m-%d %H:%M:%S"); taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$SRC" -t 15 -f s16le -ac 1 -ar 16000 /tmp/run1.raw; E1=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1
echo "  decode_failed=$(cnt "$S1" "$E1")"; analyze /tmp/run1.raw
echo "===RUN2: pw-record (no ffmpeg) 15s==="
S2=$(date "+%Y-%m-%d %H:%M:%S"); timeout 17 pw-record --target "$SRC" --rate 16000 --channels 1 --format s16 --raw /tmp/run2.raw </dev/null; E2=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1
echo "  decode_failed=$(cnt "$S2" "$E2")"; analyze /tmp/run2.raw
echo "===RUN3: ffmpeg 15s + concurrent Hailo STT on 60s mp3==="
S3=$(date "+%Y-%m-%d %H:%M:%S")
cat > /tmp/run3_stt.py <<'PY2'
import sys; sys.path.insert(0,'/home/pi/telegram_agent'); sys.path.insert(0,'/home/pi/code_dispatcher')
from voice_pipeline import speech_to_text; speech_to_text('audio_cache/rec_221a6eba.mp3')
PY2
( cd /home/pi/code_dispatcher && python3 /tmp/run3_stt.py > /tmp/run3_stt.log 2>&1 </dev/null ) &
taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$SRC" -t 15 -f s16le -ac 1 -ar 16000 /tmp/run3.raw; E3=$(date "+%Y-%m-%d %H:%M:%S"); wait; sleep 1
echo "  decode_failed=$(cnt "$S3" "$E3")"; analyze /tmp/run3.raw; grep -o "耗時: [0-9.]*ms" /tmp/run3_stt.log
echo "===SCO_LINK==="; hcitool con 2>/dev/null; echo "===KERNEL_BT==="; dmesg 2>/dev/null | grep -iE "bluetooth|hci|sco|uart" | tail -8; cat /proc/device-tree/model 2>/dev/null; echo; grep -E "^(dtoverlay|dtparam|enable_uart|krnbt)" /boot/firmware/config.txt 2>/dev/null
