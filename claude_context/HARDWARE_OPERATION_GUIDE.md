# HARDWARE_OPERATION_GUIDE.md - 樹莓派遠端運維、安全部署與藍牙控制手冊 (Hardware & Deployment Guide)

本文件提供對 `raspi678` (`192.168.50.228`) 與 `raspi543` (`192.168.50.229`) 進行遠端探測、安全部署、藍牙耳麥管理與雙端 Git 推送之標準操作指令。

---

## 1. SSH 遠端連線與輔助腳本 (SSH & Helper Scripts)

- **SSH 私鑰路徑：** `C:\Users\Andrew\.ssh\id_rsa_pi5`
- **直接執行遠端指令：**
  ```powershell
  ssh -i C:\Users\Andrew\.ssh\id_rsa_pi5 -o StrictHostKeyChecking=no pi@192.168.50.228 "<command>"
  ```
- **專案內建輔助工具 (`tools/`)：**
  - `tools\pi_run.cmd <ip> <script.sh>`: 將本地腳本送上 Pi 執行並將輸出存回 `tools\pi_probe_out\`。
  - `tools\pi_push.cmd <ip> <local_file> <remote_path> [post_script.sh]`: 推送單檔並可選執行腳本。
  - `tools\pi_pull.cmd <ip> <remote_path> <local_path>`: 從 Pi 拉回測試報告或音訊樣本。

---

## 2. 安全部署標準流程 (Safe Deployment Runbook)

### ⚠️ 部署前鐵律 (Pre-Deployment Busy Guard)
部署前**必須**確認沒有真人正在使用系統錄音或處理紀要：
```bash
curl -s -m 5 http://192.168.50.228:8000/api/status
```
- 若 `state` 為 `recording` 或 `processing`，**嚴禁部署或重啟服務**。
- 若 `job` 為 `m_<timestamp>`（距離現在 15 分鐘內）且不在 `/dev/shm/ln_e2e_jobs.txt` 內，代表有真人在網頁上操作，**嚴禁打斷**。

### 使用 `deploy_on_pi.sh` 自動備份、部署與健康檢查回滾
[tools/ci/deploy_on_pi.sh](file:///f:/13_prj_raspi5_localnote/tools/ci/deploy_on_pi.sh) 內建 4 階段安全機制：
1. **忙碌守衛 (Busy Check)：** 若忙碌則以 `exit 75` 安全退出。
2. **語法檢查 (`py_compile`)：** 預先檢查 `code_dispatcher/*.py` 與 `hailo_whisper/*.py`。
3. **自動備份與同步：**
   - 備份現有版本至 `/home/pi/code_dispatcher/.deploy_backup/<timestamp>/`（自動保留最近 10 份）。
   - 複製 `code_dispatcher/*.py`、`ui.html`、`static/`、`hailo_whisper/*.py`。
   - **注意：** `ui.html` 為唯一前端原始檔，腳本會自動將其複製為 `ui_client.html`、`static/ui_client.html` 與 `static/index.html`。
4. **重啟與健康檢查回滾 (Auto-Rollback)：**
   - 執行 `sudo -n systemctl restart pi5-dispatcher-api.service`。
   - 輪詢 `http://127.0.0.1/health` 並檢查 `journalctl -u pi5-dispatcher-api.service` 是否出現 `Traceback / ImportError / SyntaxError`；若失敗會**自動回滾 (Rollback)** 至上一版備份。

**從本機同步最新 Commit 到 Pi 並部署：**
```bash
# 1. 先在 Windows 本機透過 Desktop Commander 推送至 gitlab / origin
# 2. 在 Pi 上拉取並執行安全部署腳本：
ssh -i C:\Users\Andrew\.ssh\id_rsa_pi5 pi@192.168.50.228 "cd ~/pi5-hailo-localnote && git pull gitlab main && bash tools/ci/deploy_on_pi.sh"
```
*(若直接在開發中測試未 push 的檔案，亦可先 `scp -i C:\Users\Andrew\.ssh\id_rsa_pi5` 至 Pi 的暫存目錄再跑 `deploy_on_pi.sh`)*。

---

## 3. 藍牙耳麥與聲學測試運維 (Bluetooth Headset Operations)

1. **開啟受信任耳麥「自動連線 (Auto-Connect)」(防休眠關機)：**
   在夜間 (19:00–07:00) 執行聲學自測前，務必開啟耳麥自動連線，避免測試間隔耳麥休眠斷電：
   ```bash
   curl -s -X POST http://192.168.50.228:8000/api/bt/trusted/auto_connect \
     -H "Content-Type: application/json" \
     -d '{"mac": "<耳麥_MAC>", "auto_connect": true}'
   ```
2. **查詢目前藍牙連線狀態與受信任清單：**
   ```bash
   curl -s http://192.168.50.228:8000/api/bt/status
   curl -s http://192.168.50.228:8000/api/bt/trusted
   ```
3. **聲學測試前 30 秒防呆檢查：**
   - 夜間啟動 `speaker_selftest.py` 後，觀察前 30 秒的即時逐字稿：若未收到正常語音或僅出現重複幻覺句（如 `"I'm a little bit of..."`），代表 PC 喇叭音源未切對或耳麥已關機，應立即中止測試並改跑數位直送 E2E (`Null-Sink`)。

---

## 4. Hailo-10H NPU 與 LLM 狀態檢查 (NPU & LLM Diagnostics)

1. **檢查 `/health` 與當前 LLM 後端 (`hailo` vs `cpu`)：**
   ```bash
   curl -s http://192.168.50.228:8000/health
   ```
   - 回傳範例：`{"status": "ok", "llm_backend": "hailo", ...}`
2. **檢查 `hailo-ollama` (Port 11435) 與 CPU `ollama` (Port 11434)：**
   ```bash
   ssh -i C:\Users\Andrew\.ssh\id_rsa_pi5 pi@192.168.50.228 "curl -s http://127.0.0.1:11435/api/tags && curl -s http://127.0.0.1:11434/api/tags"
   ```
3. **查看服務即時日誌：**
   ```bash
   ssh -i C:\Users\Andrew\.ssh\id_rsa_pi5 pi@192.168.50.228 "journalctl -u pi5-dispatcher-api.service -n 80 --no-pager"
   ```

---

## 5. Git 雙遠端同步規範 (Git Dual-Remote Push via Desktop Commander)

- **工作目錄：** `F:\13_prj_raspi5_localnote`（已加入 Desktop Commander `allowedDirectories` 白名單）。
- **每累積 3～5 個已驗證的 Commit 自動推送：**
  透過 **Desktop Commander MCP (`start_process`)** 在 Windows PowerShell 執行：
  ```powershell
  $env:GIT_TERMINAL_PROMPT="0"
  $env:GCM_INTERACTIVE="never"
  git -C F:\13_prj_raspi5_localnote push gitlab main
  git -C F:\13_prj_raspi5_localnote push origin main
  ```
- **處理殘留 `.git/*.lock` 檔案：**
  若遇 `.git/index.lock` 或 `.git/HEAD.lock`，直接用 `Move-Item` 改名移開（例如 `stale-index-lock`），**切勿發起刪除權限彈窗阻塞自動化迴圈**。

