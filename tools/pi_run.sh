#!/usr/bin/env bash
# 在 Pi 上跑 tools/ 下的腳本：pi_run.sh <host> <script.sh>（同 pi_run.cmd）→ pi_probe_out/<host>_<script>.txt
source "$(dirname "$0")/pi_common.sh"
HOST=$1; SCRIPT=$2; LOG="$OUT/${HOST}_$(basename "${SCRIPT%.*}").txt"
ssh "${SSHOPT[@]}" "pi@$HOST" bash -s < "$TOOLS_DIR/$SCRIPT" > "$LOG" 2>&1
echo "exit=$?" >> "$LOG"
echo done > "$OUT/DONE.flag"
