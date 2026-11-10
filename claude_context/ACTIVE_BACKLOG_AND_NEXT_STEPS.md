# ACTIVE_BACKLOG_AND_NEXT_STEPS.md - 專案進度、近期修復軌跡與接手待辦清單 (Active Backlog & Loop Engineering Queue)

本文件紀錄截至最新 Commit 之工程進度與下一階段 **Loop Engineering（持續自測 → 找問題 → 修改 → 驗證）** 任務佇列。每次完成一輪優化與推送後，請同步更新本文件。

---

## 1. 近期已完成修復軌跡 (Recent Verified Commits — 截至 `b05108c`)

- **`b05108c`** `fix(summary): pass maxsplit by keyword to silence Py3.13 re.split DeprecationWarning`（2026-11-09 已推送 gitlab / origin）
  - `summary_utils.py` 6 處 `re.split(..., 1)` 改為 `maxsplit=1`；離線 pytest 由 145 warnings 降為 0，行為不變。
- **`8302fa8`** `fix(minutes): treat a truncated "## 要" heading as the summary section`
  - 修補小型 LLM (`qwen3:1.7b` / `qwen2.5:3b`) 偶發輸出截斷標題 `## 要`（原為 `## 重點摘要`）導致摘要段落未被識別的問題。
- **`dca55a8`** `fix(stt): recap "決意施" / "像是" garbles that hid the 3-minute supplier decision`
  - 修補 3 分鐘會議結尾總結中「決議是」被辨識為「決意施／像是」導致供應商決議遺失的問題。
- **`6147009` / `52a3598` / `c0e7b4e` / `337947c` / `aa4e51f`** (`night9_*` 夜間 10/30 分鐘喇叭聲學實測收斂)
  - 針對夜間 `night9_m10`、`night9_m30`、`night9_m30b`、`night9_m10c`、`night9_m30c` 實境聲學收音結果，修補「吳副理」、「報名/名額」、「電源-in器→電源供應器」、「預警+日期」與結尾 Recap 同音訛誤。
- **`6715bb4` / `4627d5f` / `35e82a1` / `f7e286d` / `05f565c`** (`night8_*` 夜間 3/10/30 分鐘聲學實測收斂)
  - 修補「待分事向→待辦事項」、過濾結尾無實質意義的「今天做到這裡」贅句、消除待辦期限多餘的「前」字，並確保英文待辦列與中文待辦不重複。
- **`01581fc`** `chore(e2e): don't run tests or deploy while someone is using the app`
  - 於 `e2e.py` 與 `deploy_on_pi.sh` 實裝 15 分鐘內真人使用守衛 (`m_<timestamp>`)，防止測試打斷真人會議錄音。

---

## 2. 接手後立即可執行的閉環工程佇列 (Active Loop Engineering Queue)

### 🌞 A. 白天時段任務佇列 (07:00 – 19:00，禁開喇叭/藍牙收音，專注數位直送與程式碼品質)

1. **[Task D1] 數位直送全尺寸回歸自測 (`run_suite.py` Null-Sink E2E)：**
   - **進度（2026-11-09）：** 快速組 1/3 分鐘 **PASS**（`/home/pi/ln_e2e/reports/d1_quick_20261109_8302fa8/`）；中段組 5/10/15/30 分鐘執行中（`/home/pi/ln_e2e/reports/d1_mid_20261109_8302fa8/`）。
   - **執行位置：** Pi 上沒有 repo clone；harness 在 `/home/pi/ln_e2e/deploy_<commit>/tools/e2e/`（目前為 `deploy_8302fa8`，md5 與本機一致），音檔在 `/home/pi/ln_e2e/data/`。
   - 在確認 `192.168.50.228` (`raspi678`) 閒置後，依序執行：
     - 快速組：`python3 tools/e2e/run_suite.py --minutes 1 3 5`
     - 中長組：`python3 tools/e2e/run_suite.py --minutes 10 15 30`
     - 長會議穩定度組：`python3 tools/e2e/run_suite.py --minutes 45 60`
     - 英文會議組：執行 `en_short` (127s) 與 `en_long` (339s) 數位直送 E2E，確認英文紀要（`Summary / Action Items / Decisions`）之 `recap_recall` 與 `topic_coverage` 穩定超越門檻。
   - **閉環動作：** 檢查每次產出的 `suite.json` 與 `summary.md`；凡發現 `summary_recap_recall < 0.8`、`summary_topic_coverage < 0.7` 或任何格式瑕疵（如標題截斷、待辦負責人誤判、重複列），立即擷取該次實際輸入與輸出，在 `tests/test_summary_utils.py` 新增重現單測並於 `code_dispatcher/summary_utils.py` 修復。

2. **[Task D2 ✅ 已於 `b05108c` 完成] 清理 `summary_utils.py` 的 Python 3.13 正則表達式 `DeprecationWarning`：**
   - **現況：** 執行 `pytest` 時，`code_dispatcher/summary_utils.py`（第 1267、1329、1330、1436、1545、1720 行）共有 145 個 `DeprecationWarning: 'maxsplit' is passed as positional argument`（因 `re.split(pattern, string, 1)` 在 Python 3.13+ 要求改用關鍵字參數 `maxsplit=1`）。
   - **閉環動作：** 將 `re.split(..., ..., 1)` 統一改為 `re.split(..., ..., maxsplit=1)`，跑全套 `pytest` 確認 0 warnings 且全數通過。

3. **[Task D3] 清理工作區未追蹤之歷史臨時探測腳本 (`tools/pi_*_remote.sh`)：**
   - **現況：** `git status -s` 顯示 `tools/` 下有數十個 10/22 藍牙除錯期間留下的未追蹤 `pi_*_remote.sh` 探測腳本。
   - **閉環動作：** 檢視哪些探測腳本仍有診斷價值（可歸檔至 `tools/diagnostics/` 或加入 `.gitignore`），保持 `git status` 乾淨整潔。

---

### 🌙 B. 夜間時段任務佇列 (19:00 – 07:00，實境聲學自測 `speaker_selftest.py`)

1. **[Task N1] 開跑前環境確認與藍牙自動重連開啟：**
   - 呼叫 `POST http://192.168.50.228:8000/api/bt/trusted/auto_connect` 確保測試耳麥 `auto_connect: true`。
   - 確認 PC 播放音效卡切換至靠近耳麥之喇叭，並在開跑前 30 秒檢查即時逐字稿確認非靜音幻覺。

2. **[Task N2] 3 / 10 / 30 分鐘多輪聲學循環自測 (`night10_*` 系列)：**
   - 依序跑 3 分鐘 → 10 分鐘 → 30 分鐘 `speaker_selftest.py`。
   - 針對每一輪錄音產出的逐字稿與紀要，比對 `fixtures/meeting_{3,10,30}min.json` 的 Ground Truth Facts 與 Recap Decisions/Todos：
     - 找出因藍牙 CVSD 8kHz 窄頻或環境殘響產生的新同音錯字（Garbles）。
     - 在 `hailo_whisper/whisper_engine.py` 與 `code_dispatcher/summary_utils.py` 補齊正規化規則，並在 `tests/test_whisper_engine.py` / `tests/test_summary_utils.py` 加上對應單元測試。
     - 每累積 3～5 個已驗證 Commit，透過 Desktop Commander 自動雙推 `gitlab` 與 `origin`，並呼叫 `deploy_on_pi.sh` 部署至 Pi 進入下一輪實測。

---

## 3. 本輪觀察 (2026-11-09 白天，Claude 接手)

- **離線測試基準：** Windows 本機 `pytest`（忽略 3 個 Linux 專屬模組）實測 **498 passed**；文件舊值 513 已依實測更正。
- **Pi 現行版本：** `/home/pi/code_dispatcher` 與 HEAD `8302fa8` 內容一致（僅有 CRLF 差異）。`b05108c` 為語法等價改寫，尚未部署到 Pi，下一批修改一併部署。
- **`/health` 回報 `degraded`：** 原因是 `redis-server` 未執行；`main.py` 的 RQ 佇列為遺留程式碼，錄音主流程不依賴。待確認是否移除或忽略此狀態，不影響功能。
- **3 分鐘快速組殘留 STT 錯誤（數位直送路徑）：** `工安`→`公安`、`供應商星光材料`→`新光材料`、總結段「決議是」→「依是」，以及一段英文幻覺 `to stop the time for 3 hours`。
  - 注意：以測試專屬人名或詞彙加校正表，會對合成 fixture 過度擬合（overfit）。優先找通用修正（例如 ASR 後處理、幻覺偵測），再以單測固定行為。
- **2026-11-09 19:24 夜間觀察：** Pi `/api/status` 為 `done`（無 recording/processing；最後 job `m_1794214462` 為 16:38，已超過 15 分鐘）；`/health` 為 `degraded`（redis 未連線，同 #8）；藍牙耳麥未連線（見 #6）。最新 e2e 報告 `en_c17a4d0_20261109` 仍為 2/2 PASS（en_short CER 0.0349、en_long CER 0.092）。本機 pytest 在 `039e612` 為 502 passed。
- **Pi 忙碌守衛：** 本輪所有 E2E 前都確認 `/api/status` 為 `done`，且無非 e2e 的近期 `m_<timestamp>` 工作。

---

## 4. 待辦清單 (Todo — 定時循環每次審視並更新；狀態以此為準)

**工作鎖 (Lock)：** 無（14:25 定時循環本輪只做唯讀與離線 pytest，未寫入鎖；13:52 互動 session 推送 1e00751 到 gitlab 與 origin，已釋放）；前次：無（13:46 關機 raspi678，已釋放）；前次：無（13:34–13:40 互動 session 部署 1e00751 到 raspi543，已釋放；未 git 寫入、未 push）；前一把（定時循環 60 分 E2E，12:25 開始）已於 13:38 結束：FAIL 1/1，唯一失敗項 swap_growth_mb 75（門檻 ≤64），其餘檢查 PASS；報告 `/home/pi/ln_e2e/deploy_1e00751/e2e_reports/20261110_122534/`；原記載：定時循環，2026-11-10 12:25 開始；範圍：60 分數位 E2E 背景執行，PID 2669349，log `/home/pi/ln_e2e/run_60min_1e00751.log`，報告目錄 `/home/pi/ln_e2e/deploy_1e00751/e2e_reports/`；預計 13:30 前後完成；未 push、未部署；下一輪若程序已結束，讀 `summary.md` 後清除鎖）。前次：無（2026-11-10 11:27–11:33 本輪：本機 commit `1e00751`、部署 `1e00751` 至 raspi678、1 分數位 E2E PASS，已釋放；未 push）。前次：無（2026-11-10 10:48–約 10:58 互動 session 耳麥 1 分鐘聲學測試，已釋放；未 git 寫入、未部署）；09:30 定時循環的 45 分 E2E 已於 10:19 結束，鎖已過期；範圍：45 分數位 E2E（背景執行，報告目錄見 §18、§19）。10:19 已完成（PASS），程序已結束；10:24 本輪唯讀觀察時鎖仍在 60 分鐘有效期內（至 10:30 過期），本輪未做 Pi 測試與 git 寫入。以 `/api/status` 為準，recording／processing 期間不部署、不 push。前次：無（2026-11-10 08:25–08:45 本輪：Pi 3 分數位 E2E ×2、部署 `7606f00` 至 raspi678、git commit `7606f00` 與推送 gitlab／origin，已釋放）。前次：無（2026-11-10 07:27–07:31 本輪 Pi 1 分數位 E2E，已釋放；無 git 寫入、無部署）。前次：無（2026-11-10 06:27–06:33 本輪 commit 456ce73／878995d、部署 raspi678、1 分數位 E2E，已釋放；未 push）。前次：無（2026-11-10 05:25–05:30 本輪 Pi 數位 E2E 完成後已釋放，範圍僅 1 分 E2E，無 git 寫入、無部署；前次 01:45 已釋放；持有期間約 01:30–01:45，寫入 commit、部署、Pi E2E、推送）；04:24 本輪僅唯讀與文件，未寫入鎖

**最後回報：** 2026-11-10 14:25（台北）

> 做 Pi 測試或 git 寫入前，先在上面寫入「持有者 / 開始時間」；超過 60 分鐘視為過期。定時 review 看到有效鎖時，不得另開 Pi 測試或 git 寫入。
> 2026-11-09 18:07 使用者指定：定時循環每次審視待辦與排程；循環（自測 → 找問題 → 修改 → 驗證）不因使用者不在而停。白天只做數位工作（pytest、離線重放、null-sink E2E、修改與文件）；夜間才可做喇叭與耳麥自測。

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 1 | D1 中段組 5/10/15/30 分鐘 E2E | ✅ 完成（16:47） | 4/4 PASS：CER 0.233–0.258、逐字稿事實召回 0.85–0.91、紀要召回 0.83–1.0、議題覆蓋 1.0、STT NPU 100%；報告 `/home/pi/ln_e2e/reports/d1_mid_20261109_8302fa8/`；17:24 定時 review 複核：`summary.md` 4/4 ✅，該目錄無 `.log` 檔（實際為 `e2e_*.json`、`mon_*.jsonl`、`junit.xml`、`suite.json`、`summary.md`） |
| 2 | 16:47 續測檢查點 | ✅ 已執行 | 已讀取 #1 報告並更新本表 |
| 3 | 英文 E2E en_short / en_long | ✅ 完成（16:58） | 2/2 PASS：en_short CER 0.035、紀要召回 1.0；en_long CER 0.092、紀要召回 1.0；報告 `/home/pi/ln_e2e/reports/en_c17a4d0_20261109/`。`run_suite.py --en` 由 commit `c17a4d0` 加入 |
| 4 | 3 分鐘 STT 殘留錯誤的通用修正 | 待辦（可自動執行） | 工安→公安、星光→新光、決議→依是；英文幻覺已由 #17 處理。先寫離線重現單測，再做通則修正；禁止測試專屬人名過擬合。白天或夜間皆可做（pytest＋離線重放，不出聲）。2026-11-10 00:30 再評估：23:30 的 1 分 E2E 逐字稿仍有同音誤認（如「外科呱瓜」「一傭一站」「改報」），尚未找到可泛化的規則（推測），本輪未改程式 |
| 5 | 部署到 raspi678 | 條件式自動 | 只有已 commit、通過 pytest 與離線重放、且會改變 app 行為的變更（例如 #4）才依 `tools/ci/deploy_on_pi.sh` 部署（busy guard；失敗即回滾並記錄）。17:24 的 `b05108c`（語法等價改寫）與 `c17a4d0`（只改測試工具）無行為變更，不部署 |
| 6 | 夜間 speaker_selftest 3/10/30 分鐘 | 🟡 部分完成（2026-11-10 上午，白天 1 分聲學測試，使用者同意） | 耳麥 RichChipAN（`A0:D1:2A:42:12:34`）已連線、auto_connect 開啟、電量 100%。1 分結果：link arrival 96.9%、dropout 0.1%、inserted 0.08 s；CER 0.2669（數位 1 分 0.1864–0.1949，差約 0.07）；事實召回 0.7273（11 項漏 3：T1 招募-職缺數、T2 品質-新不良率、T2 品質-缺陷）。報告 `tools/pi_probe_out/speaker_1min_20261110.json`（gitignored）。3/10/30 分未跑；夜間規則照舊 |
| 7 | D3 未追蹤檔清理 | 等待你決定 | 歸檔到 `tools/diagnostics/`，或加入 `.gitignore`。另 `tools/git_sync.cmd` 有未提交修改（M），用途待確認 |
| 8 | `/health` degraded（redis 未啟動） | 等待你決定 | 遺留 RQ 佇列是否移除 |
| 9 | 定時循環 | 已設定（`trig_01XfezGs…`，每小時 :23 台北） | 18:07 更新提示：每次審視待辦與排程，依時段分流自測，循環不停工 |
| 10 | git 推送 | ✅ 已推送（21:40）：`c17a4d0`、`039e612`、`19fd82b` 同步到 gitlab＋origin | `c17a4d0`（測試工具）待累積到 3–5 個已驗證 commit 再推。17:24 `git status -sb`：`main` ahead 1（僅 `c17a4d0`）；工作樹另有已追蹤檔 `tools/git_sync.cmd` 未提交修改（M），未推送 |
| 11 | LLM 潤稿區（逐字稿 LLM 版＋修同音字／漏字補字／重新潤稿 開關） | 等待你決定 | 預設：修同音字與漏字用修改清單（模型只輸出 `{from, to}`，程式套用）；重新潤稿全文重寫，手動觸發；多選合併成一次 prompt；錄音中回 409。決定後才實作；以 E2E 的 CER 與事實召回驗證，沒有改善就不預設開啟 |
| 12 | `.transcript` 高度不一致 | 等待你決定（09:35 已查） | 結果面板逐字稿 `.transcript` 為 `max-height:360px`（`code_dispatcher/ui.html`、`ui_client.html`、`static/index.html` 第 136 行，三份相同）。`code_dispatcher/*.html` 內無 `165px`、無 `overflow-y`；`165px` 只出現在根目錄 `CLAUDE.md`（122 行）、`AGENTS.md`（71 行）、`.claude/CLAUDE.md`（92 行）、`.agents/rules/project_rules.md`（68 行），描述「即時雙語卡片」，目前 UI 無對應實作（推測：規格過時）。待你決定：改文件（四處一致）或改 UI |
| 13 | 循環自測（找問題） | 持續 | 待辦沒有可自動執行的項目時，依最新 E2E 報告找最差指標（CER、紀要召回、STT 零值比例），新增一列後修改驗證 |
| 14 | 待辦事項截斷切到數字（3 分鐘 e2e「…拿到5」） | ✅ commit `039e612`（18:31）；✅ 已部署 raspi678（20:32，見 §5）| 19:5x 離線重放（`.cc_scratch/replay_todo.py`、`replay_todo2.py`，以 `8302fa8` 的 3 分鐘 e2e JSON 比對舊版 `su_old_8302fa8.py` 與新版）：`transcript_todo_rows` 與 `extract_todos` 兩版輸出相同，**未重現「拿到5」**，重放不足以作為部署依據，故暫不部署；「拿到5」可能來自另一次未留存的 run，需找到真實重現輸入後再重放。原因：`summary_utils` 待辦事項以硬編碼 `[:20]` 截斷，切在「500臺」中間。修正：新增 `_cut_item()`，截點落在數字串中間時退到數字之前，其餘不變；單測 `test_todo_item_cut_never_splits_a_number`。pytest 502 passed、0 failed。未部署；需有真實重現輸入的離線重放通過後，才依 `deploy_on_pi.sh` 部署（busy guard；白天可做，不出聲）。其餘 `[:20]` 調用點（英文 `[:40]`）未改。本輪暫存 `.cc_scratch/` 為未追蹤檔，勿 commit；工具無法刪除，可手動刪除 |


## 5. 本輪更新（2026-11-09 20:30–20:40 定時循環，台北時間）

- **#14 真實重現與部署：** 3 分鐘 digital E2E（`8302fa8`，報告 `/home/pi/ln_e2e/reports/d1_quick_20261109_8302fa8/`，見 `e2e_3min.json`）的待辦列「客戶訂單臺中蓮華精力希望3月17日拿到5」恰為 20 字，切點落在「500」中間。離線重放（`F:\13_prj_raspi5_localnote\.cc_scratch\replay_14_cut.py`，輸出 `replay_14_cut_out.txt`）：舊 `[:20]` → `…拿到5`；新 `_cut_item` → `…拿到`；不含數字的截斷結果不變。本機 pytest（`C:\Python313`，忽略 3 個 Linux 專屬模組）502 passed。
- **部署：** `039e612` 以 `tools/ci/deploy_on_pi.sh` 部署到 raspi678，20:32 OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261109_203222/`；`summary_utils.py` md5 與來源一致。`/health` 仍為 `degraded`（redis，同 #8），部署日誌無 Traceback。
- **部署後 1 分鐘 digital E2E（null-sink）：** PASS，報告 `/home/pi/ln_e2e/deploy_039e612/e2e_reports/20261109_203240/`。CER 0.1737（8302fa8 同長度為 0.1864）；逐字稿事實召回 0.9091（0.8182）；總結事實 1.0；紀要召回 1.0；議題覆蓋 0.5（8302fa8 同長度為 1.0）；STT NPU 12/12。
- **部署方式注意（#16）：** `tools/ci/deploy_on_pi.sh` 在 git HEAD 內為 CRLF，直接 `bash` 執行報 `set: pipefail: invalid option name`，腳本 exit 2，未執行任何步驟，Pi 未變更。本輪改用 LF 副本（由 `git archive` 取 HEAD 內容並去除 CR，`F:\13_prj_raspi5_localnote\.cc_scratch\deploy_on_pi_lf.sh`），上傳到 `/home/pi/ln_e2e/deploy_039e612/tools/ci/` 後 `bash -n` 通過才部署。
- **Pi 狀態：** 20:2x–20:3x 檢查 `/api/status` 為 `done`（最後 job `m_1794214462`，16:38；部署與 E2E 期間無錄音或處理中）；`/api/bt/status` connected=false，`trusted_devices` 仍只有控制器，#6 仍阻塞。
- **git：** `main` 領先 `origin/main` 與 `gitlab/main` 各 2 個 commit（`c17a4d0`、`039e612`），尚未推送（未達 3–5 個門檻）。`tools/git_sync.cmd` 仍為 M，未併入。`.cc_scratch/` 為未追蹤暫存（含 `deploy_039e612.tar`、`e2e_3min_8302fa8.json`、重放腳本），勿 commit。
- **#4 子項判讀（推測，待驗證）：** `工安→公安`、`星光→新光`、`決議是→依是` 較像 STT 同音誤認，通用修正困難，除非能找到可泛化的規則，否則列為已知限制；不以詞表處理。

新增待辦：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 15 | 1 分鐘議題覆蓋 0.5（部署後 E2E） | ✅ 再次結案（2026-11-10 07:28）：06:30 同 commit `456ce73` 為 0.5，07:24 回到 1.0，未連續兩次低於 1.0（見 §16） | 039e612 那次為 0.5；之後 19fd82b（1 分，21:55）、0f26dd5（3 分，22:31）、23ca266（1 分，23:30）的議題覆蓋皆為 1.0。0.5 的原因未查明（推測為 LLM 單次用詞差異）；若再連續 2 次低於 1.0 才重開，檢查 `summary_utils` 的議題擷取 |
| 16 | `deploy_on_pi.sh` 在 git 內為 CRLF | 等待你決定 | 直接 bash 執行會失敗（見 §5）。建議：`.gitattributes` 設 `*.sh text eol=lf`，或將該檔正規化為 LF 後 commit。屬工具變更，本輪未自行修改 repo |
| 17 | 3 分鐘殘留：英文幻覺 `to stop the time for 3 hours` 夾在中文段中 | ✅ 實作並部署（`19fd82b`，21:35）；1 分 E2E PASS，3 分逐字稿已不含該句；誤傷風險見 #18 | 已在 `8302fa8` 的 3 分鐘逐字稿中確認仍保留（`e2e_3min_8302fa8.json` 的 transcript）。下一步：找通用規則（例如中文主體段落內的連續英文小寫詞串），先寫離線單測；不以本句為特例加詞表 |

## 6. 本輪更新（2026-11-09 21:30–21:52 定時循環，台北時間）

- **#17 英文幻覺（已實作、已部署）：** `code_dispatcher/voice_pipeline.py` 新增 `_CJK_ISLAND_EN_RE`：逐字稿含中文時，拿掉夾在中文之間、全小寫、4 詞以上的英文片語（含大寫詞者不動）。單測 `tests/test_stt_segment_clean.py` 新增 4 例（2 例命中、2 例不動），先紅後綠；pytest（Windows，Python 3.13）506 passed。離線重放 `e2e_3min_8302fa8.json`：只命中 1 段（`to stop the time for 3 hours`），其餘輸出不變。
- **commit `19fd82b`**（fix(stt)）：21:35 以 `tools/ci/deploy_on_pi.sh` 部署到 raspi678，OK（備份 `/home/pi/code_dispatcher/.deploy_backup/20261109_213541`），`voice_pipeline.py` md5 與來源一致。部署腳本在 git 內為 CRLF，本輪照 #16 在 Pi 副本以 sed 去除 CR 後執行。
- **部署後 digital E2E（null-sink，不出聲）：** 1 分 PASS（`e2e_reports/20261109_213555`）：CER 0.1864、逐字稿事實 0.8182、總結事實 1.0、議題覆蓋 1.0（#15 的 039e612 為 0.5，本次回到 1.0）。3 分 FAIL（`e2e_reports/20261109_213928`）：CER 0.1582（15:06 的 8302fa8 為 0.2268）、逐字稿事實 0.8529、總結事實 0.8333、議題覆蓋 1.0；唯一失敗項為 `summary_no_placeholder`，見 #19。3 分逐字稿已不含 `to stop the time for 3 hours`。
- **git：** 累積 3 個未推送 commit（`c17a4d0`、`039e612`、`19fd82b`），依序 `git push gitlab main`、`git push origin main`，兩端皆 `b05108c..19fd82b` 成功，本機與 origin 同步。`tools/git_sync.cmd` 仍為 M，未併入；`.cc_scratch/` 為未追蹤暫存，未 commit。
- **Pi 狀態：** 21:31–21:46 `/api/status` 為 `done`；`/health` 仍 `degraded`（redis，同 #8）；`/api/bt/status` connected=false，耳麥未連線，#6 仍阻塞。
- **離線重放腳本（未 commit，位於 `.cc_scratch/`）：** `replay_17_island.py`、`replay_17_ctx.py`。

新增待辦（併入 §4 表，編號接續）：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 18 | #17 規則的誤傷風險 | 等待你決定 | 真人說的全小寫英文 4 詞以上、夾在中文之間，也會被拿掉（推測，未驗證）。等耳麥配對後的夜間真人錄音驗證；若誤傷多，改為只拿掉幻覺特徵較強的片語，或改用 VAD／信心分數判斷 |
| 19 | 3 分 E2E `summary_no_placeholder` 失敗：紀要含 `## 要`，`## 摘要` 只剩補上的「模型輸出長度不足」 | ✅ 已實作並部署（`0f26dd5`，22:31；3 分數位 E2E 22:31 PASS，見 §7）。**08:25 同症狀再現，真因更正為 `summary_raw` 標題含 U+FFFD，已由 `7606f00` 修正（見 #34、§17）** | 本次紀要有 7 條 `## 要` 條目，`## 摘要` 為 ensure_sections 補上的標記。`summary_utils.py` 約 97–102 行的 `## 要`→`## 摘要` 改寫未生效，原因未知（推測：此路徑未經過該改寫，或標題含額外字元）。未確認與 #17 有關（單次 LLM 結果，#17 只改了逐字稿）。下一步：從 `mon_3min.jsonl` 或 `summary_stream` 取原始 LLM 輸出，寫重現單測於 `tests/test_summary_utils.py`，再做通則修正 |

下一輪建議（依時段）：先做 #19 的原始輸出擷取與重現單測（數位工作，白天夜間皆可）；重跑 3 分 digital E2E 一次確認是否穩定；#18 與 #6 等耳麥配對後再處理。

## 7. 本輪更新（2026-11-09 22:30–22:38 定時循環，台北時間）

- **#19 實作（commit `0f26dd5`，fix(summary)）：** `code_dispatcher/summary_utils.py` 的 `to_internal_sections()` 原本只在「完全沒有 `## 摘要` 行」時把「## 要」改成「## 摘要」。模型若先寫一個空的「## 摘要」（只有標題，或只寫「- 無」、「-」），摘要條目就留在「## 要」底下，`ensure_sections()` 再補上「模型輸出長度不足」佔位。修正：新增 `_SUMMARY_ALIAS_HEAD_RE`、`_EMPTY_SUMMARY_RE`，有「## 要」類標題時先拿掉空的「## 摘要」，再改寫；「## 摘要」已有內容時兩者都不動。
- **單測先紅後綠：** `tests/test_summary_utils.py::test_empty_summary_section_does_not_hide_zhao_heading`（3 種空摘要寫法 + 1 個「已有內容不動」斷言）。修改前該測試 FAIL，修改後 PASS。pytest（Windows，Python 3.13，忽略 3 個 Linux 專屬模組）507 passed、0 failed。
- **離線重放的限制（誠實說明）：** 21:39 那次 3 分 E2E 的 LLM 原始輸出沒有留存，只有經後處理的 `summary_stream`（已含佔位）。因此本次重現是用合成輸入（`.cc_scratch/repro_19.py`，6 種寫法），不是真實原始輸出。「模型先寫空的『## 摘要』」是否就是 21:39 的真實觸發條件，仍是推測，未經證實。
- **部署：** 22:31 以 `deploy_on_pi.sh`（LF 副本，tar 來自 `git archive HEAD`）部署到 raspi678，OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261109_223123`；`summary_utils.py` md5 與來源一致（`d5e22f9a…`）。`/health` 仍為 `degraded`（redis，同 #8）。
- **部署後 3 分數位 E2E（null-sink，不出聲）：** PASS，報告 `/home/pi/ln_e2e/deploy_0f26dd5/e2e_reports/20261109_223139/`，failed cases 0/1。CER 0.1909（21:39 同長度 0.1582 FAIL；8302fa8 0.2268）、逐字稿事實 0.8235、總結事實 0.8333（逐字稿內 1.0）、議題覆蓋 1.0、STT NPU 27/27。原先失敗的 `summary_no_placeholder` 本次通過。
- **Pi 狀態：** 22:26–22:36 `/api/status` 為 `done`，錄音（22:31 起）為本輪 E2E 自己開的工作；`/api/bt/status` connected=false，`trusted_devices` 只有控制器，#6 仍阻塞（夜間條件已成立，但耳麥未連線，未執行 `auto_connect`）。
- **git：** `main` 領先 `origin/main` 與 `gitlab/main` 各 1 個 commit（`0f26dd5`）；未達 3–5 個門檻，未推送。`tools/git_sync.cmd` 仍為 M，未併入。`.cc_scratch/` 為未追蹤暫存，未 commit。
- **本輪受限事項：** 遠端工具 `device_bash` 回報「無連接資料夾」，依規定未請求資料夾授權，改以 Desktop Commander 讀寫 `F:\`。

新增待辦（併入 §4 表，編號接續）：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 20 | 桌面 app 未連接 `F:\13_prj_raspi5_localnote` 資料夾 | 等待你決定 | 本輪 `device_bash` 無法使用，依規定不請求資料夾授權，改用 Desktop Commander（讀檔、pytest、git、scp 皆正常）。若要 `device_bash` 的 `$HOME/mnt` 路徑可用，請在 app 內「Add folder」連接該資料夾 |
| 21 | E2E 報告未留存 LLM 原始輸出 | ✅ 完成（23:33，`23ca266`） | #19 因此只能用合成輸入重現。已實作：`JobStatus.summary_raw` 存 LLM 原文（後處理前），`e2e.py` 寫入 `e2e_<label>.json`；1 分 E2E PASS（見 §8）。分段路徑未覆蓋，見 #25 |
| 22 | `0f26dd5`、`23ca266`、`6ba0509` 推送 | ✅ 已推送（01:43）：三個 commit 同步到 gitlab＋origin（兩端 main = `6ba0509`） | 見 §10。GIT_TERMINAL_PROMPT=0、GCM_INTERACTIVE=never；推送時 PowerShell 會把 stderr 顯示為錯誤，exit code 0 即成功 |
| 23 | 根目錄 `CLAUDE.md`、`.claude/settings.json` 為未追蹤檔 | 等待你決定 | 本輪 `git status` 首次看到，未併入 commit。確認要納入版本控制或加入 `.gitignore` |
| 26 | 1 分 E2E 漏「T2品質-缺陷」：「外科呱瓜」「一傭一站」 | 已知限制（ASR） | 推測為聲學誤認，無可泛化文字規則；同音音檔重跑 1 分逐字稿事實 0.9091→0.8182，ASR 有波動。待 #11 或夜間真人錄音再評估（§10）。2026-11-10 05:25 同 commit `6ba0509` 重跑 1 分：CER 仍為 0.1864，逐字稿事實回到 0.9091（報告 `d1_1min_0511`）；同 commit 下 CER 相同而逐字稿事實不同，顯示此指標有波動（推測為 chunk 時序或 NPU 差異，未查證） |
| 27 | 3 分決議段殘留「待辦事項是王金，主持面試」 | ✅ commit `6ba0509`（01:2x），部署 01:34，E2E 2/2 PASS | 原因：負責人 STT 聽錯為「王金」，`_clause_in_table` 認不出；修正為以事項文字比對拿掉子句。單測 1 條，pytest 510 passed（§10） |


## 8. 本輪更新（2026-11-09 23:27–23:33 定時循環，台北時間）

- **#21 完成（commit `23ca266`，feat(summary)）：** `code_dispatcher/meeting_minutes.py` 的 `JobStatus` 新增 `summary_raw`（LLM 原文，後處理前）；`_generate_summary_llm` 在串流結束、後處理前寫入。畫面用的 `summary_stream`、後處理與紀要內容不變。`tools/e2e/e2e.py` 把 `summary_raw` 寫進 `e2e_<label>.json`。單測 `tests/test_summary_raw.py`（2 例：預設 None；串流原文等於 raw，且後處理結果不同）。本機 pytest（Python 3.13，忽略 3 個 Linux 專屬模組）509 passed（原 507 + 新 2）。
- **部署：** 23:29 以 `deploy_on_pi.sh` 部署到 raspi678，OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261109_232917`；`meeting_minutes.py` md5（`2b35af1e…`）與來源一致。`/health` 仍 `degraded`（redis，同 #8）。部署腳本改用本機位元組過濾 CR 後上傳；先前在遠端以未加引號的 `sed -i s/\r$//` 處理，`\r` 被 shell 吃掉，把 Pi 上的暫存副本弄壞（未影響線上程式，改上傳後 `bash -n` 通過）。
- **1 分數位 E2E（null-sink，不出聲）：** PASS，報告 `/home/pi/ln_e2e/deploy_23ca266/e2e_reports/20261109_233050/`。CER 0.1864、逐字稿事實召回 0.9091、總結召回 1.0、議題覆蓋 1.0、STT NPU 12/12；`summary_raw` 有值（234 字）。#15 的 1 分議題覆蓋本次回到 1.0，仍列為觀察中。
- **Pi 狀態：** 23:2x–23:3x `/api/status` 為 `done`（最後 job `m_1794234703`，約 22:15，已超過 15 分鐘）；`/api/bt/status` connected=false，`trusted_devices` 只有控制器，#6 仍阻塞（夜間條件已成立，耳麥仍未連線，未執行 `auto_connect`）。
- **git：** `main` 領先 `origin/main` 與 `gitlab/main` 各 2 個 commit（`0f26dd5`、`23ca266`），未達 3–5 個門檻，未推送。`tools/git_sync.cmd` 仍為 M，未併入。`.cc_scratch/` 為未追蹤暫存（含 `deploy_23ca266.tar`、`deploy_on_pi_lf.sh`、`d21_1min/`），未 commit。
- **裝置連線：** `device_bash` 本輪仍無連接資料夾（#20），依規定未請求授權，讀寫經 Desktop Commander。

新增待辦（併入 §4 表，編號接續）：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 24 | 1 分 E2E `summary.md` 的「raspi678 commit」欄為 `-` | 等待你決定（04:24 分析後由「可自動執行」改為待決定） | 部署目錄沒有 `.git`。`tools/e2e/run_suite.py` 的 `meta.commit` 只讀環境變數 `CI_COMMIT_SHORT_SHA` / `GITHUB_SHA`，所以 Pi 上 `deploy_<sha>/` 的報告一律為 `-`。原備註「由 `deploy_on_pi.sh` 寫入 `VERSION`」不成立：該腳本部署的是 `/home/pi/code_dispatcher`，不是 E2E 目錄。可行選項：(A) 上傳 `deploy_<sha>/` 時寫入 `VERSION`，harness 讀 `HERE/../../VERSION` 作為後備；(B) harness 從目錄名解析 sha。請選擇後再實作（會改 harness 契約，需單測與 commit） |
| 25 | 分段路徑（逐字稿超過 single_max）的 `summary_raw` 為 null | 等待你決定 | 長會議 E2E 此欄為 null。若要覆蓋，需在 `_hierarchical_summary_body` 各段累積原文；是否值得改分段路徑，請你決定 |

下一輪建議（依時段）：夜間 #6 仍等耳麥配對與 MAC；白天可做 #4（離線重現單測）與 #24；#22 累積到 3 個 commit 再推。

## 9. 本輪更新（2026-11-10 00:24–00:40 定時循環，台北時間）

- **唯讀觀察：** Pi `/health` 為 `degraded`（`redis_connected=false`，同 #8；`ollama_running=true`，`queue_length=0`）。`/api/status` 為 `done`（最後 job `m_1794238254` 為 23:30 的 1 分 E2E 錄音，已結束）。`/api/bt/status` 為 `connected=false`；`trusted_devices` 只有控制器 `RichChipBOBO`（`auto_connect=true`）；pipewire 只有 `Dummy Output`。#6 仍阻塞。
- **git（本機唯讀）：** `main` 領先 `origin/main` 與 `gitlab/main` 各 2 個 commit（`0f26dd5`、`23ca266`），未達 3–5 個門檻，未推送。`tools/git_sync.cmd` 仍為 M，未併入。`.git` 下無 `*.lock`。
- **工作鎖：** 無。本輪只做唯讀觀察與 scp 讀取報告，未跑 Pi 測試、未做 git 寫入，故未寫入鎖。
- **最新 E2E（23:30，`deploy_23ca266`，`20261109_233050`）：** 1 分 PASS。CER 0.1864（ref 236 字、hyp 217 字）；逐字稿事實 0.9091（10/11）；總結事實 1.0；議題覆蓋 1.0；紀要召回 1.0；errors 0；llm_fallbacks 0；hailo_busy_errors 0；STT NPU 12/12。缺漏的那一項在本機讀取時編碼失真，未能確認內容。
- **#15 結案：** 039e612 那次議題覆蓋 0.5 視為單次波動；之後 19fd82b（1 分，21:55）、0f26dd5（3 分，22:31）、23ca266（1 分，23:30）皆為 1.0。
- **本輪未做：** 未改程式、未跑 pytest、未部署、未跑 E2E。原因：#6 缺耳麥 MAC 與連線；#4 的同音誤認尚無可泛化規則（推測），依規定不以詞表處理；#22 未達推送門檻。
- **回報：** 本輪無新進度，距上次回報（23:34）未滿 4 小時，依規定不回報，「最後回報」維持 23:34。

下一輪建議（依時段）：夜間若耳麥已配對且取得 MAC，才跑 #6；否則維持阻塞。白天或夜間可做 #4：從 23:30 的 `summary_raw` 與逐字稿寫離線重放，先找可泛化的規則再動手。#22 等累積到 3 個 commit 再推。#16、#18、#20、#23、#25 仍等你決定。

## 10. 本輪更新（2026-11-10 01:20–01:45 定時循環，台北時間）

- **唯讀觀察：** Pi `/api/status` 為 `done`（最後 job `m_1794238254`，23:30 的 1 分 E2E，已結束）；`/health` 仍 `degraded`（redis，同 #8）；`/api/bt/status` connected=false，`trusted_devices` 只有控制器（同 #6）。本機 git：`main` 領先 `origin/main` 與 `gitlab/main` 各 2 個 commit（`0f26dd5`、`23ca266`），`tools/git_sync.cmd` 仍為 M，`.git` 無 lock。
- **#26（新，已知限制）：1 分 E2E 漏掉「T2品質-缺陷」的原因：** 23:30 逐字稿的「外科呱瓜」「一傭一站」是 ASR 聲學誤認（推測，未經聲學驗證），沒有可泛化的文字規則，依 #4 不以詞表處理。同一段音檔在 01:34 重跑時，1 分逐字稿事實降為 0.8182（23:30 為 0.9091），顯示 ASR 本身有波動。待 #11 或夜間真人錄音再評估。
- **#27（新，已修，commit `6ba0509`）：3 分鐘決議段殘留「待辦事項是…」子句：** 22:31 的 3 分 E2E（`e2e_3min_0f26dd5.json`）決議段有「招募方面，決議是12月3日前完成報到待辦事項是王金，主持面試」。這句由 `merge_recap_into_minutes` 的結尾總結路徑加入（不是 LLM 原文）。待辦子句的負責人「王金」是 STT 把「王經理」聽錯，認不出職稱，`_clause_in_table` 以負責人比對，於是整句保留。
- **修改：** `summary_utils._drop_listed_todo_clause` 新增 `_drop_todo_clause_listed_by_text`：待辦子句文字（去標點）與待辦表某列事項互相包含（各至少 3 字）時，只拿掉該子句，前後的決議保留；表上沒有的子句照舊。單測 `test_decision_clause_dropped_when_table_has_the_same_item_despite_garbled_owner`。本機 pytest（Python 3.13，忽略 3 個 Linux 專屬模組）510 passed，先前 509。
- **撤回的嘗試（未進 commit）：** 曾在 `clean_summary_markdown`（LLM 原文後處理）加同類規則，離線重放證明它碰不到這句（來源是結尾總結路徑），已撤回。
- **離線重放（`.cc_scratch/replay_19c.py`）：** 3 分 e2e 決議段：「…完成報到待辦事項是王金，主持面試」→「…完成報到」；1 分 e2e 決議段不變。
- **部署：** 01:34:20 以 `deploy_on_pi.sh`（LF 副本，來源 `git archive 6ba0509`）部署到 raspi678，OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261110_013420`；`summary_utils.py` md5 `163e97a7…` 與來源一致。`/health` 仍 `degraded`（同 #8）。
- **digital E2E（null-sink，不出聲）：** 報告 `/home/pi/ln_e2e/deploy_6ba0509/e2e_reports/20261110_013434/`，**2/2 PASS**（failed 0/2）。1 分：CER 0.1864、逐字稿事實 0.8182、總結事實 1.0、議題覆蓋 1.0。3 分：CER 0.2007、逐字稿事實 0.8529、總結事實 0.8333、議題覆蓋 1.0、STT NPU 27/27。3 分決議段已不含「待辦事項是」子句。
- **git：** `0f26dd5`、`23ca266`、`6ba0509` 依序推送 gitlab 與 origin，兩端 main = `6ba0509`（#22 ✅）。`tools/git_sync.cmd` 與 `.cc_scratch/` 未併入。
- **#6 仍阻塞：** 耳麥未連線、MAC 仍未提供；夜間條件成立，未執行 `auto_connect`。
- **工具注意：** (a) `device_bash` 仍無連接資料夾（#20），本輪讀寫與 SSH 皆經 Desktop Commander。(b) PowerShell 的 `>` 與 `Out-File` 會把 Python 輸出寫成亂碼，改在 Python 內用 `open(..., encoding="utf-8")` 寫檔再讀。(c) 遠端指令內含雙引號時，PowerShell 端曾卡住（PID 30056，已強制終止）；之後改為 scp 一個 `.sh` 到 Pi 再 `bash` 執行。

下一輪建議（依時段）：夜間 #6 仍等耳麥 MAC；白天可做 #24（`VERSION` 檔，可自動執行，低優先）。#26 為 ASR 限制，文字規則不可解。目前沒有未推送的 commit，下次累積到 3 個新 commit 再推。

## 11. 本輪更新（2026-11-10 02:20–02:40 定時循環，台北時間）

- **唯讀觀察：** Pi `/api/status` 為 `done`（最後 job `m_1794245843`，約 01:37 的 3 分 E2E，已結束超過 15 分鐘）；`/health` 仍 `degraded`（redis，同 #8）；`/api/bt/status` connected=false，`trusted_devices` 只有控制器 `RichChipBOBO`。#6 仍阻塞：夜間條件成立，但耳麥未配對、MAC 未提供，未執行 `auto_connect`。
- **git（本機唯讀）：** `main` = `origin/main` = `gitlab/main` = `6ba0509`，無未推送 commit。`tools/git_sync.cmd` 仍為 M；`.cc_scratch/` 與多個未追蹤檔未併入；`.git` 無 `*.lock`。
- **最新 E2E（01:34，`deploy_6ba0509/e2e_reports/20261110_013434/summary.md`）：** 2/2 PASS。1 分：CER 0.1864、逐字稿事實 0.8182、總結事實 1.0、議題覆蓋 1.0。3 分：CER 0.2007、逐字稿事實 0.8529（缺 T2停機時數、T3警示燈、T3複訓期限、T5客戶、T6回歸輪數）、紀要召回 0.8333（缺 `T1供應商-負責人`）、議題覆蓋 1.0。
- **#13 最差指標（3 分 CER／紀要召回）歸因**（讀 `e2e_3min.json` 與 `tools/e2e/fixtures/meeting_3min.json`；標「推測」者未經重跑驗證）：
  - 紀要缺的唯一 ground-truth 項目是「供應商負責人＝李協理」。逐字稿中，正文把「請李協理」聽成「情立佔」，結尾總結把「待辦事項是李協理」聽成「卶」，人名已不在 ASR 輸出中。
  - 最終待辦表寫「新光材料交貨週五回報｜王經理」。LLM 可能是借用逐字稿中其他段落的「王經理」（T5、T7）來補負責人，屬錯誤指派（推測）。
  - 結尾總結「決議是替代料持續驗證」被聽成「依是待了持續驗證」。`summary_raw` 的決議段只剩 3 條，供應商與預算兩條決議因而缺漏（推測）。
  - 結論：主要失分來自 ASR 對人名與「決議是」的同音誤認，與 #4、#26 同類，屬 ASR 限制。依 CLAUDE.md 不以詞表處理。
- **摘要點數上限（觀察，未改程式）：** `meeting_minutes.py` 兩處呼叫 `clean_summary_markdown` 都使用預設上限（摘要 5、決議 3）。3 分的 LLM 原文 `summary_raw` 有 7 條摘要，第 7 條「招募業務部…」被截掉。最終紀要的第 6 條「工業閘道器的韌體更新…」不在 LLM 前 5 條之內，文字也與原文不同，來源未查明（推測：其他補充路徑加入）。主題覆蓋仍為 1.0，因為「招募」在待辦表中仍有列。
- **本輪未做的事（原因）：** 未改程式、未跑 pytest、未部署、未跑 Pi E2E，也未寫工作鎖（沒有 Pi 測試或 git 寫入）。#4 的三個同音誤認仍無可泛化規則（沿用上輪判斷）。#24 屬部署腳本（CRLF），需另行測試，維持低優先。
- **回報：** 本輪沒有可回報的新進度（無 commit、push、部署、E2E 或 Pi 狀態變化），依規定不發通知。「最後回報」維持 2026-11-10 01:45。

新增待辦（編號接續）：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 28 | 3 分 E2E 紀要缺「供應商負責人（李協理）」與兩條決議（供應商、預算） | 已知限制（ASR） | 人名與「決議是」在逐字稿中被聽錯（見 §11）。待辦負責人「王經理」為 LLM 指派錯誤（推測）。若要改善，可考慮通則「負責人需出現在該議題的逐字稿片段中，否則留空」，但會影響真實會議的推論，需多次重跑與真人錄音驗證後再決定。等待你決定是否實作 |
| 29 | 摘要點數上限 5 截掉第 7 條議題；第 6 條來源未明 | 等待你決定（來源已釐清，見 §12） | 第 6 條來源已確認為 `fill_missing_topics` 補上的逐字稿原句（設計行為，非 bug）。上限是 `clean_summary_markdown` 的預設（摘要 5、決議 3）。待你決定：調高摘要上限（會加長紀要，並改變 fill 的觸發），或維持現況。未改程式 |

下一輪建議（依時段）：#29 的來源追查可離線進行；#6 仍等耳麥配對與 MAC；#24 低優先；#22 累積到 3 個新 commit 再推（目前沒有未推送 commit）。

## 12. 本輪更新（2026-11-10 03:23–03:40 定時循環，台北時間）

- **唯讀觀察：** Pi `/health` 為 `degraded`（redis，同 #8）；`/api/status` 為 `done`（最後 job `m_1794245843`，即 01:34 的 3 分 E2E，已結束）；`/api/bt/status` connected=false，`trusted_devices` 只有控制器 `RichChipBOBO`。#6 仍阻塞：夜間條件成立，但耳麥未配對、MAC 未提供，未執行 `auto_connect`。Pi 時間 03:24，與台北時間一致。
- **git（本機唯讀）：** `main` = `origin/main` = `gitlab/main` = `6ba0509`，無未推送 commit，`.git` 無 `*.lock`。`tools/git_sync.cmd` 仍為 M，未併入。未追蹤檔仍有 `.cc_scratch/`、根目錄 `CLAUDE.md`、`claude_context/`、`.claude/settings.json`、`LogoFiles/`、`_ui_screenshots/` 與數十個 `tools/pi_*_remote.sh`（#7、#23）。
- **工作鎖：** 無。本輪只做唯讀查程式與寫文件，未做 Pi 測試或 git 寫入。
- **#29 來源已確認（設計行為，非 bug）：** 01:34 的 3 分 E2E（job `m_1794245843`）`summary_raw` 摘要有 7 條；`clean_summary_markdown` 依預設上限 5 截掉第 6、7 條（`summary_utils.py` 約 206 行起，`count > lim` 規則）。之後 `fill_missing_topics`（約 1908 行）在逐字稿「第N個議題」段落中找未寫到的議題，補上「工業閘道器」的開頭原句，接在摘要最後，所以第 6 條是逐字稿原句（約 28–46 字），不是 LLM 潤稿。第 7 條「招募業務部」的議題已在待辦表（招募業務部面試｜王經理｜下週）出現，`_topic_said` 判定已寫到，故不補。`summary_stream` 的 6 條與此一致。
- **待你決定（新增於 #29）：** 摘要上限 5 是既有設計（註解「限制摘要/決議點數」）。調高到 6–7 可讓 LLM 原句取代逐字稿原句，但會加長紀要，並改變 fill 的觸發條件。未改程式，等你決定。
- **本輪未做：** 未改程式、未跑 pytest、未部署、未跑 E2E（無新 commit，夜間 #6 缺耳麥）。#4、#26、#28 仍是 ASR 限制，沒有可泛化的文字規則。#24 低優先，且觸及 CRLF 部署腳本（#16），本輪不動。
- **回報：** 本輪沒有 commit、push、部署、E2E 或 Pi 狀態變化，依規定不回報；「最後回報」維持 2026-11-10 01:45。

下一輪建議（依時段）：夜間仍等耳麥配對與 MAC（#6）；#24 可於白天處理（先處理 #16 的 CRLF，或以 LF 副本部署）；#29 等你決定；累積到 3 個新 commit 再推。

## 13. 本輪更新（2026-11-10 04:23–04:35 定時循環，台北時間）

- **唯讀觀察：** Pi `/api/status` 為 `done`（最後 job `m_1794245843`，即 01:34 的 3 分 E2E，已結束）；`/health` 仍 `degraded`（redis，同 #8）；`/api/bt/status` 為 connected=false，`trusted_devices` 只有控制器 `RichChipBOBO`（同 #6）。Pi 時間 04:24，與台北時間一致。最新 E2E 報告仍為 `deploy_6ba0509/e2e_reports/20261110_013434`，本輪沒有新的 E2E。
- **git（本機唯讀）：** `main` = `origin/main` = `gitlab/main` = `6ba0509`，無未推送 commit，`.git` 無 `*.lock`。`tools/git_sync.cmd` 仍為 M，未併入；未追蹤檔與 §12 相同（`.cc_scratch/`、根目錄 `CLAUDE.md`、`claude_context/`、`tools/pi_*_remote.sh` 等，#7、#23）。
- **#24 分析（未改程式）：** 見 §4 表中 #24 的備註。harness 取 commit 的來源只有環境變數，E2E 目錄 `deploy_<sha>/` 沒有 `.git`，且 `deploy_on_pi.sh` 不寫入 E2E 目錄。需你選擇 (A) 或 (B) 才實作。
- **#6 仍阻塞：** 夜間條件成立，但耳麥未連線、MAC 仍未提供，未執行 `auto_connect`。
- **工作鎖：** 無。本輪只做唯讀觀察與文件更新，未做 Pi 測試或 git 寫入。
- **執行限制：** `device_bash` 仍無連接資料夾（#20），依規定未請求授權，讀寫與 SSH 經 Desktop Commander。
- **回報：** 本輪沒有 commit、push、部署、E2E 或 Pi 狀態變化；距上次回報（01:45）未滿 4 小時，依規定不回報。若到 05:45 仍無新進度，屆時回報一次。

下一輪建議（依時段）：夜間 #6 仍等耳麥配對與 MAC；#24 等你選擇 (A) 或 (B)；#4、#26、#28 為 ASR 限制，無可泛化規則（沿用前幾輪判斷）；目前無未推送 commit，累積到 3 個新 commit 再推。

## 14. 本輪更新（2026-11-10 05:23–05:30 定時循環，台北時間）

- **唯讀觀察：** Pi `/api/status` 為 `done`（最後 job `m_1794245843`，01:34 的 3 分 E2E，已結束）；`/health` 仍 `degraded`（redis，同 #8）；`/api/bt/status` 為 connected=false，`trusted_devices` 只有控制器 `RichChipBOBO`。#6 仍阻塞：夜間條件成立，但耳麥未配對、MAC 未提供，未執行 `auto_connect`。git：`main` = `origin/main` = `gitlab/main` = `6ba0509`，無未推送 commit，`.git` 無 lock。
- **工作鎖：** 05:25 起持有，僅做 Pi 數位 E2E，05:30 前釋放；無 git 寫入、無部署。
- **數位 1 分 E2E（null-sink，不出聲，`deploy_6ba0509`，報告 `/home/pi/ln_e2e/deploy_6ba0509/e2e_reports/d1_1min_0511/`）：** PASS（failed 0/1）。CER 0.1864、逐字稿事實 0.9091（01:34 同 commit 為 0.8182）、總結事實 1.0、議題覆蓋 1.0、紀要召回 1.0；STT NPU 12/12；summary 延遲 105.87 s；最高溫 50.7 °C；RAM 峰值 2713 MB。
- **判讀：** 同 commit 下 CER 完全相同，逐字稿事實卻從 0.8182 變為 0.9091，顯示該指標本身有波動（推測為 chunk 時序或 NPU 差異，未查證），併入 #26。目前沒有新的 ASR 殘留需要處理。
- **本輪未做：** 未改程式、未跑 pytest、未部署。無可自動執行且有通則規則的修改項目（#4、#28 仍為 ASR 限制），依 §4 規則不為了修改而修改。
- **回報：** 本輪 E2E 完成且距上次回報（01:45）已超過 15 分鐘，依回報判斷規則發送一則簡短回報；「最後回報」更新為 2026-11-10 05:30（台北）。

下一輪建議（依時段）：夜間 #6 仍等耳麥配對與 MAC；白天若要繼續自測，可再跑 3 分 digital E2E 補足 #26 的波動樣本；#24、#16、#18、#20、#23、#25、#28、#29 等你決定；目前無未推送 commit，累積到 3 個新 commit 再推。

## 15. 本輪更新（2026-11-10 06:24–06:33 定時循環，台北時間）

- **唯讀觀察：** Pi `/api/status` 為 `done`，最後 job `m_1794259475` 為 05:24 的 1 分 E2E（在 OWN_JOBS 內，非真人錄音）；`/health` 為 `degraded`（redis，同 #8）；`/api/bt/status` 為 connected=false，`trusted_devices` 只有控制器（#6 仍阻塞）。開始時 `main` = `origin/main` = `gitlab/main` = `6ba0509`，無 `.git/*.lock`。
- **#30 完成（commit `456ce73`，fix(summary)）：** 05:24 的 1 分 E2E 原文（`summary_raw`）中，小模型重複「- 產線加一傭一站查」直到 num_predict 用盡，最後一行被截成「- 產線加一」，殘留在最終紀要決議段。`code_dispatcher/summary_utils.py` 新增 `_drop_cut_off_final_bullet`：只看最後一行，若它（≥3 字）是其他條目的嚴格前綴就拿掉，中間行不動。單測 `test_final_bullet_cut_off_by_token_limit_is_dropped` 先紅後綠；本機 pytest（Python 3.13，忽略 3 個 Linux 專屬模組）511 passed、0 failed。
- **離線重放（真實 `summary_raw`，`.cc_scratch/replay_30_cutoff.py`，輸出 `replay_30_out.txt`）：** 舊版與新版只差一行，決議段「- 產線加一」消失，其餘逐行相同。
- **commit `878995d`（test）：** 只修正測試註解中的 E2E 時間（06:23 → 05:24），無行為變更。
- **部署（#5）：** 06:30:19 以 `deploy_on_pi.sh` 部署 `456ce73` 程式到 raspi678，OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261110_063019`。Pi 上 `summary_utils.py` md5 `07a1cf87…` 與 HEAD blob 一致。`git archive` 在本機 autocrlf 下會產生 CRLF，本輪先以 `sed` 把 Pi 上的 `*.py`/`*.html`/`*.sh` 統一為 LF 才部署（與 #16 相關）。
- **數位 1 分 E2E（null-sink，`deploy_456ce73/e2e_reports/20261110_063044/`）：** PASS（failed 0/1）。CER 0.1737、逐字稿事實 0.9091、紀要召回 1.0、**議題覆蓋 0.5**、重複行 0、errors 0、llm_fallbacks 0、STT NPU 12/12。本次 LLM 原文沒有被截斷，所以新規則沒有在線上實際觸發（離線重放已驗證）。
- **#15 議題覆蓋 0.5 再次出現：** 這是第 2 次低於 1.0（前一次為 039e612），中間隔了 4 次 1.0。#15 的規則是「連續 2 次低於 1.0 才重開」，目前尚不算連續；下一次 1 分 E2E 若仍 <1.0，即重開並檢查 `summary_utils` 的議題擷取。
- **git：** `main` 領先 `origin/main` 與 `gitlab/main` 各 2 個 commit（`456ce73`、`878995d`），未達 3–5 個門檻，未推送。`tools/git_sync.cmd` 仍為 M，未併入；`.cc_scratch/` 為未追蹤暫存，未 commit。
- **工作鎖：** 06:27 持有，06:33 釋放（範圍：commit、部署、1 分 E2E）。
- **回報：** 本輪有 commit、部署、E2E 三項新進度，且距上次回報（05:30）已超過 15 分鐘，已發送一則回報；「最後回報」更新為 2026-11-10 06:33（台北）。

新增待辦：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 30 | LLM 重複迴圈撞上 num_predict 後，最後一行截斷殘留（「- 產線加一」） | ✅ commit `456ce73`，部署 06:30 OK，1 分 E2E PASS | 離線重放（真實 summary_raw）只移除該行。線上 E2E 本次未觸發，屬正常；之後若再出現截斷殘句，檢查 `_drop_cut_off_final_bullet` 的觸發條件 |
| 31 | 同一音檔的 LLM 決議段，三條都帶同一段負責人與期限（「，黃專員2月15日前提出改報」） | 觀察（不實作） | 06:30 的 1 分 E2E 出現，與 05:24 的重複迴圈型態不同。尚無可泛化的規則（推測是 LLM 複製待辦子句）。若再出現，再評估「決議條目不得整段複製待辦表的負責人與期限」這類通則，先寫重現單測 |

下一輪建議（依時段）：07:23 為白天，可做數位工作。#15：下一次 1 分 E2E 若議題覆蓋 <1.0 即重開（連續 2 次）。#31：觀察。目前 2 個未推送 commit，累積到 3 個再推。#6 仍等耳麥配對與 MAC（夜間）。#4、#26、#28 為 ASR 限制，無可泛化規則。#16、#20、#23、#24、#25、#29 等你決定。

## 16. 本輪更新（2026-11-10 07:23–07:31 定時循環，台北時間）

- **唯讀觀察：** Pi `/api/status` 為 `done`（最後 job `m_1794263448`，約 06:30 的 1 分 E2E，已結束）；`/health` 仍 `degraded`（redis，同 #8）；`/api/bt/status` connected=false，`trusted_devices` 只有控制器（#6 仍阻塞）。git：`main` 領先 `origin/main` 與 `gitlab/main` 各 2 個 commit（`456ce73`、`878995d`），`.git` 無 lock，未達 3–5 個推送門檻。
- **數位 1 分 E2E（null-sink，不出聲，`deploy_456ce73`，報告 `/home/pi/ln_e2e/deploy_456ce73/e2e_reports/20261110_072454/`）：** PASS（failed 0/1）。CER 0.1949、逐字稿事實 0.8182、總結事實 1.0、議題覆蓋 1.0、紀要召回 1.0、STT NPU 13/13、summary 延遲 60.22 s、最高溫 51.2 °C、RAM 峰值 2729 MB。
- **#15 判讀：** 06:30 同 commit 為 0.5，本次回到 1.0。未連續兩次低於 1.0，依規則不重開，結案（見 §4 表 #15）。
- **#26 補充：** 同一 commit `456ce73` 下，1 分逐字稿事實為 0.9091（06:30）與 0.8182（07:24），CER 為 0.1737 與 0.1949。同 commit 指標浮動，屬 ASR 或 NPU 波動（推測），非程式行為變化。07:24 缺漏的兩個事實未查明。
- **未做的事（原因）：** 目前沒有可自動執行、且有通則規則的待辦（#4、#26、#28 為 ASR 限制；#16、#24 等你決定）。依步驟 5 找最差指標：近期 1 分逐字稿事實 0.8182 為最低，缺漏事實需對照 fixture 與逐字稿才能定位，列為 #32 的下一步。未改程式、未跑 pytest、未部署。
- **本輪工作鎖：** 07:27–07:31 持有，僅 Pi 1 分數位 E2E，已釋放。無 git 寫入、無部署。
- **工作區新未追蹤檔：** 根目錄 `_commit_opencard.txt`、`_commit_status.txt`、`_loop_count.py`、`_patch_opencard.py`、`_patch_status.py`；`tools/net_probe.cmd`、`tools/pi_pull.cmd`；`LocalNote 聽記盒 規格與功能.md` 與 `.pdf`。用途未知，本輪未開啟內容，未併入 commit（列為 #33）。
- **回報：** 本輪有 E2E 完成（新進度），且距上次回報（06:33）已超過 15 分鐘，依規定回報一次；「最後回報」更新為 2026-11-10 07:31（台北）。

新增待辦：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 32 | 1 分逐字稿事實召回 0.8182（07:24，同 commit 06:30 為 0.9091）；3 分 0.8529（01:34）為近期較低者 | ✅ 分析完成（2026-11-10 08:2x）：無可泛化規則，列為 ASR 限制（同 #26），未改程式。證據：07:24 1 分 E2E 的 `facts_missing` 為 `T2品質-原不良率`（逐字稿「百分之四」→「4-1%」）與 `T2品質-缺陷`（「外殼刮傷」→「外科誒」）；其餘 9 項皆命中。原下一步：以 `e2e_1min.json` 的逐字稿對照 `tools/e2e/fixtures/meeting_1min.json`，列出缺漏事實與 ASR 錯誤型態；若有通則規則，先寫離線重現單測再改。禁止以測試專屬詞彙加校正表 |
| 33 | 工作區新未追蹤檔（根目錄 `_commit_opencard.txt`、`_commit_status.txt`、`_loop_count.py`、`_patch_opencard.py`、`_patch_status.py`；`tools/net_probe.cmd`、`tools/pi_pull.cmd`；`LocalNote 聽記盒 規格與功能.md/.pdf`） | 等待你決定 | 用途未知。請確認要納入版本控制、加入 `.gitignore`，或保留為本機檔案。未併入 commit |

下一輪建議（依時段）：白天做 #32（離線對照，不出聲）；夜間仍等耳麥配對與 MAC（#6）；#16、#18、#20、#23、#24、#25、#28、#29、#31、#33 等你決定；目前 2 個未推送 commit，累積到 3 個再推。

## 17. 本輪更新（2026-11-10 08:23–08:45 定時循環，台北時間）

- **唯讀觀察：** Pi `/health` 為 `degraded`（redis，同 #8）；`/api/status` 為 `done`；`/api/bt/status` 為 connected=false，trusted 只有控制器（#6 仍阻塞）。開始時 `main` 領先 gitlab／origin 各 2 個 commit（`456ce73`、`878995d`），無 `.git` lock。
- **#32 分析（完成）：** 07:24 的 1 分 E2E（`e2e_1min_456ce73.json`）`facts_missing` 只有兩項：`T2品質-原不良率`（逐字稿「百分之四」→「4-1%」）與 `T2品質-缺陷`（「外殼刮傷」→「外科誒」）。皆為 STT 同音或數字誤認，屬 ASR 限制（同 #26），沒有可泛化的文字規則，未改程式。
- **3 分 E2E 08:25 FAIL（`deploy_456ce73`，報告 `20261110_082538`）：** 唯一失敗項 `summary_no_placeholder`。`summary_raw` 的標題為「## U+FFFD要」：「摘」所在的多位元組字被串流切斷，解碼後變成 U+FFFD。標題認不出 → 「## 要」保留，`ensure_sections` 補上「模型輸出長度不足」佔位。離線重放（`.cc_scratch/replay_34_fffd.py`，輸出 `.cc_scratch/replay_34_out.txt`）確認舊版（456ce73）重現相同佔位，與 #19 症狀一致。
- **#19 真因更正：** #19 原以為是「模型先寫空的『## 摘要』」（推測）。本輪的真實 `summary_raw` 證據指向 U+FFFD 標題。0f26dd5 的空摘要規則仍保留（單測仍有效），但真因以 #34 為準。
- **修改（commit `7606f00`，fix(summary)）：** `to_internal_sections()` 一開始先去掉 U+FFFD，再判斷標題。新增單測 `test_replacement_char_in_split_heading_does_not_hide_summary`，修改前 FAIL（重現佔位）、修改後 PASS。本機 pytest（Python 3.13，忽略 3 個 Linux 專屬模組）512 passed（原 511 + 1）。離線重放：新版無佔位、`## 摘要` 恢復。
- **部署（#5）：** 08:34 以 `deploy_on_pi.sh`（LF 副本，來源 `git archive 7606f00`）部署到 raspi678，OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261110_083403`；`summary_utils.py` md5 `073d0ea9…` 與來源一致。過程中一次失誤：遠端 `sed -i` 的 `\r` 未加引號，被 shell 吃掉，只毀損暫存目錄（`bash -n` 失敗，未部署、線上程式未動）；改用 `s/\\r$//` 重做後才部署。
- **3 分數位 E2E（08:34，`deploy_7606f00/e2e_reports/20261110_083416`）：** PASS（0/1 failed）。CER 0.1582、逐字稿事實 0.8529、總結事實 0.8333（逐字稿內 1.0）、議題覆蓋 1.0、紀要召回 0.8333（缺 `T1供應商-供應商`，同 #28）、STT NPU 27/27；summary 延遲 108.64 s；最高溫 51.2 °C；RAM 峰值 2784 MB。
- **git：** 推送 `6ba0509..7606f00` 到 gitlab 與 origin，兩端皆成功（PowerShell 顯示 stderr，exit code 0，同 #22）。`main` = `origin/main` = `gitlab/main` = `7606f00`，目前無未推送 commit。`tools/git_sync.cmd` 仍為 M，未併入；`.cc_scratch/` 未 commit。
- **新觀察（與 #29 相關）：** 同一 raw 的 LLM 摘要有 7 條，`clean_summary_markdown` 的上限 5 截掉後 2 條（招募業務部、工業閘道器）。議題覆蓋仍為 1.0，因為待辦表有列。#29 仍等你決定。
- **工具注意：** `device_bash` 仍無連接資料夾（#20），本輪以 Desktop Commander 讀寫 `F:\` 與 SSH。`git show ... | Out-File` 會把 UTF-8 內容轉成 cp950，造成 .py 語法錯誤；改用 `cmd /c "git show ... > file"` 重導向。

新增待辦（併入 §4 表，編號接續）：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 34 | 3 分 E2E 08:25 `summary_no_placeholder` 失敗（#19 同症狀）；真因：`summary_raw` 標題含 U+FFFD | ✅ commit `7606f00`，部署 08:34 OK，3 分 E2E 08:34 PASS | 串流中多位元組字被 token 邊界切斷。來源未查證（推測：LLM 服務的 detokenizer 或 JSON 編碼；`llm_backend.py` 只看到已替換的字元）。若再出現非標題處的 U+FFFD，檢查串流解碼層，不要只在摘要段處理 |
| 35 | D1 長會議 45 分鐘 digital E2E（null-sink，不出聲） | ✅ PASS（10:19 完成；suite 0/1 failed；CER 0.2674） | 日誌 `/home/pi/ln_e2e/run_45min_0930_7606f00.log`；報告目錄會在 `/home/pi/ln_e2e/deploy_7606f00/e2e_reports/` 下以時間戳建立。下一輪先看 `/api/status`：recording／processing 時只讀不測；done 且 PID 已結束才讀 `summary.md` 並更新本列。60 分鐘（`--minutes 60`）列為下一步，本輪未排入 |

## 18. 本輪更新（2026-11-10 09:23–09:40 定時循環，台北時間）

- **唯讀觀察：** Pi `/api/status` 為 `done`，最後 job `m_1794270860`（08:34 的 3 分 E2E，已結束）；`/health` 仍 `degraded`（redis，同 #8）；`/api/bt/status` connected=false，trusted 只有控制器（#6 仍阻塞）。git：`main` = `origin/main` = `gitlab/main` = `7606f00`，無未推送 commit，`.git` 無 lock。
- **#12 查明（文件與 UI 不一致，待你決定）：** 逐字稿區 `.transcript` 為 `max-height:360px`，位於 `code_dispatcher/ui.html`、`ui_client.html`、`static/index.html` 第 136 行（三份相同）。`code_dispatcher/*.html` 內搜不到 `165px` 與 `overflow-y`。`165px` 規格只寫在文件（根目錄 `CLAUDE.md` 122 行、`AGENTS.md` 71 行、`.claude/CLAUDE.md` 92 行、`.agents/rules/project_rules.md` 68 行），描述的「即時雙語卡片」在目前 UI 沒有對應實作（推測：規格過時）。未改任何檔。
- **#34 補充（來源定位）：** 08:34 job `m_1794270860` 的 `summary_raw` 標題仍為 `## �要`（含 U+FFFD），但 `summary_stream` 與最終紀要都正常，3 分 E2E PASS。`llm_backend.py` 對 `iter_lines()` 只做 `json.loads`，不會自行產生替換字元，因此 U+FFFD 很可能來自 LLM 服務端的 token 解碼（推測，未驗證）。repo 內已在 `meeting_minutes.py`（710、988 行）、`summary_utils.py`（103、226、735、891 行）、`hailo_whisper/engine.py`（916 行）多處清除。目前沒有非標題處的 U+FFFD 證據，不改串流層。
- **D1 長會議組：** 45 分鐘已開始（#35）；60 分鐘尚未執行。
- **工作鎖：** 09:30 起持有，範圍僅 Pi 45 分數位 E2E（背景，`setsid nohup`）；未部署、未 push、未改程式。
- **工具注意：** DC 的 PowerShell 會吃掉雙引號字串內的 `$_`，本輪改用 `findstr` 與不含 `$` 的指令；遠端 SSH 指令一律單引號包住。

## 19. 本輪更新（2026-11-10 10:23–10:30 定時循環，台北時間）

- **唯讀觀察：** Pi `/health` 為 `degraded`（`redis_connected=false`，同 #8）；`/api/status` 為 `done`，最後 job `m_1794274039`（09:30 起的 45 分 E2E，2792 s，已結束）；`/api/bt/status` connected=false，trusted 僅 `RichChipBOBO`（`A0:D1:2A:00:0B:6D`）未連線，pipewire 只有 `Dummy Output`（#6 仍阻塞）。
- **git（唯讀，`git --no-optional-locks`）：** `main` = `origin/main` = `gitlab/main` = `7606f00`，無未推送 commit。`tools/git_sync.cmd` 仍為 M；`.cc_scratch/`、根目錄 `CLAUDE.md`、`claude_context/`、`tools/pi_*_remote.sh` 等仍未追蹤（同 #7、#23）。
- **45 分 E2E 結果（`/home/pi/ln_e2e/deploy_7606f00/e2e_reports/20261110_092713/`，suite PASS，failed 0/1）：** CER 0.2674（門檻 ≤0.4）、逐字稿事實召回 0.9411（門檻 ≥0.6）、總結事實召回 1.0、議題覆蓋 1.0、summary 延遲 320.63 s（門檻 ≤678）、STT NPU 427/427、錄音 CPU 2.4%、最高溫 54.0 °C、RAM 峰值 3173 MB、swap 增量 31 MB。
- **品質疑慮（新，#36）：** 同一份 45 分總結與逐字稿中可讀到明顯非詞句，例如「回額額額」「完成全元復une」「庭經理」「軍訂單」，逐字稿夾雜英文（`three-pointed`、`b lye`）。現行 check 只量事實召回與議題覆蓋，這類破碎字串不會被攔截，所以仍顯示 PASS。
- **CER 偏高（新，#37）：** 45 分 CER 0.2674，高於 3 分的 0.1582–0.2007 與 1 分的 0.1864–0.1949（數值見各報告）。是否為長度效應或 chunk 誤差累積屬推測，未驗證。
- **#15 本輪未再出現：** 45 分的議題覆蓋為 1.0，未觸發 0.5 的情況。
- **工作鎖：** 開始時仍為 09:30 持有（距開始 54 分，未過 60 分鐘期限）。依規則本輪不做 Pi 測試與 git 寫入，只做唯讀與文件更新。`pgrep` 確認 `run_suite` 已無程序。鎖於 10:30 過期，下一輪可依 §4 規則判斷是否做 60 分 E2E（#35 後續）。
- **工具注意：** `device_bash` 因未連接任何資料夾無法使用（同 #20）；本輪未發出資料夾權限請求（依規定跳過，已記於此）。DC 的 PowerShell 輸出預設非 UTF-8，需先設定 `[Console]::OutputEncoding=[System.Text.Encoding]::UTF8`，否則中文會亂碼。

新增待辦（併入 §4 表，編號接續）：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 36 | 45 分總結含非詞句（「額額額」「une」「庭經理」等），現行 check 未攔截 | 🔍 分析完成（11:3x，見 §20）：非詞句是 ASR 逐字稿原樣傳入，摘要照抄；待你決定是否加指標 | 先以 `e2e_45min.json` 與 `summary_stream` 人工抽樣比對，確認是 LLM 生成還是 STT 錯誤傳遞。若要加指標（例如非詞句比例），需先與你確認，不改 `thresholds.json`，也不以關鍵字表過擬合 |
| 37 | 45 分 CER 0.2674 偏高，高於 3 分與 1 分 | ✅ 分析完成（12:3x，見 §21） | 近似拆解：替換 63%、刪除 30%、插入 7%。分段 CER 沒有隨時間上升（最高第 7 段 0.315，第 1 段 0.248，第 10 段 0.290）。偏高的主因是評分正規化不一致（數字格式、周/週），已列為 #42；其餘為 ASR 同音誤認與刪字。未改程式 |
| 38 | 白天 E2E 規則下，45 分 E2E 已完成；60 分（`--minutes 60`）已排入 | ✅ 完成（13:37，FAIL 1/1：swap_growth_mb 75 > 64，見 #43、§22） | 鎖 10:30 過期後，若 Pi 為 `done` 且無其他 E2E 程序，可排 60 分數位 E2E（白天、null-sink）。需先寫入工作鎖 |

## 19 補充：下一輪建議

- 先讀本檔 §4 與 §19，確認工作鎖已過期後，才寫入鎖並做 Pi 測試或 git 寫入。
- 既有未 commit 的 `tools/git_sync.cmd` 與未追蹤檔仍待你決定（#7、#10、#23）。

## 20. 本輪更新（2026-11-10 11:23–11:34 定時循環，台北時間）

- **唯讀觀察（11:24）：** Pi `/api/status` 為 `done`。最後 job `m_1794278901` 是 10:48 的 86 秒藍牙測試（互動 session，與 §4 鎖欄的記錄一致），不是本循環產生，也不是新錄音。耳麥 RichChipAN 目前 connected=true、電量 100%，且為 pipewire 預設 sink。`/health` 仍 `degraded`（redis，同 #8）。git 開始時 `main` = `origin/main` = `gitlab/main` = `7606f00`，`.git` 無 lock。
- **#36 分析（完成）：** 45 分總結的非詞句是 ASR 逐字稿原樣傳入，摘要照抄，不是 LLM 生成。「回額額額」來自逐字稿第 39 議題的「週四前回額額額」；「全元復une」「品的工程成」「負責公安赦」來自結尾總結句。LLM 沒有見到新增的非詞句（推測：僅照抄；未逐句核對）。現行 check 只量事實召回與議題覆蓋，因此不會攔截這類字串。是否加指標，待你決定。
- **45 分逐字稿的其他 ASR 型態（記錄，未改）：** (a) 英文短片語夾在中文中，例如 `three-pointed`、`b lye`、`to increase the 2-way`、`to 2位工程師`、`in 50臺`、`of 8月9日`、`on the 80-10`、`ZeroZero`，共 44 段英文字串。現行 `_CJK_ISLAND_EN_RE` 只拿掉 4 詞以上全小寫的片語，不涵蓋這些。擴大規則需真人錄音驗證，以免誤傷（同 #18）。(b) 同字三連，例如「負責通知」被聽成「負負負所」、「額額額」。它與「好好好」同形，無法用通則區分，不動。
- **#37 觀察（未拆解 S/D/I）：** 45 分 hyp 8363 字、ref 8937 字，少 574 字（約 6.4%）。事實召回漏 38 項，分布在全程，未集中在某一段。報告未留存 CER 的替換／刪除／插入拆解，無法確認主因（推測以刪字為主）。
- **#39（新，✅ commit `1e00751`）：** `code_dispatcher/voice_pipeline.py` 的 `collapse_phrase_loops()` 原本只壓 2 字以上的片語，因此單字迴圈「的，的，的，的，的，的」（45 分逐字稿「車用的的，的，…，淨室」）會被保留。修正：單一中文字後接逗號或頓號，重複 4 次以上時壓成一次。無標點的疊字（「好好好」）與 3 次以下（「是，是，是」）不動。單測 `tests/test_stt_segment_clean.py` 新增 2 例，先紅後綠。pytest（Windows，Python 3.13，忽略 3 個 Linux 專屬模組）514 passed、0 failed。
- **離線重放（`.cc_scratch/r12/replay_r12.py`，輸出 `replay_r12_out.txt`）：** 13 份快取逐字稿中，只有 45 分逐字稿改變（9499 → 9489 字，只刪去「的，」重複），其餘不變。
- **部署（#5）：** 11:29:56 以 `deploy_on_pi.sh` 部署 commit `1e00751` 到 raspi678，OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261110_112956`。`voice_pipeline.py` md5 `0d98b7be…` 與來源一致。部署前 `/api/status` 為 `done`，最後非 E2E job 距今約 40 分鐘，符合 G1。部署腳本使用 LF 副本（`git -c core.autocrlf=false archive` 取出後，將 `.py`／`.html`／`.sh` 的 CRLF 轉為 LF）。
- **1 分數位 E2E（null-sink，`deploy_1e00751/e2e_reports/20261110_113009/`）：** PASS（failed 0/1）。CER 0.1949（ref 236 字、hyp 217 字）；逐字稿事實 0.8182（缺 T2品質-原不良率、T2品質-缺陷，同 #26／#32）；總結事實 1.0；紀要召回 1.0；議題覆蓋 1.0；errors 0；llm_fallbacks 0；hailo_busy 0；STT NPU 13/13；summary 延遲 59.56 s；最高溫 49.6 °C；RAM 峰值 2675 MB。這段短音檔沒有單字迴圈，新規則在線上未被觸發，屬預期；行為由離線重放驗證。
- **#24（部分解）：** 啟動 E2E 時加上環境變數 `CI_COMMIT_SHORT_SHA=1e00751`，報告的 commit 欄即正確顯示（本輪為 `1e00751`）。循環自動啟動時照此傳入即可。`deploy_<sha>` 目錄仍沒有 `.git`；若要改為讀 `VERSION` 檔（選項 A），仍待你決定。
- **藍牙（觀察）：** 耳麥目前連線中，且是 pipewire 預設 sink。本輪 digital E2E 正常，未見影響。白天若有互動測試，請在 §4 鎖欄註明，避免循環誤判。
- **git：** `main` 領先 gitlab 與 origin 各 1 個 commit（`1e00751`），未達 3–5 個推送門檻，未 push。`tools/git_sync.cmd` 仍為 M，未併入；`.cc_scratch/` 未 commit。
- **工作鎖：** 11:27 寫入（本機 commit），11:29 再寫入（部署與 E2E），11:33 釋放。
- **回報：** 本輪有 commit、部署與 E2E 完成（新進度），且距上次回報（10:25）超過 15 分鐘，已發送一則回報。「最後回報」更新為 2026-11-10 11:34（台北）。
- **未做（原因）：** #38（60 分 E2E）本輪未排入：先完成部署與 1 分驗證，且該 E2E 約 65 分鐘，需確認無其他程序後再排。

新增待辦：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 39 | 單字逗號迴圈「的，的，的，的」未被壓縮 | ✅ commit `1e00751`；✅ 部署 11:29（md5 一致）；✅ 1 分 E2E PASS 11:33 | 60 分 E2E（12:25 啟動、13:37 結束，同 commit）逐字稿未見 4 連以上「的，」（僅 2 連 1 處，未逐句確認）；已結案（見 §22） |
| 40 | 45 分逐字稿的短英文片語（in／to／of／at 等夾在中文間）與同字三連（「負負負」） | 等待你決定 | 同 #18，需真人錄音驗證；若要處理，先列誤傷風險與離線重放結果，不以詞表處理 |
| 41 | 60 分數位 E2E（#38）已排入 | ✅ 完成（13:37）：FAIL 1/1，唯一失敗項 swap_growth_mb 75（門檻 ≤64），其餘通過；報告 `/home/pi/ln_e2e/deploy_1e00751/e2e_reports/20261110_122534/` | 已讀 `summary.md` 與 `mon_60min.jsonl`，結果見 §22；後續見 #43 |

## 20 補充：下一輪建議

- 先讀 §4 與 §20，確認鎖已過期、Pi 為 `done`，且最後非 E2E job 超過 15 分鐘，再做部署或 E2E。
- 白天可跑 #38，或做 #37 的 S/D/I 拆解（離線，讀 `e2e_45min.json` 與 fixture，不需 Pi）。
- 目前只有 1 個未推送 commit，累積到 3 個新 commit 再推。
- #6（夜間耳麥）等耳麥 MAC；#16、#20、#23、#24（選項 A／B）、#25、#28、#29、#31、#33、#40 等你決定。

## 21. 本輪更新（2026-11-10 12:23–12:32 定時循環，台北時間）

- **唯讀觀察（12:24）：** Pi `/api/status` 為 `done`，最後 job `m_1794281413` 為 11:30 的 1 分 E2E（已結束）。`/health` 仍 `degraded`（redis，同 #8）。`/api/bt/status` connected=true，耳麥 RichChipAN 為預設 sink、電量 100%。git：`main` 領先 gitlab 與 origin 各 1 個 commit（`1e00751`），`.git` 無 lock，未達推送門檻。
- **Pi 數位 E2E 啟動（#38／#41）：** 12:25:34 以 `run_suite.py --minutes 60` 背景啟動（`CI_COMMIT_SHORT_SHA=1e00751`，PID 2669349，log `/home/pi/ln_e2e/run_60min_1e00751.log`）。啟動前 Pi 為 `done`，最後非 E2E job 為 10:48 的互動測試（超過 15 分鐘）。12:30 `/api/status` 為 `recording`（E2E 自己開的工作，進度 7%，預估 3403 s 後完成）。本輪結束時仍在執行，工作鎖持有中，未 push、未部署。
- **#37 完成（離線分析，未在 Pi 上計算）：** 以 scp 把 `e2e_45min.json`（7606f00，10:19 報告）複製到 `F:\13_prj_raspi5_localnote\.cc_scratch\r37\`，用 `tools/e2e/scoring.py` 的 `norm`、`levenshtein` 與 difflib 近似拆解。本機無 opencc，所以本機 CER 為 0.2779，harness 為 0.2674，差 0.0105，推測來自繁簡與臺／台正規化。結果如下（近似，非最小編輯距離）：
  - 錯誤型態：替換 1569（63%）、刪除 750（30%）、插入 176（7%）。刪除減插入為 574，與「參考字數減逐字稿字數」8937 − 8363 = 574 吻合，可作為拆解的檢核。
  - 分段：把參考文字十等分，近似 CER 落在 0.244–0.315，沒有隨時間單調上升。最高為第 7 段（0.315），第 1 段 0.248，第 10 段 0.290。#37 原本的「隨時間上升」假設在 45 分中不成立。
  - 替換清單前列幾乎都是數字格式：fixture 用中文數字（十二、四週），逐字稿用阿拉伯數字（12、4週），如「十二→12」27 次、「八→8」26 次、「四→4」24 次。把兩邊數字都轉為阿拉伯數字後，本機 CER 由 0.2779 降為 0.1711。也就是說，CER 有相當大的部分來自格式不一致，而不是 ASR 聽錯（見 #42）。
  - 事實召回：harness 的 9 個「可撐週數」遺漏，逐字稿是「4周」、事實值是「4週」，只差「周／週」字形。加入周→週正規化後，事實召回由 0.9411 升為 0.9547（623→632／662）。
  - 其餘事實遺漏多為 ASR 真實錯誤：「宏遠科技」→「紅院科技」、「永豐光電」→「永途光」、「華新機電」→「滑興機店」、「聯華精密」→「迴華精密」、「台揚通訊」→「臺陽通」、「外殼刮傷」→「外課刮傷」、「按鍵失靈」→「按鍵失灶」；「警示燈」常丟「燈」字（7 次）。這些不宜以詞表處理（同 #4、#26）。
  - 報告 `report_37.txt`（拆解）、`report_37b.txt`（事實分型）、`report_37c.txt`（遺漏對照）、`report_37d.txt`（正規化敏感度），皆在 `.cc_scratch\r37\`，未 commit。
- **#42 新增：** 評分正規化不一致會影響 CER 與事實召回的讀數，見本節表格。未改 `scoring.py` 或 `thresholds.json`。
- **回報：** 本輪有 Pi 狀態改變（60 分 E2E 啟動）與新分析結論（#42 待你決定），距上次回報（11:34）已超過 15 分鐘，已發送一則回報；「最後回報」更新為 2026-11-10 12:32（台北）。

新增待辦（併入 §4 表，編號接續）：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 42 | 評分正規化不一致：中文數字 vs 阿拉伯數字、周/週、臺/台 | 等待你決定 | `norm()`（CER）沒有數字與臺/台正規化；`_fact_norm()` 有臺→台，沒有周→週。本機估計：數字正規化後 45 分 CER 0.2779→0.1711（未含 opencc，不可直接與 harness 的 0.2674 比較）；事實召回加周→週後 0.9411→0.9547。選項：(A) CER 與事實比對共用一份正規化（中文數字→阿拉伯、臺→台、周→週），改動前先重新量測基準、列出影響，不直接放寬 `thresholds.json`；(B) 把 fixture 改成阿拉伯數字（會改動人工標註的 ground truth，不建議）；(C) 維持現況。未實作 |

下一輪建議（依時段）：13:23 若 `run_suite` 仍在執行，只讀 `/api/status` 與 log，不做其他 Pi 測試與 git 寫入，只更新文件。60 分 E2E 完成後讀 `summary.md`，結案 #41，檢查 #39，並清除鎖。#42、#36、#40、#31、#33 等你決定。累積到 3 個新 commit 再推（目前只有 `1e00751`）。

## 22. 本輪更新（2026-11-10 13:23–13:41 定時循環，台北時間）

- **唯讀觀察（13:24）：** Pi `/api/status` 為 `recording`（job `m_1794284740`，94%），即 60 分 E2E 本身的錄音。錄音中，本輪不做 Pi 評估、不 push、不部署。git：`main` 領先 gitlab 與 origin 各 1 個 commit（`1e00751`），`.git` 無 lock。
- **等待與結果（13:37）：** 本輪以唯讀輪詢（`kill -0` 與 `/api/status`）等待 60 分 E2E 結束，未做任何評估。`summary.md`（`/home/pi/ln_e2e/deploy_1e00751/e2e_reports/20261110_122534/`）顯示 **FAIL 1/1**，唯一失敗項 `swap_growth_mb` = 75（門檻 ≤64）。其餘：CER 0.2723、逐字稿事實 0.9521、總結事實 1.0（逐字稿內 1.0）、議題覆蓋 1.0、summary 延遲 493.74 s、STT NPU 567/567、錄音 CPU 2.5%、最高溫 57.3 °C、RAM 峰值 3406 MB。
- **swap 觀察（#43，只讀 `mon_60min.jsonl`）：** swap_used 在錄音前約 3600 秒內持平於 369 MB，之後升至 441 MB（峰值 444 MB），增量 75 MB。RAM used 由 2133 MB 緩升至 2276 MB。45 分 E2E 的 swap 增量為 31 MB（PASS）。推測：增量集中在錄音尾端與長會議分段總結階段（LLM 記憶體），並非逐步洩漏；未驗證。
- **#39 結案：** 60 分逐字稿未見 4 連以上「的，」，僅有 2 連 1 處（符合門檻 4，未逐句確認）。
- **工作鎖：** 本輪未寫入鎖（只做唯讀等待與文件更新）。§4 鎖欄目前顯示互動 session 持有（部署 `1e00751` 到 raspi543）。本循環不碰 raspi543，也不做 Pi 測試或 git 寫入，直到該鎖釋放或過期。
- **未做的事（原因）：** 未改 `thresholds.json`（不為了通過而調門檻）；未改程式、未跑 pytest、未部署（本輪無行為變更）；未 push（只有 `1e00751` 1 個未推送 commit，未達 3–5 個門檻）。
- **工具注意：** `device_bash` 仍無連接資料夾（#20），本輪未請求資料夾授權（依規定跳過）。讀寫與 SSH 皆經 Desktop Commander。
- **回報：** 本輪 E2E 完成（新進度，FAIL 1 項），距上次回報（12:32）超過 15 分鐘，已發送一則回報；「最後回報」更新為 2026-11-10 13:41（台北）。

新增待辦：

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 43 | 60 分 E2E `swap_growth_mb` 75 > 門檻 64（FAIL）；45 分為 31（PASS） | 等待你決定（先分析，未改門檻） | 數據見 §22。下一步（白天可做，只讀與離線）：(a) 查 `mon_60min.jsonl` 中 swap 跳變的精確秒數，對照 `summary_stream` 與分段總結的起止時間；(b) 確認 Pi 上佔用 swap 的主要程序（推測為 LLM 服務），並比較 45 分與 60 分的差異；(c) 若確認為總結階段的峰值，選項：調整分段總結的併發或模型卸載時機（改程式需先寫單測，再依 `deploy_on_pi.sh` 部署），或與你討論是否調整 `swap_growth_mb` 門檻。預設不放寬門檻 |

下一輪建議（依時段）：14:23 為白天。先看 §4 鎖欄：若互動 session 的鎖仍有效（60 分鐘內），本輪只做文件與唯讀。鎖釋放後，可做 #43(a)(b) 的唯讀分析（mon 檔已在 Pi 上）。#42、#36、#40、#31、#33 等你決定；#16、#20、#23、#24、#25、#28、#29 亦待決定。未推送 commit 1 個（`1e00751`），累積到 3 個新 commit 再推。


## 22. 本輪更新（2026-11-10 13:34–13:40，互動 session，使用者要求「更新聽記盒到最新」）

- **raspi543 部署：** `1e00751` 已部署到 raspi543（192.168.50.229），`deploy_on_pi.sh` 結果 OK，備份 `/home/pi/code_dispatcher/.deploy_backup/20261110_133835`。`voice_pipeline.py` md5 `0d98b7be…`、`ui.html` md5 `c55e27e7…` 與 raspi678 一致；`/` 回應 HTTP 200；服務 active。
- **raspi543 `/health`：** `degraded`（`redis_connected=false`，同 #8），`llm_backend` 為 Hailo-10H NPU qwen3:1.7b；RAM 可用 15027 MB / 16218 MB。
- **raspi678 60 分 E2E（#35 後續）：** FAIL 1/1，報告 `/home/pi/ln_e2e/deploy_1e00751/e2e_reports/20261110_122534/`。唯一失敗項 `swap_growth_mb` 75（門檻 ≤64）；CER 0.2723、逐字稿事實召回 0.9521、紀要召回 1.0 皆 PASS。未修改 `thresholds.json`。是否調整門檻或處理 swap 成長，待你決定。
- **部署流程問題（已繞過）：** Windows 端 `git archive` 產生 CRLF 檔，`deploy_on_pi.sh` 第 6 行 `set -euo pipefail` 報錯，腳本在複製檔案前退出，raspi543 未被改動。修正：在 Pi 端用 `perl -pi -e 's/\\r$//'` 正規化後再部署。注意：bash 未加引號的 `\\r` 會變成 `r`，用 sed 時會誤刪行尾的 `r`。
- **未推送：** `1e00751` 仍只在本機，`origin` 與 `gitlab` 各落後 1 個 commit。


## 23. raspi678 已關機（2026-11-10 13:47，使用者要求）

- **狀態：** 互動 session 於 13:46 執行 `sudo -n shutdown -h now`，關機前 `/api/status` 為 `done`，無 E2E、錄音或服務程序在跑，無熱點連線裝置（`iw` 站台數 0）。60 秒後 HTTP 與 ping（192.168.50.228）皆無回應。
- **raspi543（192.168.50.229）：** 仍在線，`/health` degraded（同 #8），聽記盒可用。
- **定時循環指示：** raspi678 離線期間，不做任何 678 測試、E2E、部署或 Pi 寫入。若連不上 192.168.50.228，本輪只記錄「678 離線」，不重試超過一次，也不嘗試重開機。
- **重新開機：** raspi678 沒有遠端喚醒機制，需由人到現場按電源。開機後先確認 `/health` 與 `/api/bt/status`，耳麥仍需重新配對或確認自動連線（#6）。
- **#5 與 #24 的部署目標：** 之後若要再部署，請先確認目標機（678 或 543）與其線上狀態。
- **未推送：** `1e00751` 仍只在本機（同 §22）。


## 24. 推送完成（2026-11-10 13:52，互動 session，使用者要求）

- **推送：** `7606f00..1e00751` 已推送到 gitlab（`main -> main`）與 origin（`main -> main`），兩邊 exit 0，沒有帳密提示。
- **注意：** 第一次推送時，`$env:GCM_INTERACTIVE=never` 因 PowerShell 語法錯誤沒有設定成功；`GIT_TERMINAL_PROMPT=0` 有生效。之後的推送請先確認兩個環境變數都已設定。
- **本機：** `tools/git_sync.cmd` 仍有未提交修改（M），未被推送。
- **raspi543：** 仍在 `1e00751`（見 §22）。raspi678 仍關機（見 §23）。


## 25. 本輪更新（2026-11-10 14:24–14:27 定時循環，台北時間）

- **唯讀觀察（14:24）：** raspi678（192.168.50.228）SSH 逾時（`banner exchange ... Connection timed out`）。依 §23 規定只嘗試一次，未重試、未嘗試遠端開機。最後已知狀態仍是 13:46 的關機。
- **git（本機唯讀）：** `main` = `origin/main` = `gitlab/main` = `1e00751`，無未推送 commit，`.git` 無 lock。`tools/git_sync.cmd` 仍為 M，未併入；未追蹤檔與 §18 相同，未 commit。
- **本機 pytest（HEAD `1e00751`，Python 3.13，忽略 3 個 Linux 專屬模組）：** 514 passed、0 failed，與 §14 之後的數字一致。
- **工作鎖：** 無，本輪未寫入（未做 Pi 測試、未做 git 寫入）。
- **未做（原因）：** Pi 測試、部署與 E2E 都被 678 離線阻塞。#43 的 (a)(b) 分析需要 678 上的 `mon_60min.jsonl`，本輪無法取得。
- **回報：** 14:25 因 Pi 狀態改變（678 離線）發送一則回報，最後回報更新為 2026-11-10 14:25（台北）。
- **事故（需你處理）：** 本輪誤呼叫 `send_later` 建立一則內容為 `placeholder` 的一次性排程（`trig_01XZgTpBTgR2tNS8Aa7dm9o9`，約 15:26 台北時間會送回本 session）。刪除與停用都被權限拒絕，因此保留，未再嘗試其他方式。請到排程清單手動刪除。若它仍送出，內容只是無意義文字，不會觸發任何動作。

| # | 項目 | 狀態 | 備註 / 下一步 |
|---|---|---|---|
| 44 | raspi678 離線（需人工開機） | 等待你決定（人工） | 13:46 互動 session 關機；14:24 SSH 逾時。循環不請求硬體操作，也不嘗試遠端開機。開機後先確認 `/health`（redis 仍 degraded 屬 #8）與 `/api/bt/status`。#6、#43 與後續 E2E／部署都待 678 上線後才能做 |
| 45 | 誤建一次性排程 `trig_01XZgTpBTgR2tNS8Aa7dm9o9`（內容 `placeholder`） | 等待你決定（人工刪除） | 刪除與停用皆被權限拒絕，請到排程清單刪除。已記錄，不再嘗試 |

下一輪建議（依時段）：先 SSH 一次確認 678 是否已上線（不重試超過一次）。若仍離線，本輪只更新文件。上線後依 §4 規則確認 /api/status 為 `done` 再做 #43 (a)(b) 唯讀分析。#42、#36、#40 等你決定。目前無未推送 commit。
