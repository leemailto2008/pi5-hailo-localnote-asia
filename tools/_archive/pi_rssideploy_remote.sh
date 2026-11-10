set -e
cd /home/pi/code_dispatcher
cp -f main.py /tmp/main.bak2.py; cp -f ui.html /tmp/ui.bak2.html
tar -xf /tmp/rssi_deploy.tar -C /home/pi/code_dispatcher
# keep the identical copies in sync (same content as ui.html before this change)
for f in ui_client.html static/ui_client.html static/index.html; do [ -f "$f" ] && cp -f ui.html "$f"; done
python3 -m py_compile main.py && echo "compile ok"
sudo -n systemctl restart pi5-dispatcher-api.service; sleep 7; systemctl is-active pi5-dispatcher-api.service
curl -s -m 8 http://127.0.0.1:80/api/bt/status | python3 -c "import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ('connected','rssi','rssi_kind','signal_level_pct')})"
curl -s -m 5 http://127.0.0.1:80/ | grep -c "formatRssi"
