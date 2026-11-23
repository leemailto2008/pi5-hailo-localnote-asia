#!/usr/bin/env bash
# 兩台 Pi 跑 pi_probe_remote.sh：pi_probe.sh [host...]（預設 .228 .229；同 pi_probe.cmd）
# 注意：pi_probe_remote.sh 會跑 bluetoothctl，錄音中不要對該台用（CLAUDE.md 重點一）。
# exit code：全部成功 0，否則最後一個失敗主機的 ssh exit code。
source "$(dirname "$0")/pi_common.sh"
if [ $# -eq 0 ]; then set -- 192.168.50.228 192.168.50.229; fi
pi5_init_out
RC=0
for H in "$@"; do
  echo "[$(date +%H:%M:%S)] probing $H ..."
  ssh "${SSHOPT[@]}" "pi@$H" bash -s < "$TOOLS_DIR/pi_probe_remote.sh" > "$OUT/$H.txt" 2>&1
  R=$?
  echo "exit=$R" >> "$OUT/$H.txt"
  [ $R -ne 0 ] && RC=$R
done
finish $RC
