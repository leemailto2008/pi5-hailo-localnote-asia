set -e
cd /home/pi/code_dispatcher && cp -f voice_pipeline.py /tmp/voice_pipeline.bak.py && mv -f /tmp/voice_pipeline_new.py voice_pipeline.py && python3 -m py_compile voice_pipeline.py && echo "compile ok"
sudo -n systemctl restart pi5-dispatcher-api.service; sleep 8; systemctl is-active pi5-dispatcher-api.service
MAC=A0:D1:2A:42:12:34
echo "===SIMULATE reconnect then immediate record==="; bluetoothctl disconnect $MAC >/dev/null 2>&1; sleep 3; for i in $(seq 1 8); do bluetoothctl connect $MAC >/dev/null 2>&1; sleep 2; bluetoothctl info $MAC | grep -q "Connected: yes" && break; done; bluetoothctl info $MAC | grep Connected
echo "start $(date +%T)"; curl -s -m 90 -H "Content-Type: application/json" -X POST http://127.0.0.1:80/api/voice/record_and_transcribe -d '{"duration_sec":12}' > /tmp/pf.json; echo "end $(date +%T)"
python3 -c "import json; d=json.load(open('/tmp/pf.json')); print('TEXT:', d.get('transcribed_text') or d.get('message'))"
F=$(ls -t /dev/shm/audio_cache/rec_*.ogg | head -1); ffmpeg -nostdin -v error -y -i "$F" -f s16le -ac 1 -ar 16000 /tmp/pf.raw && python3 /tmp/analyze.py /tmp/pf.raw
echo "===APP LOG==="; journalctl -u pi5-dispatcher-api.service -S -60s --no-pager -o short-iso | grep -E "VoicePipeline\]" | sed 's/.*python3\[[0-9]*\]: //' | tail -8
