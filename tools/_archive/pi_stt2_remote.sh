echo "===JOB_LOG (last recording)==="; journalctl -u pi5-dispatcher-api.service -S -15m --no-pager -o short-iso | grep -vE "GET /api|WebSocket|POST /api/bt" | grep -iE "hailo|whisper|stt|transcri|轉錄|chunk|segment|RTF|ms\)|master|minutes|took|秒|error|exception|降級" | tail -40
echo "===STATE==="; curl -s -m 3 http://127.0.0.1:80/api/status | python3 -c "import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ('state','phase','job','metrics')})"
echo "===STT_FILE_TEST==="
cd /home/pi/code_dispatcher
F=$(ls -S audio_cache/rec_*.mp3 | head -1); echo "file: $F"; 
HL_BEFORE=$(wc -l < /home/pi/hailort.log)
( top -b -d 1 -n 12 | grep -E "^%Cpu" ) > /tmp/cpu_during.txt &
python3 - "$F" <<'PY' 2>&1 | grep -vE "^\s*$"
import sys, time
sys.path.insert(0, "/home/pi/telegram_agent"); sys.path.insert(0, "/home/pi/code_dispatcher")
from voice_pipeline import speech_to_text
f=sys.argv[1]; t=time.time()
txt = speech_to_text(f)
print(f"took {time.time()-t:.2f}s (audio 60.0s)\nTEXT: {txt}")
PY
wait; echo "--- CPU% samples (us) during test:"; awk '{print $2}' /tmp/cpu_during.txt | tr '\n' ' '; echo
echo "===HAILORT_LOG_NEW==="; tail -n +$((HL_BEFORE+1)) /home/pi/hailort.log | grep -vE "OS Version" | head -20
