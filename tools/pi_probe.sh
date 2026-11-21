#!/usr/bin/env bash
# 兩台 Pi 跑 pi_probe_remote.sh：pi_probe.sh [host...]（預設 .228 .229；同 pi_probe.cmd）
# 注意：pi_probe_remote.sh 會跑 bluetoothctl，錄音中不要對該台用（CLAUDE.md 重點一）。
source "$(dirname "$0")/pi_common.sh"
HOSTS=("$@"); [ ${#HOSTS[@]} -eq 0 ] && HOSTS=(192.168.50.228 192.168.50.229)
for H in "${HOSTS[@]}"; do
  echo "[$(date +%T)] probing $H ..."
  ssh "${SSHOPT[@]}" "pi@$H" bash -s < "$TOOLS_DIR/pi_probe_remote.sh" > "$OUT/$H.txt" 2>&1
  echo "exit=$?" >> "$OUT/$H.txt"
done
echo done > "$OUT/DONE.flag"
