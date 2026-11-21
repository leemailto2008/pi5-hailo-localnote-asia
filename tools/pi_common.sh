# shell 版共用設定（Mac／Linux／Git Bash；對應 Windows 的 *.cmd，2026-11-21 搬到 Mac 的準備）
# ssh 金鑰：環境變數 PI5_SSH_KEY 可覆寫，預設 ~/.ssh/id_rsa_pi5。輸出放 tools/pi_probe_out/（已 gitignore），同 cmd 版。
TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEY="${PI5_SSH_KEY:-$HOME/.ssh/id_rsa_pi5}"
OUT="$TOOLS_DIR/pi_probe_out"
SSHOPT=(-i "$KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=6)
mkdir -p "$OUT"
rm -f "$OUT/DONE.flag"
