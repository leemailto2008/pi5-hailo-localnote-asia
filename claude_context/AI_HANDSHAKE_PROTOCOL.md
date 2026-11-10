# AI_HANDSHAKE_PROTOCOL.md - Antigravity ↔ Claude 跨 AI 無縫接棒協定 (Cross-AI Handover Protocol)

本文件定義當 **Antigravity** 達到 Token Limit（或排程切換）時，**Claude** 如何透過 `F:\14_prj_raspi5_localnote_asia\claude_context` 目錄無縫接手，以及雙方如何保持記憶同步。

---

## 1. 給使用者的「一鍵交棒提示詞 (One-Line Handover Prompt)」

當 Antigravity 遇到 Token Limit 時，您只需要在 Claude Desktop 打開 `14_prj_raspi5_localnote_asia` 專案，貼上以下這句話即可：

> **「請先完整閱讀 `F:\14_prj_raspi5_localnote_asia\claude_context\CLAUDE.md` 與該資料夾內的所有檔案，繼承 Antigravity 的記憶與進度，直接接手執行 Loop Engineering 續測並改到最佳。」**

---

## 2. 雙向記憶同步規範 (Bi-Directional Memory Sync Rules)

為了確保 **Antigravity → Claude** 與 **Claude → Antigravity** 隨時都能在 0 上下文損失下互相接手，任一 AI 在工作期間必須遵守：

1. **狀態單一事實來源 (Single Source of Truth)：**
   - 架構決策與硬體避坑指南統一記錄於 [PROJECT_STATE.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/PROJECT_STATE.md)（同步鏡像於根目錄 `AGENTS.md` 與 `CLAUDE.md`）。
   - 當前最新 Commit、剛修好的問題與下一步待測佇列統一記錄於 [ACTIVE_BACKLOG_AND_NEXT_STEPS.md](file:///f:/14_prj_raspi5_localnote_asia/claude_context/ACTIVE_BACKLOG_AND_NEXT_STEPS.md)。
2. **每輪 Commit & Push 時同步更新交棒狀態：**
   - 每當完成一輪自測與修復（累積 3～5 個 commit 準備推送至 `gitlab` 與 `origin` 時），順手更新 `claude_context/ACTIVE_BACKLOG_AND_NEXT_STEPS.md` 的「近期已完成修復軌跡」與「待辦佇列」。
   - 若發現新的樹莓派硬體特性、Hailo NPU 限制或藍牙行為，立即增補至 `claude_context/PROJECT_STATE.md`。
3. **不留半成品原則 (Atomic State Rule)：**
   - 每次修改必須通過 `pytest` 離線單元測試後才可 Commit，確保另一個 AI 隨時接手時，`HEAD` 永遠處於可部署、可測試的乾淨狀態。

---

## 3. MCP 工具鏈分工建議 (MCP Toolchain Best Practices for Claude)

在 Claude Desktop (`Cowork` / `Code` 模式) 接手本專案時，已配置好以下工具組合：
- **Desktop Commander MCP (`desktop-commander`)：**
  - `allowedDirectories` 已授權：`F:\14_prj_raspi5_localnote_asia` 與 `F:\62_prj_my6601_cosim`。
  - **用途：** 直接在 Windows 本機執行 `git add`、`git commit`、`git push gitlab main`、`git push origin main`、Windows 端腳本與檔案編輯，完全避開 Linux VM 掛載層留下的 `.git/index.lock` 問題。
- **내建 Linux VM (`device_bash`) / SSH：**
  - **用途：** 執行 Linux 環境專屬的 `python3 -m pytest -q tests`（含 `fcntl` 與 POSIX pipe `select` 測試），以及透過 SSH 連線 `pi@192.168.50.228` 執行 `deploy_on_pi.sh` 與 `run_suite.py`。

