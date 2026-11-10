set -e
cd /home/pi/code_dispatcher && tar -xf /tmp/ui_deploy.tar -C /home/pi/code_dispatcher
for f in ui_client.html static/ui_client.html static/index.html; do [ -f "$f" ] && cp -f ui.html "$f"; done
echo "$(hostname): btnToggleNpu=$(grep -c btnToggleNpu ui.html) Hailo-visible=$(grep -c 'Hailo-10H AI' ui.html) TOPS=$(grep -c '40 TOPS' ui.html)"
curl -s -m 5 http://127.0.0.1:80/ | grep -c "btnToggleNpu"
