#!/usr/bin/env bash
# 網路檢查（同 net_probe.cmd，Mac／Linux／Git Bash）：ping 兩台 Pi、ARP 表、本機 IP → pi_probe_out/net_probe.txt
# ping 逾時參數各平台不同：GNU iputils 的 -W 是「秒」，macOS／BSD 的 -W 是「毫秒」（-W 2 等於 2 ms，永遠判成連不上），
# 所以 BSD 用 -t（整個 ping 的秒數上限）；Git Bash 用 Windows 的 ping。
source "$(dirname "$0")/pi_common.sh"
pi5_init_out
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) PING=(ping -n 1 -w 2000) ;;
  Darwin|*BSD|DragonFly) PING=(ping -c 1 -t 2) ;;
  *) PING=(ping -c 1 -W 2) ;;
esac
{
  echo "=== ping .229 / .228"
  for H in 192.168.50.229 192.168.50.228; do
    if "${PING[@]}" "$H" >/dev/null 2>&1; then echo "$H reachable"; else echo "$H unreachable"; fi
  done
  # -n：不反查 DNS（離線時 arp -a 每筆都要等 DNS 逾時）；沒有 net-tools 的 Linux 用 ip neigh
  echo "=== arp table for 192.168.50.x"
  { arp -an 2>/dev/null || ip neigh 2>/dev/null; } | grep -a "192\.168\.50\."
  # macOS ifconfig：「inet 192.168.x.x」；舊 net-tools：「inet addr:192.168.x.x」；iproute2：「inet 192.168.x.x/24」
  echo "=== my ip"
  { ifconfig 2>/dev/null || ip -4 addr 2>/dev/null || ipconfig 2>/dev/null; } | grep -aE "inet (addr:)?(192|10)\.|IPv4"
} > "$OUT/net_probe.txt" 2>&1
finish 0
