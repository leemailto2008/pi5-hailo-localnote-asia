cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
EP=0001:01:00.0
echo on | sudo -n tee /sys/bus/pci/devices/$EP/power/control >/dev/null
echo "===A: bound, services running (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/x1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/x1.raw
sudo -n systemctl stop pi5-dispatcher-api.service hailo-ollama.service; sleep 2
echo "===UNBIND driver==="; T0=$(date +%s.%N); echo $EP | sudo -n tee /sys/bus/pci/drivers/hailo1x/unbind >/dev/null && echo "  unbind ok in $(echo "$(date +%s.%N) - $T0" | bc | cut -c1-4)s"; lspci -k -s $EP | grep -E "driver"; cat /sys/bus/pci/devices/$EP/power_state
echo "===B: unbound (10s) x2==="; for r in 1 2; do S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/x2$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  [$r] decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/x2$r.raw; done
echo "===REBIND==="; T0=$(date +%s.%N); echo $EP | sudo -n tee /sys/bus/pci/drivers/hailo1x/bind >/dev/null && echo "  bind ok in $(echo "$(date +%s.%N) - $T0" | bc | cut -c1-4)s"; lspci -k -s $EP | grep -E "driver"; ls /dev/hailo*
echo "===C: rebound, services still stopped (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/x3.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/x3.raw
sudo -n systemctl start hailo-ollama.service pi5-dispatcher-api.service; sleep 6; systemctl is-active hailo-ollama.service pi5-dispatcher-api.service; timeout 10 hailortcli fw-control identify 2>&1 | grep -E "Architecture|error" | head -1
echo "===D: rebound, services running (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/x4.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/x4.raw
