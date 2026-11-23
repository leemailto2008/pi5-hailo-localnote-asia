# shellcheck shell=bash
# shell 版共用設定（Mac／Linux／Git Bash；對應 Windows 的 *.cmd，2026-11-21 搬到 Mac 的準備）
# ssh 金鑰：環境變數 PI5_SSH_KEY 可覆寫，預設 ~/.ssh/id_rsa_pi5。輸出放 tools/pi_probe_out/（已 gitignore），同 cmd 版；
# PI5_PROBE_OUT 可改輸出位置（測試用）。只用 bash 3.2（macOS 內建）與 BSD／GNU 共通的指令。
TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY="${PI5_SSH_KEY:-$HOME/.ssh/id_rsa_pi5}"
OUT="${PI5_PROBE_OUT:-$TOOLS_DIR/pi_probe_out}"
# shellcheck disable=SC2034  # 給 source 這支的腳本用
SSHOPT=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=6)

# 參數不夠就印 usage、exit 2（不建輸出目錄、不連線）：need_args <實際個數> <最少個數> "<usage>"
need_args() {
  if [ "$1" -lt "$2" ]; then
    echo "usage: $(basename "$0") $3" >&2
    exit 2
  fi
}

# tools/ 下要送到 Pi 跑的腳本必須存在：need_script <檔名>
need_script() {
  if [ ! -f "$TOOLS_DIR/$1" ]; then
    echo "$(basename "$0"): 找不到 $TOOLS_DIR/$1" >&2
    exit 2
  fi
}

# 標記完成（cmd 版的 DONE.flag，輪詢用），並以 $1 結束
finish() {
  echo "done" > "$OUT/DONE.flag"
  exit "${1:-0}"
}

pi5_init_out() {
  mkdir -p "$OUT"
  rm -f "$OUT/DONE.flag"
}
