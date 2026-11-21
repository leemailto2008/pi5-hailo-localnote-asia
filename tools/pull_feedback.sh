#!/usr/bin/env bash
# 從盒子拉回全部 Issue 回報（同 pull_feedback.ps1）：pull_feedback.sh [box] [port] → .cc_scratch/feedback/<box>_<時間>/
BOX=${1:-192.168.50.228}; PORT=${2:-8000}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTDIR="$ROOT/.cc_scratch/feedback/${BOX}_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTDIR"
curl -sf -m 120 -o "$OUTDIR/feedback.zip" "http://$BOX:$PORT/api/feedback/export.zip" || { echo "下載失敗（盒子 $BOX 連得上嗎？）" >&2; exit 1; }
(cd "$OUTDIR" && unzip -q -o feedback.zip)
echo "拉回 $(find "$OUTDIR" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ') 筆回報 → $OUTDIR"
