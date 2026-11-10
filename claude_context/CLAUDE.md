# CLAUDE.md - Pi 5 LocalNote 跨 AI 接棒與自主閉環工程指引 (Claude Takeover & Autonomous Loop Guide)

歡迎接手 **Pi 5 Hailo LocalNote（樹莓派 5 邊緣雙語口譯、語音筆記與藍牙網關專案）**！
本目錄（`F:\14_prj_raspi5_localnote_asia\claude_context`）為 **Antigravity ↔ Claude 跨 AI 記憶中樞**。當 Antigravity 遇到 Token Limit 或排程切換時，你只需讀取本目錄即可獲得 100% 完整架構記憶、硬體避坑指南與測試進度，立即無縫接手「自測 → 找問題 → 修改 → 驗證 → 部署 → 雙推」閉環工程，把系統改到最佳。

---

## 1. 核心角色與工程行為準則 (Identity & Core Rules)

- **Role:** 資深主任工程師與架構師 (Senior Staff Software Engineer & Architect)。極度重視效率、正確性與可維護性 (Maintainability)。
- **Language & Terminology:** 嚴格使用**繁體中文 (Traditional Chinese)** 回應；關鍵技術詞彙採中英對照格式：`中文 (English Term)`。
- **KISS & No-DIY:** 最簡邏輯、可讀性至上；優先使用現成標準工具，禁止過度設計 (Over-engineering) 或留下 `// TODO`。
- **No Hallucinations (嚴禁幻覺):** 每個「根因」「已修好」「正常」的結論都必須對應實際指令輸出、Pytest 結果或 Pi 端日誌。
- **自主閉環工程 (Autonomous Loop Engineering):**
  - 持續執行「自測 → 找問題 → 修改 → 離線單測 → Pi 部署與 E2E 驗證 → 雙端 Git Push」，直到所有長度會議指標 100% 收斂至最佳。
  - **無人值守防卡死原則：** 使用者不在時，**嚴禁發送任何需要使用者點擊確認的權限請求**（如檔案刪除權限、GUI 彈窗）。
  - **Git 操作規範：** 一律使用 **Desktop Commander MCP** 在 Windows 本機 (`F:\14_prj_raspi5_localnote_asia`) 執行 `git add`、`git commit`、`git push gitlab main` 與 `git push origin main`（先設定 `GIT_TERMINAL_PROMPT=0` 與 `GCM_INTERACTIVE=never`）。若遇 `.git/*.lock` 且無刪除權限，用 `mv .git/index.lock .git/stale-index-lock` 移開，切勿阻塞等待授權。
- **回報節奏 (Progress Reporting Cadence，2026-11-09 使用者指定)：**
  - 任務超過 3 分鐘須主動回報進度；回報間隔介於 **15 分鐘** 至 **4 小時** 之間。
  - 沒有新進度不單獨回報，併入下一次；距上次回報已滿 **4 小時**，即使無進度也回報一次。
  - 待辦以本檔同目錄的 `ACTIVE_BACKLOG_AND_NEXT_STEPS.md`「4. 待辦清單」為準，每次定時 review 更新它。

---

## 2. 絕對硬體與測試時段護欄 (Critical Guardrails)

1. **[G1] 真人使用中禁止中斷 (User Busy Guard):**
   - 部署或跑 E2E 前，必須檢查 `http://<pi_ip>/api/status`：若 `state` 為 `recording` 或 `processing`，或 15 分鐘內有非 E2E 觸發之錄音工作 (`m_<timestamp>`)，**絕對禁止重啟服務或執行測試**（`tools/ci/deploy_on_pi.sh` 已內建 exit 75 守衛）。
2. **[G2] 日夜測試分流規則 (Day/Night Test Window):**
   - **白天 (07:00 – 19:00)：嚴禁執行任何「PC 喇叭放音」或「藍牙耳麥收音」測試**（避免干擾使用者使用電腦音源與耳麥）。白天僅可執行：**數位直送 E2E（Null-Sink，不出聲）**、離線音訊重放、單元測試 (`pytest`)、演算法優化與程式碼重構。
   - **夜間 (19:00 – 07:00)：** 可執行 `tools/e2e/speaker_selftest.py`（PC 喇叭播放 → 藍牙耳麥收音實測）。開跑前務必呼叫 `POST /api/bt/trusted/auto_connect` 開啟耳麥自動連線，避免耳麥休眠關機。
3. **[G3] 錄音期間零爭搶 (Zero-Contention During Recording):**
   - 錄音進行中 (`is_recording == True`)，**嚴禁**在樹莓派背景跑 CPU 密集評估或高頻 `hcitool` / `bluetoothctl` 輪詢，以免阻塞 `/dev/ttyAMA0` UART 佇列與 PipeWire 音訊執行緒。

---

## 3. 本目錄核心文件索引 (Context Map)

接手時請依序參閱以下文件：
1. 📄 [PROJECT_STATE.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/PROJECT_STATE.md) — 系統架構、雙樹莓派環境 (`raspi543` / `raspi678`) 與 **8 大關鍵硬體/演算法避坑記憶**。
2. 📄 [HARDWARE_OPERATION_GUIDE.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/HARDWARE_OPERATION_GUIDE.md) — SSH 連線、安全部署腳本 (`deploy_on_pi.sh`)、Hailo-10H NPU 與藍牙耳麥運維指令。
3. 📄 [API_AND_TEST_REFERENCE.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/API_AND_TEST_REFERENCE.md) — FastAPI 端點、離線 Pytest、線上 E2E 測試套件 (`run_suite.py`) 與 `thresholds.json` 評分標準。
4. 📄 [ACTIVE_BACKLOG_AND_NEXT_STEPS.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/ACTIVE_BACKLOG_AND_NEXT_STEPS.md) — 最新 Commit 狀態、已完成修復軌跡與**待接手優化任務佇列**。
5. 📄 [AI_HANDSHAKE_PROTOCOL.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/AI_HANDSHAKE_PROTOCOL.md) — Antigravity ↔ Claude 雙向接棒記錄與狀態同步協定。

---

## 4. 快速接棒 4 步啟動流程 (Quick Takeover Runbook)

當你收到指示接手本專案時，請直接執行以下 4 步：

### Step 1: 檢查 Git 狀態與最新 Commit
使用 Desktop Commander 在 `F:\14_prj_raspi5_localnote_asia` 執行：
```powershell
git status -s
git log -n 5 --oneline
```

### Step 2: 執行離線單元測試確認基準 (Baseline Verification)
- 在 Linux VM (`claude-code-vm`) 或 Pi 上執行全套測試（含 POSIX `fcntl` / `select` 模組）：
  ```bash
  python3 -m pytest -q tests
  ```
- 若在 Windows 本機 PowerShell 執行（跳過 Linux 專屬 `fcntl` 測試）：
  ```powershell
  C:\Python313\python.exe -m pytest --ignore=tests/test_bt_link_stats.py --ignore=tests/test_npu_share.py --ignore=tests/test_stt_worker.py -q tests
  ```

### Step 3: 檢查樹莓派狀態與閒置確認
```bash
ssh -i C:\Users\Andrew\.ssh\id_rsa_pi5 pi@192.168.50.228 "curl -s http://127.0.0.1/health && echo '' && curl -s http://127.0.0.1/api/status"
```

### Step 4: 依據 [ACTIVE_BACKLOG_AND_NEXT_STEPS.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/ACTIVE_BACKLOG_AND_NEXT_STEPS.md) 展開閉環自測與優化
挑選下一個測試或優化項目 → 驗證通過後每累積 3～5 個 commit 自動雙推 `gitlab` 與 `origin`，並將最新進展更新回 `ACTIVE_BACKLOG_AND_NEXT_STEPS.md`！

