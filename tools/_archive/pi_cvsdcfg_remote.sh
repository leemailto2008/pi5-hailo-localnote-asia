export XDG_RUNTIME_DIR=/run/user/1000
echo "===WRITE wireplumber conf==="
sudo -n mkdir -p /etc/wireplumber/wireplumber.conf.d
sudo -n tee /etc/wireplumber/wireplumber.conf.d/51-bluez-cvsd.conf >/dev/null <<'CONF'
# Pi 5 Local Note — force HFP/HSP to CVSD (basic-rate EV3 packets).
# Measured 2026-10-22 on raspi543: mSBC (EDR 2-EV3) frames arrive 30–65% corrupted on this
# CYW43455 link (pkt_status=1), giving 20–70% silence after decode failures; CVSD gives ~1.5%.
monitor.bluez.properties = {
  bluez5.enable-msbc = false
}
CONF
cat /etc/wireplumber/wireplumber.conf.d/51-bluez-cvsd.conf | tail -3
echo "===RESTART wireplumber (user)==="; systemctl --user restart wireplumber; sleep 5; systemctl --user is-active wireplumber pipewire
echo "===RECONNECT headset==="; MAC=A0:D1:2A:42:12:34; bluetoothctl disconnect $MAC >/dev/null 2>&1; sleep 2; for i in $(seq 1 10); do bluetoothctl connect $MAC >/dev/null 2>&1; sleep 3; bluetoothctl info $MAC | grep -q "Connected: yes" && break; done; bluetoothctl info $MAC | grep Connected; sleep 3
pw-dump | python3 -c "
import sys,json
for n in json.load(sys.stdin):
    p=(n.get('info',{}).get('props',{}) or {})
    if p.get('device.api')=='bluez5' and n.get('type','').endswith('Device'): print('DEVICE',n['id'],p.get('device.description'),'profile=',[x.get('name') for x in n['info']['params'].get('Profile',[])],'enum=',[x.get('name') for x in n['info']['params'].get('EnumProfile',[])])
    if 'bluez_input_internal' in p.get('node.name',''): print('SRC',n['id'],p.get('node.name'),'codec=',p.get('api.bluez5.codec'),'rate=',p.get('audio.rate'))
"
DEV=$(pw-dump | python3 -c "import sys,json; print(next((n['id'] for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')),''))")
IDX=$(pw-dump | python3 -c "import sys,json; n=next(n for n in json.load(sys.stdin) if n['id']==$DEV); print(next((p['index'] for p in n['info']['params']['EnumProfile'] if p['name']=='headset-head-unit'),''))"); [ -n "$IDX" ] && wpctl set-profile $DEV $IDX; sleep 4
SRC=$(pw-dump | python3 -c "import sys,json; print(next((n['info']['props']['node.name'] for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')),'default'))"); echo "source=$SRC"
pw-dump | python3 -c "import sys,json; [print('  codec now =',(n['info']['props']).get('api.bluez5.codec')) for n in json.load(sys.stdin) if 'bluez_input_internal' in (n.get('info',{}).get('props',{}) or {}).get('node.name','')]"
cnt(){ journalctl -S "$1" -U "$2" --no-pager 2>/dev/null | grep -c "decode failed"; }
rec(){ taskset -c 0,1 ffmpeg -nostdin -v error -y -thread_queue_size 16384 -f pulse -ar 16000 -ac 1 -i "$1" -t $2 -f s16le -ac 1 -ar 16000 "$3"; }
echo "===VERIFY 10s==="; S=$(date "+%Y-%m-%d %H:%M:%S"); rec "$SRC" 10 /tmp/v1.raw; E=$(date "+%Y-%m-%d %H:%M:%S"); sleep 1; echo "  decode_failed=$(cnt "$S" "$E")"; python3 /tmp/analyze.py /tmp/v1.raw
echo "===API status==="; curl -s -m 5 http://127.0.0.1:80/api/bt/status | head -c 300; echo
