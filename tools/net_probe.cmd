@echo off
set OUT=%~dp0pi_probe_out
del /q "%OUT%\DONE.flag" 2>nul
(
echo === ping .229 / .228
ping -n 1 -w 1500 192.168.50.229 | findstr /i "TTL timed unreachable"
ping -n 1 -w 1500 192.168.50.228 | findstr /i "TTL timed unreachable"
echo === nslookup raspi543
nslookup raspi543 2>&1 | findstr /i "Address Name"
echo === arp table for 192.168.50.x
arp -a | findstr /i "192.168.50"
echo === my ip
ipconfig | findstr /i "IPv4"
) > "%OUT%\net_probe.txt" 2>&1
echo done > "%OUT%\DONE.flag"
