#!/usr/bin/env bash
# 從盒子拉回全部 Issue 回報（同 pull_feedback.ps1）：pull_feedback.sh [box] [port] → .cc_scratch/feedback/<box>_<時間>/
# PI5_FEEDBACK_DIR 可改輸出根目錄（測試用）。沒有 unzip（Git Bash、精簡版 Linux）時改用 python3 -m zipfile。
BOX=${1:-192.168.50.228}; PORT=${2:-8000}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTDIR="${PI5_FEEDBACK_DIR:-$ROOT/.cc_scratch/feedback}/${BOX}_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR" || exit 1
curl -sf -m 120 -o "$OUTDIR/feedback.zip" "http://$BOX:$PORT/api/feedback/export.zip" || { echo "下載失敗（盒子 $BOX 連得上嗎？）" >&2; exit 1; }
if command -v unzip >/dev/null 2>&1; then
  (cd "$OUTDIR" && unzip -q -o feedback.zip) || { echo "解壓縮失敗：$OUTDIR/feedback.zip" >&2; exit 1; }
elif command -v python3 >/dev/null 2>&1; then
  (cd "$OUTDIR" && python3 -m zipfile -e feedback.zip .) || { echo "解壓縮失敗：$OUTDIR/feedback.zip" >&2; exit 1; }
else
  echo "沒有 unzip 也沒有 python3，zip 留在 $OUTDIR/feedback.zip" >&2; exit 1
fi
# wc -l 在 BSD 會補前導空白，用 tr 去掉
echo "拉回 $(find "$OUTDIR" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ') 筆回報 → $OUTDIR"
