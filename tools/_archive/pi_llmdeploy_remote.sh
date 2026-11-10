set -e
cd /home/pi/code_dispatcher
mkdir -p /tmp/llm_bak && cp -f main.py voice_streaming.py meeting_minutes.py /tmp/llm_bak/
tar -xf /tmp/llm_deploy.tar -C /home/pi/code_dispatcher
python3 -m py_compile llm_backend.py main.py voice_streaming.py meeting_minutes.py && echo "remote compile ok"
sudo -n systemctl restart pi5-dispatcher-api.service && echo restarted
sleep 6; systemctl is-active pi5-dispatcher-api.service
echo "===HEALTH==="; curl -s -m 5 http://127.0.0.1:80/health | head -c 600; echo
echo "===TRANSLATE_API==="; time curl -s -m 90 -H "Content-Type: application/json" -X POST http://127.0.0.1:80/api/voice/translate -d '{"text":"我們今天討論了三件事：藍牙耳機配對問題已經修好、語音辨識現在跑在 NPU 上、下週要把大語言模型也搬到 NPU。","direction":"zh2en"}' | head -c 800; echo
echo "===JOURNAL==="; journalctl -u pi5-dispatcher-api.service -n 30 --no-pager -o short-iso | grep -viE "GET /api|WebSocket" | tail -15
