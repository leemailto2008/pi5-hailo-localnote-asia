#!/usr/bin/env bash
# 網路檢查（同 net_probe.cmd，Mac／Linux 指令）：ping 兩台 Pi、ARP 表、本機 IP → pi_probe_out/net_probe.txt
source "$(dirname "$0")/pi_common.sh"
{
  echo "=== ping .229 / .228"
  case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) PING=(ping -n 1 -w 2000);; *) PING=(ping -c 1 -W 2);; esac   # Git Bash 用 Windows 的 ping
  for H in 192.168.50.229 192.168.50.228; do "${PING[@]}" "$H" >/dev/null 2>&1 && echo "$H reachable" || echo "$H unreachable"; done
  echo "=== arp table for 192.168.50.x"; arp -a 2>/dev/null | grep -a "192.168.50"
  echo "=== my ip"; (ifconfig 2>/dev/null || ip -4 addr 2>/dev/null || ipconfig 2>/dev/null) | grep -aE "inet (192|10)\.|IPv4"
} > "$OUT/net_probe.txt" 2>&1
echo done > "$OUT/DONE.flag"
