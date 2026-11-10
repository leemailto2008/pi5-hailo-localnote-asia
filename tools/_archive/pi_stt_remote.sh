echo "===REC_GUARD==="; curl -s -m 3 http://127.0.0.1:80/api/status | head -c 120; echo
echo "===ENGINE_PROBE==="
cd /home/pi/code_dispatcher && python3 - <<'PY' 2>&1 | grep -vE "^\s*$"
import sys, time, logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
sys.path.insert(0, "/home/pi/code_dispatcher")
from hailo_whisper.engine import get_whisper_engine
t=time.time(); eng = get_whisper_engine(preferred_backend="hailo")
print("engine:", type(eng).__name__, "hw:", eng.is_hardware_accelerated(), "hef:", getattr(eng,"hef_path",None), f"init {time.time()-t:.2f}s")
PY
echo "===STT_FILE_TEST==="
cd /home/pi/code_dispatcher
F=$(ls -S audio_cache/rec_*.mp3 | head -1); echo "file: $F $(du -h $F | cut -f1)"; ffprobe -v error -show_entries format=duration -of csv=p=0 "$F"
HL_BEFORE=$(wc -l < /home/pi/hailort.log)
python3 - "$F" <<'PY' 2>&1 | grep -vE "^\s*$"
import sys, time
sys.path.insert(0, "/home/pi/code_dispatcher")
from voice_pipeline import speech_to_text
f=sys.argv[1]; t=time.time()
txt = speech_to_text(f)
print(f"took {time.time()-t:.2f}s\nTEXT: {txt}")
PY
echo "===HAILORT_LOG_NEW==="; tail -n +$((HL_BEFORE+1)) /home/pi/hailort.log | head -30
echo "===TRACEBACK_1021==="; journalctl -u pi5-dispatcher-api.service -S "2026-10-21 16:08:30" -U "2026-10-21 16:09:38" --no-pager -o short-iso | grep -vE "GET /api|WebSocket|anyio|^$" | head -80
