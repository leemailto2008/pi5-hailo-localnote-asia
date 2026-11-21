#!/usr/bin/env bash
# 從 Pi 拉檔，選擇性先跑腳本：pi_pull.sh <host> <remote> <local> [script.sh]（同 pi_pull.cmd）
source "$(dirname "$0")/pi_common.sh"
HOST=$1; REMOTE=$2; LOCAL=$3; SCRIPT=${4:-}
if [ -n "$SCRIPT" ]; then
  LOG="$OUT/${HOST}_$(basename "${SCRIPT%.*}").txt"
  ssh "${SSHOPT[@]}" "pi@$HOST" bash -s < "$TOOLS_DIR/$SCRIPT" > "$LOG" 2>&1
  echo "exit=$?" >> "$LOG"
fi
scp "${SSHOPT[@]}" "pi@$HOST:$REMOTE" "$LOCAL" > "$OUT/${HOST}_pull.txt" 2>&1
echo "exit=$?" >> "$OUT/${HOST}_pull.txt"
echo done > "$OUT/DONE.flag"
