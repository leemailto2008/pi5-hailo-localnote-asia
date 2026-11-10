echo "===USB==="; lsusb; echo; for d in /sys/bus/usb/devices/usb*; do echo "$(basename $d): $(cat $d/speed 2>/dev/null)Mbps $(cat $d/product 2>/dev/null)"; done
echo "===USB_DEVICES_SPEED==="; for d in /sys/bus/usb/devices/[0-9]-[0-9]*; do [ -f $d/speed ] && echo "$(basename $d): $(cat $d/speed)Mbps $(cat $d/manufacturer 2>/dev/null) $(cat $d/product 2>/dev/null)"; done
echo "===THROTTLE/POWER==="; vcgencmd get_throttled; vcgencmd measure_volts; vcgencmd measure_clock arm
echo "===BT_INQUIRY_SCAN_STATE==="; bluetoothctl show | grep -E "Discoverable|Pairable|Discovering"; sudo -n btmgmt info 2>/dev/null | grep "current settings"
echo "===LE ADV/SCAN active?==="; sudo -n timeout 4 btmon 2>/dev/null | grep -cE "LE Advertising Report|LE Meta Event"
echo "===2.4G NEIGHBOURS==="; sudo -n nmcli -f SSID,CHAN,FREQ,SIGNAL dev wifi list --rescan yes 2>/dev/null | awk '$3<3000' | sort -k4 -nr | head -12
echo "===ACL LINK POLICY==="; hcitool con; sudo -n hcitool lp A0:D1:2A:42:12:34 2>/dev/null; sudo -n hcitool lst A0:D1:2A:42:12:34 2>/dev/null
