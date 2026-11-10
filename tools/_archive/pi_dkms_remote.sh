echo "===DKMS==="; which dkms && sudo -n dkms status 2>&1
echo "===HAILO_PKGS==="; dpkg -l | grep -iE "hailo" | awk '{print $2, $3}'
echo "===HAILO_MODULE==="; lsmod | grep -i hailo; modinfo hailo_pci 2>/dev/null | grep -E "^filename|^version|^vermagic"; ls /lib/modules/*/updates/dkms/ 2>/dev/null; ls /lib/modules/
echo "===HAILO_SRC==="; ls /usr/src/ | grep -i hailo; ls /home/pi/hailo530_pkgs/
echo "===DISK==="; df -h / | tail -1
echo "===APT_SIM==="; sudo -n apt-get -s full-upgrade 2>/dev/null | grep -E "^Inst|upgraded,|^Remv" | head -40
