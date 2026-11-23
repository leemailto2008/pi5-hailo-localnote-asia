#!/usr/bin/env bash
# 在 Pi 上跑 tools/ 下的腳本：pi_run.sh <host> <script.sh>（同 pi_run.cmd）→ pi_probe_out/<host>_<script>.txt
# exit code = ssh 的 exit code；參數不對 exit 2。
source "$(dirname "$0")/pi_common.sh"
need_args $# 2 "<host> <script.sh>"
HOST=$1; SCRIPT=$2
need_script "$SCRIPT"
pi5_init_out
LOG="$OUT/${HOST}_$(basename "${SCRIPT%.*}").txt"
ssh "${SSHOPT[@]}" "pi@$HOST" bash -s < "$TOOLS_DIR/$SCRIPT" > "$LOG" 2>&1
RC=$?
echo "exit=$RC" >> "$LOG"
finish $RC
