#!/usr/bin/env bash
# 傳檔到 Pi，選擇性接著跑腳本：pi_push.sh <host> <local> <remote> [script.sh]（同 pi_push.cmd）
source "$(dirname "$0")/pi_common.sh"
HOST=$1; LOCAL=$2; REMOTE=$3; SCRIPT=${4:-}
scp "${SSHOPT[@]}" "$LOCAL" "pi@$HOST:$REMOTE" > "$OUT/${HOST}_push.txt" 2>&1
echo "exit=$?" >> "$OUT/${HOST}_push.txt"
if [ -n "$SCRIPT" ]; then
  LOG="$OUT/${HOST}_$(basename "${SCRIPT%.*}").txt"
  ssh "${SSHOPT[@]}" "pi@$HOST" bash -s < "$TOOLS_DIR/$SCRIPT" > "$LOG" 2>&1
  echo "exit=$?" >> "$LOG"
fi
echo done > "$OUT/DONE.flag"
