export XDG_RUNTIME_DIR=/run/user/1000
echo "loop2 still running: $(pgrep -f loop2.sh | wc -l)"; pkill -f loop2.sh 2>/dev/null; echo "cvsd conf: $(ls /etc/wireplumber/wireplumber.conf.d/ 2>/dev/null) off: $(ls /tmp/*.off 2>/dev/null)"
[ -f /tmp/51-bluez-cvsd.conf.off ] && sudo -n mv /tmp/51-bluez-cvsd.conf.off /etc/wireplumber/wireplumber.conf.d/51-bluez-cvsd.conf && systemctl --user restart wireplumber && echo "cvsd conf restored"
echo "===BT==="; bluetoothctl show | grep -E "Powered|Discovering"; bluetoothctl devices Paired; bluetoothctl devices Connected; bluetoothctl info A0:D1:2A:42:12:34 | grep -E "Connected|Paired|Trusted"
echo "===PW==="; systemctl --user is-active pipewire wireplumber; pw-dump 2>/dev/null | python3 -c "import sys,json; print('bluez devices:', [ (n['info']['props'].get('device.description'), [x.get('name') for x in n['info']['params'].get('Profile',[])]) for n in json.load(sys.stdin) if (n.get('info',{}).get('props',{}) or {}).get('device.api')=='bluez5' and n.get('type','').endswith('Device')])"
echo "===TRY CONNECT==="; for i in 1 2 3; do bluetoothctl connect A0:D1:2A:42:12:34 2>&1 | tail -1; sleep 3; bluetoothctl info A0:D1:2A:42:12:34 | grep -q "Connected: yes" && break; done; bluetoothctl info A0:D1:2A:42:12:34 | grep Connected
echo "===API view==="; curl -s -m 5 http://127.0.0.1:80/api/bt/status | python3 -c "import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ('connected','connected_name','rssi','rssi_kind')})"
journalctl -u bluetooth -S -10m --no-pager | tail -5
