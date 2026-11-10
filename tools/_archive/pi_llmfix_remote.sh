set -e
cd /home/pi/code_dispatcher
mv -f /tmp/llm_backend_new.py llm_backend.py && python3 -m py_compile llm_backend.py && echo "compile ok"
echo "===SANITIZER_E2E==="
python3 - <<'PY'
import sys; sys.path.insert(0,"/home/pi/code_dispatcher")
from llm_backend import chat_complete, HAILO_BACKEND, is_backend_healthy
print("hailo healthy:", is_backend_healthy(HAILO_BACKEND, force_refresh=True))
txt, b = chat_complete('Repeat exactly the text between <<>>: <<line1\nline2\tTAB back\\slash "quoted">>', num_predict=60)
print(b.label, "->", repr(txt))
PY
sudo -n systemctl restart pi5-dispatcher-api.service && sleep 7 && systemctl is-active pi5-dispatcher-api.service
echo "===TRANSLATE_API x2==="; for i in 1 2; do S=$(date +%s.%N); curl -s -m 90 -H "Content-Type: application/json" -X POST http://127.0.0.1:80/api/voice/translate -d '{"text":"- 藍牙耳機配對問題已經修好\n- 語音辨識現在跑在 NPU 上\n- 下週要把大語言模型也搬到 NPU","direction":"zh2en"}' | head -c 500; echo " [$(echo "$(date +%s.%N) - $S" | bc | cut -c1-5)s]"; done
echo "===JOURNAL==="; journalctl -u pi5-dispatcher-api.service -S -2m --no-pager -o short-iso | grep -iE "LLM|backend" | tail -10
echo "===HAILO_ERRORS==="; journalctl -u hailo-ollama.service -S -2m --no-pager | grep -ciE "error|fail" || true
