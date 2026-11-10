cat > /tmp/autoloop.sh <<'INNER'
#!/bin/bash
exec > /tmp/autoloop.txt 2>&1
MAC=A0:D1:2A:42:12:34
export XDG_RUNTIME_DIR=/run/user/1000
reconnect(){ bluetoothctl disconnect $MAC >/dev/null 2>&1; sleep 3; for i in $(seq 1 8); do bluetoothctl connect $MAC >/dev/null 2>&1; sleep 3; bluetoothctl info $MAC | grep -q "Connected: yes" && break; done; sleep 3
  DEV=$(pw-dump | python3 -c "import sys,json; print(next((n['id'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')),''))")
  IDX=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next((p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='headset-head-unit'),''))"); [ -n "$IDX" ] && wpctl set-profile $DEV $IDX; sleep 5; }
trial(){ label="$1"; echo "################ $label  $(date +%T)"; bluetoothctl info $MAC | grep Connected
  sudo -n timeout 22 btmon -w /tmp/al.snoop >/dev/null 2>&1 & sleep 1
  S=$(date "+%Y-%m-%d %H:%M:%S"); curl -s -m 90 -H "Content-Type: application/json" -X POST http://127.0.0.1:80/api/voice/record_and_transcribe -d '{"duration_sec":15}' > /tmp/al.json; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 2
  python3 -c "import json; d=json.load(open('/tmp/al.json')); print('TEXT:', d.get('transcribed_text') or d.get('message'))"
  F=$(ls -t /dev/shm/audio_cache/rec_*.ogg | head -1); ffmpeg -nostdin -v error -y -i "$F" -f s16le -ac 1 -ar 16000 /tmp/al.raw && python3 /tmp/analyze.py /tmp/al.raw
  sudo -n cat /tmp/al.snoop > /tmp/alc.snoop; python3 /tmp/scostat2.py /tmp/alc.snoop 2>/dev/null | head -2
  sudo -n btmon -r /tmp/al.snoop 2>/dev/null | grep -A8 "Synchronous Connect Complete" | grep -E "Link type|interval|window|RX packet" | tr '\n' ' '; echo
  echo "  decode_failed=$(journalctl -S "$S" -U "$E" --no-pager 2>/dev/null | grep -c 'decode failed')"; }
echo "=== baseline: CVSD / eSCO S4 (disable_esco=$(cat /sys/module/bluetooth/parameters/disable_esco)) ==="
trial "T1 CVSD eSCO-S4 (current)"
trial "T2 CVSD eSCO-S4 (repeat)"
echo "=== variant: disable_esco=Y -> SCO HV3 basic-rate ==="
echo Y | sudo -n tee /sys/module/bluetooth/parameters/disable_esco >/dev/null; reconnect
trial "T3 CVSD SCO-HV3 (disable_esco)"
trial "T4 CVSD SCO-HV3 (repeat)"
echo "=== restore eSCO (disable_esco=N) ==="
echo N | sudo -n tee /sys/module/bluetooth/parameters/disable_esco >/dev/null; reconnect
trial "T5 CVSD eSCO-S4 (restored)"
echo "ALLDONE $(date +%T)"
INNER
chmod +x /tmp/autoloop.sh; rm -f /tmp/autoloop.txt; setsid nohup /tmp/autoloop.sh >/dev/null 2>&1 </dev/null & echo "launched $!"
