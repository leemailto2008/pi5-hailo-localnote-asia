NEWK=6.18.50+rpt-rpi-2712
echo "===DKMS BUILD hailo1x_pci for $NEWK==="
sudo -n dkms build -m hailo1x_pci -v 5.3.0 -k $NEWK 2>&1 | tail -5
sudo -n dkms install -m hailo1x_pci -v 5.3.0 -k $NEWK --force 2>&1 | tail -5
sudo -n dkms status 2>&1
KO=$(find /lib/modules/$NEWK -name "hailo1x_pci.ko*" 2>/dev/null | head -1); echo "module: $KO"
[ -n "$KO" ] && modinfo -k $NEWK hailo1x_pci | grep -E "^vermagic|^version"
echo "===BOOT CHECK==="; ls -la --time-style=long-iso /boot/firmware/kernel_2712.img /boot/firmware/initramfs_2712 2>/dev/null; grep -E "^(kernel|initramfs|auto_initramfs)" /boot/firmware/config.txt
if [ -n "$KO" ]; then
  echo "READY_TO_REBOOT=yes -> rebooting in 3s"; sync; (sleep 3; sudo -n systemctl reboot) >/dev/null 2>&1 &
else
  echo "READY_TO_REBOOT=no - NOT rebooting"
fi
