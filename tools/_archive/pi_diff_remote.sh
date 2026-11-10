echo "===TREE==="; ls -la /home/pi; echo; ls -la /home/pi/code_dispatcher
echo "===MD5==="; cd /home/pi/code_dispatcher && find . -type f ! -path '*/__pycache__/*' ! -path './.git/*' ! -name '*.pyc' -exec md5sum {} \; | sort -k2
echo "===HAILO_DIRS==="; ls -la /home/pi/hailo_whisper /home/pi/code_dispatcher/hailo_whisper 2>&1 | head -40
echo "===UNIT==="; systemctl cat pi5-dispatcher-api.service --no-pager 2>&1
echo "===UNIT_PROXY==="; systemctl cat pi5-port8000-proxy.service --no-pager 2>&1
echo "===UNIT_HAILO_OLLAMA==="; systemctl cat hailo-ollama.service --no-pager 2>&1 | head -40
echo "===HAILO_OLLAMA_API==="; for p in 8000 8080 11435 11436; do echo "-- :$p"; curl -s -m 2 http://127.0.0.1:$p/api/tags 2>/dev/null | head -c 400; echo; done
echo "===PY_IMPORTS==="; grep -nE "hailo|faster_whisper|WhisperEngine|qwen" /home/pi/code_dispatcher/main.py /home/pi/code_dispatcher/voice_pipeline.py /home/pi/code_dispatcher/voice_streaming.py 2>/dev/null | head -60
echo "===PIP==="; pip list 2>/dev/null | grep -iE "hailo|whisper|ctranslate|fastapi|uvicorn|rq|redis|opencc|numpy" 
echo "===DU==="; du -sh /home/pi/* /usr/share/ollama 2>/dev/null | sort -h | tail -12; du -sh /home/pi/.ollama 2>/dev/null; sudo -n du -sh /usr/share/ollama/.ollama 2>/dev/null
