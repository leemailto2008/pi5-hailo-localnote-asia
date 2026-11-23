#!/usr/bin/env bash
# 從 Pi 拉檔，選擇性先跑腳本：pi_pull.sh <host> <remote> <local> [script.sh]（同 pi_pull.cmd）
# 腳本失敗仍照拉（拉回的可能就是要看的錯誤紀錄）；exit code = 第一個失敗步驟的 exit code；參數不對 exit 2。
source "$(dirname "$0")/pi_common.sh"
need_args $# 3 "<host> <remote> <local> [script.sh]"
HOST=$1; REMOTE=$2; LOCAL=$3; SCRIPT=${4:-}
[ -n "$SCRIPT" ] && need_script "$SCRIPT"
pi5_init_out
RC=0
if [ -n "$SCRIPT" ]; then
  LOG="$OUT/${HOST}_$(basename "${SCRIPT%.*}").txt"
  ssh "${SSHOPT[@]}" "pi@$HOST" bash -s < "$TOOLS_DIR/$SCRIPT" > "$LOG" 2>&1
  RC=$?
  echo "exit=$RC" >> "$LOG"
fi
scp "${SSHOPT[@]}" "pi@$HOST:$REMOTE" "$LOCAL" > "$OUT/${HOST}_pull.txt" 2>&1
SCP_RC=$?
echo "exit=$SCP_RC" >> "$OUT/${HOST}_pull.txt"
[ $RC -eq 0 ] && RC=$SCP_RC
finish $RC
