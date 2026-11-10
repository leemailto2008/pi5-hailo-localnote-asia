MAC=A0:D1:2A:42:12:34
echo "===RSSI samples (relative to golden range), 10 x 1s==="; for i in $(seq 1 10); do printf "%s " "$(hcitool rssi $MAC 2>&1 | grep -oE '[-0-9]+$')"; sleep 1; done; echo
echo "===LQ==="; hcitool lq $MAC 2>&1
echo "===TX power of Pi link==="; sudo -n hcitool tpl $MAC 0 2>&1; sudo -n hcitool tpl $MAC 1 2>&1
echo "===Controller inquiry RSSI of nearby devices (5s inquiry, dBm)==="; sudo -n timeout 8 hcitool -i hci0 inq --length=4 --flush 2>/dev/null | head; sudo -n timeout 6 hcitool -i hci0 scan --length=3 --flush 2>/dev/null | head -5
echo "===btmgmt find (BR/EDR, shows dBm rssi) 6s==="; sudo -n timeout 8 btmgmt find -b 2>/dev/null | grep -iE "rssi|name" | head -12
