cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
RP=0001:00:00.0; EP=0001:01:00.0
echo "===STATE==="; cat /sys/bus/pci/devices/$EP/current_link_speed; cat /sys/module/pcie_aspm/parameters/policy 2>/dev/null; sudo -n lspci -vv -s $EP 2>/dev/null | grep -E "LnkCap:|LnkSta:|LnkCtl:" | head -3; grep -E "pcie" /boot/firmware/config.txt /boot/firmware/cmdline.txt
echo "===A: Gen2 baseline (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/g1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/g1.raw
echo "===SET Gen1 via setpci (root port target link speed=1 + retrain)==="
LC2=$(sudo -n setpci -s $RP CAP_EXP+30.w); echo "  LnkCtl2 before=$LC2"
sudo -n setpci -s $RP CAP_EXP+30.w=$(printf "%04x" $(( (0x$LC2 & ~0xF) | 1 )))
LC=$(sudo -n setpci -s $RP CAP_EXP+10.w); sudo -n setpci -s $RP CAP_EXP+10.w=$(printf "%04x" $(( 0x$LC | 0x20 ))); sleep 1
echo "  link now: $(cat /sys/bus/pci/devices/$EP/current_link_speed)"
echo "===B: Gen1 (10s) x2==="; for r in 1 2; do S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/g2$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  [$r] decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/g2$r.raw; done
echo "===C: Gen1 + ASPM powersave (10s)==="; echo powersave | sudo -n tee /sys/module/pcie_aspm/parameters/policy >/dev/null 2>&1; cat /sys/module/pcie_aspm/parameters/policy; sleep 2
S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/g3.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/g3.raw
echo "===D: Gen1 + Hailo STT via API running (10s)==="
F=/home/pi/code_dispatcher/audio_cache/rec_221a6eba.mp3
( cd /home/pi/code_dispatcher && python3 - <<'PY' </dev/null >/tmp/stt_d.log 2>&1
import requests,time
# trigger an inference through the running service to keep NPU busy: use /api/voice/translate? no STT endpoint for file; fallback: hailo-ollama generate
t=time.time(); r=requests.post("http://127.0.0.1:11435/api/chat",json={"model":"qwen3:1.7b","messages":[{"role":"user","content":"Write a 300 word story about a river."}],"stream":False,"think":False,"options":{"num_predict":300}},timeout=120); print("llm done", time.time()-t, r.status_code)
PY
) &
sleep 2; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/g4.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/g4.raw; wait; cat /tmp/stt_d.log
echo "===HAILO OK?==="; timeout 10 hailortcli fw-control identify 2>&1 | grep -E "Architecture|error" | head -1; cat /sys/bus/pci/devices/$EP/current_link_speed
