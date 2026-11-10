set -e
echo "===HOST==="; hostname; uname -r; ip -4 -br addr | grep -v lo; uptime
echo "===PRE==="; cd /home/pi/code_dispatcher && ls hailo_whisper >/dev/null 2>&1 && echo "hailo_whisper present"; md5sum bluetooth_manager.py main.py voice_pipeline.py | cut -c1-8 | tr '\n' ' '; echo
mkdir -p /tmp/bak678 && cp -f bluetooth_manager.py main.py voice_streaming.py meeting_minutes.py voice_pipeline.py ui.html /tmp/bak678/ 2>/dev/null || true
mkdir -p /tmp/full678 && tar -xf /tmp/full_deploy.tar -C /tmp/full678
cp -f /tmp/full678/*.py /tmp/full678/ui.html /home/pi/code_dispatcher/
for f in ui_client.html static/ui_client.html static/index.html; do [ -f "$f" ] && cp -f ui.html "$f"; done
python3 -m py_compile bluetooth_manager.py llm_backend.py main.py voice_streaming.py meeting_minutes.py voice_pipeline.py && echo "compile ok"
python3 -c "import httpx, requests; print('httpx', httpx.__version__)"
echo "===SYSTEM CONF==="; sudo -n mkdir -p /etc/wireplumber/wireplumber.conf.d /etc/systemd/system/pi5-dispatcher-api.service.d
sudo -n cp -f /tmp/full678/wireplumber.conf.d/51-bluez-cvsd.conf /etc/wireplumber/wireplumber.conf.d/
sudo -n cp -f /tmp/full678/systemd/pi5-dispatcher-api.service.d-10-logging.conf /etc/systemd/system/pi5-dispatcher-api.service.d/10-logging.conf
sudo -n systemctl daemon-reload
export XDG_RUNTIME_DIR=/run/user/1000; systemctl --user restart wireplumber 2>&1 || true; sleep 3
sudo -n systemctl restart pi5-dispatcher-api.service; sleep 8; systemctl is-active pi5-dispatcher-api.service hailo-ollama.service ollama.service bluetooth.service 2>&1 | tr '\n' ' '; echo
echo "===HEALTH==="; curl -s -m 8 http://127.0.0.1:80/health 2>/dev/null | head -c 300 || curl -s -m 8 http://127.0.0.1:8000/health | head -c 300; echo
echo "===BT STATUS==="; curl -s -m 8 http://127.0.0.1:80/api/bt/status 2>/dev/null | head -c 300; echo
echo "===HAILO==="; lspci | grep -i hailo; timeout 8 hailortcli fw-control identify 2>&1 | grep -E "Architecture|error" | head -1
echo "===LOG==="; journalctl -u pi5-dispatcher-api.service -n 12 --no-pager -o short-iso | sed 's/.*python3\[[0-9]*\]: //' | grep -vE "GET /api|WebSocket"
