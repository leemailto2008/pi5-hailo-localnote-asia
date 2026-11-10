export DEBIAN_FRONTEND=noninteractive
echo "===MAKEFILE_VARS==="; grep -nE "^(KERNEL_DIR|KERNELRELEASE|KVER|MODULE_NAME|DKMS)|install_dkms:|dkms add|dkms build|dkms install" /usr/src/hailort-pcie-driver/linux/pcie/Makefile 2>/dev/null | head -12
echo "===INSTALL dkms + kernel 6.18.50 + headers==="
sudo -n apt-get install -y dkms linux-image-rpi-2712 linux-image-rpi-v8 linux-headers-rpi-2712 linux-headers-rpi-v8 raspi-firmware 2>&1 | grep -E "^(Setting up|Unpacking|E:|Err|dkms:|Building|Error)" | head -30
echo "---"; dpkg -l | grep -E "^ii  (linux-image-6|linux-headers-6|dkms|raspi-firmware)" | awk '{print $2, $3}'; ls /lib/modules/; ls -la --time-style=long-iso /boot/firmware/kernel_2712.img
NEWK=$(ls /lib/modules/ | grep 2712 | grep 6.18.50 | head -1); echo "NEWK=$NEWK"
[ -z "$NEWK" ] && { echo "ABORT: new kernel modules dir not found"; exit 1; }
[ -d /lib/modules/$NEWK/build ] || { echo "ABORT: no headers/build dir for $NEWK"; exit 1; }
echo "===BUILD HAILO DRIVER VIA DKMS FOR $NEWK==="
cd /usr/src/hailort-pcie-driver/linux/pcie && sudo -n make install_dkms 2>&1 | tail -15
sudo -n dkms status 2>&1
echo "--- force build/install for new kernel if missing"; sudo -n dkms build -m hailo_pci -v 5.3.0 -k $NEWK 2>&1 | tail -4; sudo -n dkms install -m hailo_pci -v 5.3.0 -k $NEWK --force 2>&1 | tail -4
sudo -n dkms status 2>&1
echo "===MODULE CHECK==="; find /lib/modules/$NEWK -name "hailo*pci*.ko*" 2>/dev/null; sudo -n depmod -a $NEWK 2>&1 | tail -2; modinfo -k $NEWK hailo1x_pci 2>/dev/null | grep -E "^filename|^vermagic|^version" || modinfo -k $NEWK hailo_pci 2>/dev/null | grep -E "^filename|^vermagic|^version"
KO=$(find /lib/modules/$NEWK -name "hailo*pci*.ko*" 2>/dev/null | head -1)
if [ -n "$KO" ]; then echo "READY_TO_REBOOT=yes"; else echo "READY_TO_REBOOT=no (driver missing for $NEWK) - NOT rebooting"; fi
