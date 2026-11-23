#!/usr/bin/env bash
# 傳檔到 Pi，選擇性接著跑腳本：pi_push.sh <host> <local> <remote> [script.sh]（同 pi_push.cmd）
# scp 失敗就不跑腳本；exit code = 第一個失敗步驟的 exit code；參數不對 exit 2。
source "$(dirname "$0")/pi_common.sh"
need_args $# 3 "<host> <local> <remote> [script.sh]"
HOST=$1; LOCAL=$2; REMOTE=$3; SCRIPT=${4:-}
[ -n "$SCRIPT" ] && need_script "$SCRIPT"
pi5_init_out
scp "${SSHOPT[@]}" "$LOCAL" "pi@$HOST:$REMOTE" > "$OUT/${HOST}_push.txt" 2>&1
RC=$?
echo "exit=$RC" >> "$OUT/${HOST}_push.txt"
if [ $RC -eq 0 ] && [ -n "$SCRIPT" ]; then
  LOG="$OUT/${HOST}_$(basename "${SCRIPT%.*}").txt"
  ssh "${SSHOPT[@]}" "pi@$HOST" bash -s < "$TOOLS_DIR/$SCRIPT" > "$LOG" 2>&1
  RC=$?
  echo "exit=$RC" >> "$LOG"
fi
finish $RC
