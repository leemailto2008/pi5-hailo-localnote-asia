cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
srcname(){ pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"; }
SRC=$(srcname)
echo "===WIFI_STATE==="; nmcli -t -f ACTIVE,SSID,CHAN,FREQ,RATE,SIGNAL dev wifi 2>/dev/null | grep "^yes"; which iw iwconfig; sudo -n iw dev wlan0 get power_save 2>&1; iwconfig wlan0 2>/dev/null | grep -iE "Frequency|Power Management|Bit Rate|Link Quality"; cat /proc/net/wireless | tail -1
echo "===BT_LINK_QUALITY==="; hcitool con; for i in 1 2 3; do echo "  rssi: $(hcitool rssi A0:D1:2A:42:12:34 2>&1)  lq: $(hcitool lq A0:D1:2A:42:12:34 2>&1)"; sleep 0.5; done
echo "===UART==="; ls -la /dev/ttyAMA0 /dev/serial* 2>/dev/null; systemctl status hciuart --no-pager 2>/dev/null | head -5; ps -eo pid,comm,args | grep -E "btattach|hciattach" | grep -v grep; stty -F /dev/ttyAMA0 speed 2>/dev/null
echo "===BASELINE mSBC 10s (power_save as-is)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/b1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/b1.raw
echo "===WIFI power_save OFF, mSBC 10s==="; sudo -n iw dev wlan0 set power_save off 2>&1; sudo -n iw dev wlan0 get power_save 2>&1; sleep 2
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/b2.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/b2.raw
echo "===API service stopped (no WS telemetry) + power_save OFF, mSBC 10s==="; sudo -n systemctl stop pi5-dispatcher-api.service; sleep 2
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/b3.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/b3.raw
echo "===hailo-ollama + ollama stopped too, mSBC 10s==="; sudo -n systemctl stop hailo-ollama.service ollama.service pi5-gpio-keyled.service; sleep 2
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/b4.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/b4.raw
echo "  load: $(cat /proc/loadavg)"; top -bn1 | head -12 | tail -6
sudo -n systemctl start ollama.service hailo-ollama.service pi5-gpio-keyled.service pi5-dispatcher-api.service; sleep 3; systemctl is-active pi5-dispatcher-api.service hailo-ollama.service ollama.service
echo "===IRQ/UART stats==="; grep -iE "ttyAMA|uart|serial" /proc/interrupts | head -4; cat /proc/tty/driver/ttyAMA 2>/dev/null | head -3
