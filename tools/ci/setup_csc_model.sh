#!/bin/bash
# 在 Pi 上安裝潤稿「修同音字」的可選引擎 MacBERT4CSC（code_dispatcher/csc_corrector.py；PI5_POLISH_FIX_ENGINE=csc 才用）。
#   bash tools/ci/setup_csc_model.sh [模型目錄，預設 /home/pi/models/macbert4csc]
# - 套件 onnxruntime、tokenizers、opencc 裝在 pi 使用者的 site-packages（服務用 /usr/bin/python3）。
# - 模型 shibing624/macbert4csc-base-chinese 的 ONNX 版，約 474 MB；已存在且 sha256 相符就略過。
# - 錄音或整理中不執行（下載與 pip 會吃 CPU 與網路）。
set -euo pipefail

DIR="${1:-/home/pi/models/macbert4csc}"
HF=https://huggingface.co/shibing624/macbert4csc-base-chinese/resolve/main/onnx

state=$(curl -s -m 5 http://127.0.0.1:8000/api/status | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state",""))' || echo unknown)
case "$state" in
  recording|processing) echo "app 正在 $state，稍後再跑"; exit 75 ;;
esac

for mod in onnxruntime tokenizers opencc; do
  if ! python3 -c "import $mod" 2>/dev/null; then
    python3 -m pip install --user --break-system-packages "$mod"   # opencc：官方套件（用 t2s.json／s2twp.json 設定檔）
  fi
done
python3 -c 'import onnxruntime, tokenizers; print("onnxruntime", onnxruntime.__version__, "tokenizers", tokenizers.__version__)'

mkdir -p "$DIR"
cd "$DIR"
while read -r name sha; do
  if [ -f "$name" ] && echo "$sha  $name" | sha256sum -c --status; then
    echo "ok   $name"
    continue
  fi
  echo "get  $name"
  curl -sSL --fail -m 3600 -o "$name.part" "$HF/$name"
  echo "$sha  $name.part" | sha256sum -c --status || { echo "sha256 不符：$name"; exit 1; }
  mv "$name.part" "$name"
done <<EOF
model.onnx a4d9d6807c0c8bc9d014462a728e7212315630c669a6bd670b653154391a73f3
tokenizer.json 7dfbf1966ebf99d471c3796e9b457329d2b2182b817e144f1e904b957745c839
EOF
echo "macbert4csc ready in $DIR"
