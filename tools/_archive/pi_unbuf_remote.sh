sudo -n mkdir -p /etc/systemd/system/pi5-dispatcher-api.service.d
sudo -n tee /etc/systemd/system/pi5-dispatcher-api.service.d/10-logging.conf >/dev/null <<'CONF'
[Service]
Environment=PYTHONUNBUFFERED=1
CONF
sudo -n systemctl daemon-reload && sudo -n systemctl restart pi5-dispatcher-api.service; sleep 8; systemctl is-active pi5-dispatcher-api.service
systemctl show pi5-dispatcher-api.service -p Environment
echo "===RECORD 20s via API (speak now)==="; echo "start $(date +%T)"; curl -s -m 60 -H "Content-Type: application/json" -X POST http://127.0.0.1:80/api/voice/record_and_transcribe -d '{"duration_sec":20}' > /tmp/speech.json; echo "end $(date +%T)"
python3 -c "import json; d=json.load(open('/tmp/speech.json')); print(json.dumps({k:d.get(k) for k in ('status','transcribed_text','english_translation','message')},ensure_ascii=False,indent=1))"
F=$(ls -t /dev/shm/audio_cache/rec_*.ogg | head -1); echo "file=$F"; ffmpeg -nostdin -v error -y -i "$F" -f s16le -ac 1 -ar 16000 /tmp/sp.raw && python3 /tmp/analyze.py /tmp/sp.raw
echo "===APP LOG==="; journalctl -u pi5-dispatcher-api.service -S -90s --no-pager -o short-iso | grep -vE "GET /api|WebSocket|HailoRT|HAILO|sudo|pam_unix|affinity" | sed 's/.*python3\[[0-9]*\]: //' | tail -25
