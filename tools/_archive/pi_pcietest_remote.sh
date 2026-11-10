cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
[ "$SRC" = "default" ] && { echo "NO BT SOURCE"; exit 0; }
echo "===PCI before==="; lspci | grep -i hailo; cat /sys/bus/pci/devices/0001:01:00.0/current_link_speed /sys/bus/pci/devices/0001:01:00.0/current_link_width 2>/dev/null
echo "===A: Hailo present, idle (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/h1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/h1.raw
echo "===STOP services & REMOVE Hailo PCIe device==="
sudo -n systemctl stop pi5-dispatcher-api.service hailo-ollama.service; sleep 2
sudo -n sh -c 'echo 1 > /sys/bus/pci/devices/0001:01:00.0/remove' && echo "removed"; sleep 2; lspci | grep -ci hailo
echo "===B: Hailo removed (10s) x2==="
for r in 1 2; do S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/h2$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  [$r] decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/h2$r.raw; done
echo "===Also set PCIe root port link down? (skip) — RESCAN==="
sudo -n sh -c 'echo 1 > /sys/bus/pci/rescan'; sleep 4; lspci | grep -i hailo; ls /dev/hailo* 2>/dev/null; lsmod | grep hailo
sudo -n systemctl start hailo-ollama.service pi5-dispatcher-api.service; sleep 6; systemctl is-active hailo-ollama.service pi5-dispatcher-api.service; timeout 10 hailortcli fw-control identify 2>&1 | grep -E "Device Architecture|error" | head -2
echo "===C: Hailo back, idle (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/h3.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/h3.raw
