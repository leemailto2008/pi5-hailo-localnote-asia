#!/bin/bash
# 在 Pi 上安裝高精度逐字稿（code_dispatcher/refine_transcript.py）需要的 sherpa-onnx 與模型，以及潤稿用的 pypinyin。
#   bash tools/ci/setup_sherpa_models.sh [模型目錄，預設 /home/pi/models/sherpa]
# - sherpa-onnx 裝在 pi 使用者的 site-packages（服務用 /usr/bin/python3）。
# - 模型共約 275 MB；已存在且 md5 正確的檔案不重抓。
# - 不可在錄音中執行（下載與 pip 會吃 CPU 與網路）。
set -euo pipefail

DIR="${1:-/home/pi/models/sherpa}"
HF=https://huggingface.co/csukuangfj
GH=https://github.com/k2-fsa/sherpa-onnx/releases/download

state=$(curl -s -m 5 http://127.0.0.1:8000/api/status | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state",""))' || echo unknown)
case "$state" in
  recording|processing) echo "app 正在 $state，稍後再執行"; exit 75 ;;
esac

if ! python3 -c 'import sherpa_onnx' 2>/dev/null; then
  python3 -m pip install --user --break-system-packages sherpa-onnx
fi
python3 -c 'import sherpa_onnx; print("sherpa-onnx", sherpa_onnx.__version__)'
# 潤稿「修同音字與漏字」用 pypinyin 判斷同音（code_dispatcher/transcript_polish.py，2026-11-11）
if ! python3 -c 'import pypinyin' 2>/dev/null; then
  python3 -m pip install --user --break-system-packages pypinyin
fi
python3 -c 'import pypinyin; print("pypinyin", pypinyin.__version__)'

mkdir -p "$DIR"
cd "$DIR"
# 檔名 md5 下載網址
while read -r name md5 url; do
  if [ -f "$name" ] && echo "$md5  $name" | md5sum -c --status; then
    echo "ok   $name"
    continue
  fi
  echo "get  $name"
  curl -sSL --fail -m 1800 -o "$name.part" "$url"
  echo "$md5  $name.part" | md5sum -c --status || { echo "md5 不符：$name"; exit 1; }
  mv "$name.part" "$name"
done <<EOF
sensevoice_small_int8.onnx 0e8e550411d3589be9f0af06f1c8fec3 $HF/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/model.int8.onnx
sensevoice_tokens.txt 17cdd9d527315e28553153706d23c719 $HF/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/tokens.txt
silero_vad.onnx d486e9c504c9034316d53a9f4e0eee2e $GH/asr-models/silero_vad.onnx
pyannote_segmentation_3_0.onnx ad53cf2264883c6516d165cabebb1d60 $HF/sherpa-onnx-pyannote-segmentation-3-0/resolve/main/model.onnx
campplus_zh_cn_common.onnx 2ac7673f702e6e45ff45882a4dd55b1a $GH/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx
EOF
echo "模型就緒：$DIR"
