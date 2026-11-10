# BIG_CHANGE_STATUS.md — 大改三項循環狀態（2026-11-10 起）

## 目標與順序（使用者指定）
1. 潤稿區（待辦 #11）→ 2. SenseVoice 比較（ASR 品質與效能）→ 3. CAM++ 分說話人

## 完成定義（DONE）
三項都要符合：
- 已實作；或已有結論（採用／不採用）與理由。
- 以 tools/e2e/fixtures 合成資料量測，數值寫入下方「量測紀錄」。
- 若改變 app 行為：已 commit、依 tools/ci/deploy_on_pi.sh 部署、健康檢查通過、功能在 raspi678 上實測。
三項全部 DONE：本檔標 DONE、停用本循環排程（update_trigger enabled=false）、回報使用者。

## 現況（2026-11-10 16:45）
- 1 潤稿區：commit c00999d（feat），已部署 raspi678（備份 /home/pi/code_dispatcher/.deploy_backup/20261110_164305）。/ 首頁已含潤稿面板。
- 量測 fix（Hailo-10H qwen3:1.7b，合成 3 分鐘，注入 5 組同音錯字）：偵測 0/5，錯誤率 0.0133 → 0.0133。模型對每段輸出的是無效修改（如 [{"from":"供應商","to":"供應商"}]），被程式丟棄。
- 量測 rewrite（同模型，單段 585 字）：98.8 秒，輸出 623 字。3 分鐘約 2 段；60 分鐘約 23 段（推算約 38 分鐘）。注入錯字原樣保留。
- 抽查：rewrite 輸出的「六月十四日」「兩百萬」「二月三日」與原文一致（原文即為中文數字）；尚未以事實召回全面驗證。

## 下一步（每次循環只做一小步：自測 → 找問題 → 修改 → 驗證 → commit）
1a. fix 偵測率：改善 prompt 或流程（通用做法，不得加入測試專屬詞彙校正表、不得為了通過而改測試門檻）；比較 Hailo qwen3:1.7b 與 CPU 後端；量測偵測率與誤改率（無錯字時不得改字）。
1b. rewrite 安全性：比對數字與事實是否被改動；必要時限縮 rewrite 為只做口語贅詞清理，或保留為手動、標示風險。
2. SenseVoice：於 PC 以合成資料（已知文本）比較 CER、延遲（RTF）、記憶體，對照現行 Hailo Whisper；先確認套件與模型能否取得（網路 allowlist 可能擋），取不到就記錄為阻塞並回報。
3. CAM++：錄音結束後的離線後處理（不得在錄音中跑）；以合成資料的說話人標籤評估分人準確率；改變 app 行為者依完成定義部署。

## 量測紀錄
- 2026-11-10 16:43 fix 3min（Pi）：chunks=2，elapsed 16.6 s，changes=0，err 0.0133 → 0.0133。
- 2026-11-10 16:52 rewrite 單段 585 字（Pi）：98.8 s，out 623 字。

## 工作規則
- 白天（07:00–19:00）：只做數位工作（pytest、離線重放、合成資料 E2E、程式與文件）；不放音、不用藍牙耳麥。
- 錄音或處理中（/api/status 的 state 為 recording 或 processing）：Pi 上不跑任何評估、不部署、不重啟。
- 部署前一律 commit；用 Desktop Commander 的 Windows git 做 add／commit。不推送，除非累積 3–5 個已驗證 commit。
- 不做刪除，不送需使用者確認的權限請求。
- .cc_scratch/ 為未追蹤暫存，不 commit。
