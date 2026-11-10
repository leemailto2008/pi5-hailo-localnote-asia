echo "start $(date +%T)"; curl -s -m 60 -H "Content-Type: application/json" -X POST http://127.0.0.1:80/api/voice/record_and_transcribe -d '{"duration_sec":20}' > /tmp/speech.json; echo "end $(date +%T)"
python3 -c "import json; d=json.load(open('/tmp/speech.json')); print(json.dumps({k:d.get(k) for k in ('status','transcribed_text','english_translation','message','audio_url')},ensure_ascii=False,indent=1))"
F=$(ls -t /dev/shm/audio_cache/*.ogg | head -1); echo "file=$F"; ffmpeg -nostdin -v error -i "$F" -f s16le -ac 1 -ar 16000 /tmp/sp.raw && python3 /tmp/analyze.py /tmp/sp.raw
journalctl -u pi5-dispatcher-api.service -S -2m --no-pager -o short-iso | grep -iE "轉錄|whisper|Hailo|decode|VoicePipeline" | tail -6
