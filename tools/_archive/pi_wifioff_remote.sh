cat > /tmp/wifioff_test.sh <<'INNER'
#!/bin/bash
exec > /tmp/wifioff_result.txt 2>&1
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))")
echo "source=$SRC"; echo "uart before:"; sudo -n cat /proc/tty/driver/ttyAMA 2>&1 | head -4
( sleep 90; sudo -n nmcli radio wifi on ) &   # watchdog
echo "=== WIFI ON baseline 10s ==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/w1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/w1.raw
echo "=== WIFI OFF ==="; sudo -n nmcli radio wifi off; sleep 4; nmcli radio wifi
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/w2.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/w2.raw
sudo -n nmcli radio wifi on; echo "wifi re-enabled $(date +%T)"; sleep 8; ip -4 -br addr show wlan0
echo "uart after:"; sudo -n cat /proc/tty/driver/ttyAMA 2>&1 | head -4
echo "=== WIFI ON again 10s ==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/w3.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/w3.raw
echo DONE
INNER
chmod +x /tmp/wifioff_test.sh; rm -f /tmp/wifioff_result.txt
setsid nohup /tmp/wifioff_test.sh >/dev/null 2>&1 < /dev/null &
echo "launched detached pid=$!"
