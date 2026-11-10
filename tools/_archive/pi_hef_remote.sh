echo "===MODELS==="; find /home/pi/models /usr/local/hailo -iname "*.hef" -exec ls -la {} \; 2>/dev/null
echo "===HAILORT_LOG_TAIL==="; tail -25 /home/pi/code_dispatcher/hailort.log
echo "===HAILORT_HOME_LOG==="; tail -10 /home/pi/hailort.log
echo "===JOURNAL_WHISPER==="; journalctl -u pi5-dispatcher-api.service -S -3d --no-pager -o short-iso 2>/dev/null | grep -iE "hailo|whisper|backend|NPU" | tail -25
echo "===HAILO_OLLAMA_LOG==="; journalctl -u hailo-ollama.service -n 15 --no-pager -o short-iso 2>/dev/null
echo "===OLLAMA_STORE==="; du -sh /home/pi/.ollama/models 2>/dev/null; ls /usr/share/ollama 2>/dev/null
