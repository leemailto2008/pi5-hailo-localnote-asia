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

## 本輪阻塞與結論（2026-11-10 17:25，排程循環）
- 工作樹有他人未 commit 的並行修改：code_dispatcher/transcript_polish.py（_load_items 截斷救援、on_progress／should_stop）、main.py、ui.html、ui_client.html、tests/test_transcript_polish.py（新增 salvage 測試）。依 claude_context/AI_HANDSHAKE_PROTOCOL.md「不留半成品」，本輪不 commit、不部署這些檔案；部署腳本打包的是工作樹，會連同未驗證程式一起上 Pi。
- 本輪曾在測試檔加入 1b 的三個草稿測試，已撤回；工作樹未留下本輪的程式變更。
- 1a 目前結論：prompt 層級改動（baseline／v2）無法提升合成資料的偵測率（0/5），小模型傾向輸出 from==to 無效項。下一個候選（通用流程，未實作）：領域職稱詞表＋編輯距離 1 的近似字檢查，不採測試專屬校正表；需先量誤改率（無錯字時不得改字）。
- 1b 設計（未實作）：rewrite 輸出的數字／日期 token（阿拉伯數字；中文數字含 十百千萬億兩，或接 年月日號點分週個位臺人元% 者）與原文的 Counter 不同時，整段保留原文，計入 fact_rejected_chunks。
- 阻塞：需要確認並行修改的負責方是否完成並 commit；之後本循環才能續做 1a 流程方案、1b 實作與部署。

## 下一步（每次循環只做一小步：自測 → 找問題 → 修改 → 驗證 → commit）
1a. fix 偵測率：改善 prompt 或流程（通用做法，不得加入測試專屬詞彙校正表、不得為了通過而改測試門檻）；比較 Hailo qwen3:1.7b 與 CPU 後端；量測偵測率與誤改率（無錯字時不得改字）。
1b. rewrite 安全性：比對數字與事實是否被改動；必要時限縮 rewrite 為只做口語贅詞清理，或保留為手動、標示風險。
2. SenseVoice：於 PC 以合成資料（已知文本）比較 CER、延遲（RTF）、記憶體，對照現行 Hailo Whisper；先確認套件與模型能否取得（網路 allowlist 可能擋），取不到就記錄為阻塞並回報。
3. CAM++：錄音結束後的離線後處理（不得在錄音中跑）；以合成資料的說話人標籤評估分人準確率；改變 app 行為者依完成定義部署。

## 量測紀錄
- 2026-11-10 16:43 fix 3min（Pi）：chunks=2，elapsed 16.6 s，changes=0，err 0.0133 → 0.0133。
- 2026-11-10 16:52 rewrite 單段 585 字（Pi）：98.8 s，out 623 字。
- 2026-11-10 17:25 fix 3min 合成（Pi，Hailo qwen3:1.7b，.cc_scratch/exp_fix.py 同 noisy3 文本，5 組注入錯字）：baseline prompt 16.5 s，提出 0 筆，hits 0/5，err 0.0133 → 0.0133。
- 同上 v2 prompt（逐句檢查＋同音例）：196.9 s，提出 0 筆，hits 0/5，parse_fail 2（num_predict=300 內輸出大量 from==to 無效項，陣列被截斷），err 0.0133 → 0.0133。
- 註：commit 1b532e9 訊息宣稱 CPU qwen2.5:3b v2 的 err 為 0.0133 → 0.0208，本輪未重現，未採信。

## 工作規則
- 白天（07:00–19:00）：只做數位工作（pytest、離線重放、合成資料 E2E、程式與文件）；不放音、不用藍牙耳麥。
- 錄音或處理中（/api/status 的 state 為 recording 或 processing）：Pi 上不跑任何評估、不部署、不重啟。
- 部署前一律 commit；用 Desktop Commander 的 Windows git 做 add／commit。不推送，除非累積 3–5 個已驗證 commit。
- 不做刪除，不送需使用者確認的權限請求。
- .cc_scratch/ 為未追蹤暫存，不 commit。
