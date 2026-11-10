export DEBIAN_FRONTEND=noninteractive
echo "===HAILO_DRIVER_BUILD_INFO==="; ls /usr/src/hailort-pcie-driver/ 2>/dev/null | head; cat /usr/src/hailort-pcie-driver/dkms.conf 2>/dev/null | head -8; dpkg -L hailort-pcie-driver | grep -E "\.ko|postinst|dkms" | head -5; find /lib/modules -name "hailo*.ko*" 2>/dev/null; dpkg -s hailort-pcie-driver | grep -E "Depends|Version"; cat /var/lib/dpkg/info/hailort-pcie-driver.postinst 2>/dev/null | head -30
echo "===APT_UPDATE==="; sudo -n apt-get update -qq 2>&1 | tail -2
echo "===UPGRADE_BT_USERSPACE==="; sudo -n apt-get install -y --only-upgrade bluez libbluetooth3 pipewire pipewire-bin pipewire-pulse libpipewire-0.3-0t64 libpipewire-0.3-modules libspa-0.2-bluetooth libspa-0.2-modules firmware-brcm80211 2>&1 | grep -E "^(Setting up|Unpacking|E:|Err)" | head -20
dpkg -l | grep -iE "^ii  (bluez |libspa-0.2-bluetooth|pipewire-bin|firmware-brcm80211)" | awk '{print $2, $3}'
echo "===RESTART_STACK==="; sudo -n systemctl restart bluetooth; sleep 2
export XDG_RUNTIME_DIR=/run/user/1000; systemctl --user restart pipewire pipewire-pulse wireplumber 2>&1; sleep 4; systemctl --user is-active pipewire wireplumber
echo "waiting for headset reconnect..."; for i in $(seq 1 20); do bluetoothctl info A0:D1:2A:42:12:34 | grep -q "Connected: yes" && break; sleep 2; done; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Connected"
[ "$(bluetoothctl info A0:D1:2A:42:12:34 | grep -c 'Connected: yes')" = "0" ] && { bluetoothctl connect A0:D1:2A:42:12:34 | tail -1; sleep 4; }
sleep 3; pw-dump | python3 -c "
import sys,json
for n in json.load(sys.stdin):
    p=(n.get('info',{}).get('props',{}) or {})
    if p.get('device.api')=='bluez5' and n.get('type','').endswith('Device'): print('DEVICE',n['id'],p.get('device.description'),'profile=',[x.get('name') for x in n['info']['params'].get('Profile',[])])
    if 'bluez_input_internal' in p.get('node.name',''): print('SRC',n['id'],p.get('node.name'),'codec=',p.get('api.bluez5.codec'))
"
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
for r in 1 2; do echo "===TEST $r (10s)==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/u$r.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/u$r.raw; done
