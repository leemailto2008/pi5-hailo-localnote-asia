echo "===JOURNAL 12:58:50-12:59:30==="; journalctl -u pi5-dispatcher-api.service -S "2026-10-22 12:58:50" -U "2026-10-22 12:59:30" --no-pager -o short-iso | grep -vE "GET /api|WebSocket|HailoRT|HAILO" | sed 's/.*python3\[[0-9]*\]: //' | head -20
echo "===WP/BT journal same window==="; journalctl -S "2026-10-22 12:58:50" -U "2026-10-22 12:59:30" --no-pager -o short-iso | grep -iE "bluez|sco|wireplumber|pipewire" | sed 's/.*\]: //' | sort | uniq -c | head -10
echo "===STATE NOW==="; pw-dump | python3 -c "
import sys,json
for n in json.load(sys.stdin):
    p=(n.get('info',{}).get('props',{}) or {})
    if p.get('device.api')=='bluez5' and n.get('type','').endswith('Device'): print('DEVICE',n['id'],'profile=',[x.get('name') for x in n['info']['params'].get('Profile',[])])
    if 'bluez_input' in p.get('node.name','') and n.get('type','').endswith('Node'): print('NODE',n['id'],p.get('node.name'),p.get('media.class'),'codec=',p.get('api.bluez5.codec'),'state=',n['info'].get('state'))
"; wpctl status | sed -n '/Sources:/,/Filters:/p' | head -6
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
echo "===REPRO app cmd (taskset+nice+filters+opus) 6s==="
taskset -c 0,1 nice -n -18 ffmpeg -nostdin -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$SRC" -t 6 -af "highpass=f=80,lowpass=f=7600" -ar 16000 -ac 1 -c:a libopus -b:a 64k /tmp/app_repro.ogg 2>&1 | grep -iE "error|warn|Input #|Stream #|size=" | head -6
ffmpeg -nostdin -v error -y -i /tmp/app_repro.ogg -f s16le -ac 1 -ar 16000 /tmp/app_repro.raw && python3 /tmp/analyze.py /tmp/app_repro.raw
echo "===REPRO plain pulse default 6s==="; ffmpeg -nostdin -v error -y -f pulse -i default -t 6 -f s16le -ac 1 -ar 16000 /tmp/def.raw && python3 /tmp/analyze.py /tmp/def.raw
echo "===pactl default source==="; pactl get-default-source 2>/dev/null; pactl list sources short 2>/dev/null | head -5
