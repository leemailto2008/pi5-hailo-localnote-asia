cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
RP=0001:00:00.0; EP=0001:01:00.0
echo "===RESTORE Gen2==="; LC2=$(sudo -n setpci -s $RP CAP_EXP+30.w); sudo -n setpci -s $RP CAP_EXP+30.w=$(printf "%04x" $(( (0x$LC2 & ~0xF) | 2 ))); LC=$(sudo -n setpci -s $RP CAP_EXP+10.w); sudo -n setpci -s $RP CAP_EXP+10.w=$(printf "%04x" $(( 0x$LC | 0x20 ))); sleep 1; cat /sys/bus/pci/devices/$EP/current_link_speed
echo "===PM STATE==="; cat /sys/bus/pci/devices/$EP/power/control /sys/bus/pci/devices/$EP/power_state /sys/bus/pci/devices/$EP/power/runtime_status 2>&1
echo "===TRY runtime PM auto (services stopped so device idle)==="; sudo -n systemctl stop pi5-dispatcher-api.service hailo-ollama.service; sleep 2
echo auto | sudo -n tee /sys/bus/pci/devices/$EP/power/control; sleep 5; cat /sys/bus/pci/devices/$EP/power_state /sys/bus/pci/devices/$EP/power/runtime_status
echo "===E: driver bound, services stopped, PM auto (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/e1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/e1.raw
echo "===F: force D3hot via setpci PMCSR (device idle)==="; PMOFF=$(sudo -n lspci -s $EP -vv 2>/dev/null | grep -oE "Capabilities: \[[0-9a-f]+\] Power Management" | grep -oE "\[[0-9a-f]+\]" | tr -d '[]'); echo "  PM cap @0x$PMOFF"
if [ -n "$PMOFF" ]; then PMCSR=$(sudo -n setpci -s $EP $PMOFF.w 2>/dev/null); CTL=$(sudo -n setpci -s $EP $((0x$PMOFF+4)).w 2>/dev/null); echo "  PMCSR before=$CTL"; sudo -n setpci -s $EP $((0x$PMOFF+4)).w=$(printf "%04x" $(( (0x$CTL & ~3) | 3 ))); sleep 1; echo "  PMCSR after=$(sudo -n setpci -s $EP $((0x$PMOFF+4)).w)"; cat /sys/bus/pci/devices/$EP/power_state
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/f1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/f1.raw
echo "  -> back to D0"; sudo -n setpci -s $EP $((0x$PMOFF+4)).w=$(printf "%04x" $(( 0x$CTL & ~3 ))); sleep 1; cat /sys/bus/pci/devices/$EP/power_state; fi
echo on | sudo -n tee /sys/bus/pci/devices/$EP/power/control >/dev/null
sudo -n systemctl start hailo-ollama.service pi5-dispatcher-api.service; sleep 6; systemctl is-active hailo-ollama.service pi5-dispatcher-api.service; timeout 10 hailortcli fw-control identify 2>&1 | grep -E "Architecture|error" | head -1
