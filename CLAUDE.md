# 🤖 Pi 5 Local Note - Claude Code Instructions & Project Memory (CLAUDE.md)
# 樹莓派 5 邊緣雙語口譯、語音筆記與藍牙網關專案記憶檔案

> 本文件為 Claude Code / Claude Desktop 專案記憶與行為準則中樞。在此專案目錄（`F:\14_prj_raspi5_localnote_asia`）工作時，必須嚴格遵守下列所有工程規範、歷史經驗、避坑指引與部署設定。
> 📌 **跨 AI 接棒與完整上下文目錄 (`claude_context/`)：** 當接手 Antigravity 的工作或進行自主閉環工程時，請同步參閱 `claude_context/` 目錄下的 6 份核心文件（`CLAUDE.md`、`PROJECT_STATE.md`、`HARDWARE_OPERATION_GUIDE.md`、`API_AND_TEST_REFERENCE.md`、`ACTIVE_BACKLOG_AND_NEXT_STEPS.md`、`AI_HANDSHAKE_PROTOCOL.md`）。

---

## 1. 角色身分與行為準則 (Identity & Core Rules)

- **Role:** 資深主任工程師與架構師 (Senior Staff Software Engineer & Architect)。極度重視效率、正確性與可維護性 (Maintainability)。
- **Tone:** 直接、精簡、專業。不說廢話、不進行無意義的客套。
- **Language:** **嚴格使用繁體中文 (Traditional Chinese)** 進行回應。
- **Terminology:** 關鍵技術詞彙必須同時提供中英文對照，格式為：`中文 (English Term)`。
  - *範例:* 「請進行重構 (Refactor) 並確認依賴注入 (Dependency Injection)」。
- **KISS 原則 (Keep It Simple, Stupid) & 拒絕自幹 (No DIY):**
  - 最簡邏輯、可讀性至上。避免過度設計 (Over-engineering)。
  - 優先使用現成標準套件或工具，絕不重新發明輪子 (Don't Reinvent the Wheel)。
- **No Hallucinations (嚴禁幻覺與自行編造):** 嚴禁編造代碼、不存在的 API 參數、未量測到的數據或未驗證的結論。每個「根因」「已修好」「正常」的陳述都必須對應到實際執行過的指令輸出或日誌；推測必須明確標示為推測。不確定時直說「不確定」並提出可驗證的下一步，不得用猜測填補空白。
- **定時回饋進度 (Progress Reporting):** 任何超過 3 分鐘的任務，必須主動回報進度：目前在做什麼、已確認的事實、下一步、預估剩餘時間。背景長任務要輪詢結果並回報，不得讓使用者等待而沒有訊息。
  - **回報節奏（2026-11-09 使用者指定，取代先前 15/30/60 分鐘退避）：**
    1. 回報間隔不少於 **15 分鐘**、不多於 **4 小時**。
    2. 沒有新進度時不單獨回報，併入下一次回報。
    3. 距上次回報已滿 **4 小時**，即使沒有新進度也回報一次。
    4. 使用者一旦回覆或互動，間隔重新計算。
  - 待辦與狀態以 `claude_context/ACTIVE_BACKLOG_AND_NEXT_STEPS.md` 的「4. 待辦清單」為準；定時 review 每次讀取並更新它，只有符合上述條件才回報。
- **持續 loop engineering（2026-10-30 使用者指定）：**
  - 整天持續「自測 → 找問題 → 修改 → 驗證」，把系統改到最佳。
  - 只有使用者明確叫停才停。
  - 叫停後，如果連續 **4 小時**使用者都沒有交代新事情，就自動接著做 loop engineering。
  - 跑的時候照樣遵守上面的回報節奏規則，以及錄音中不跑吃 CPU 的工作。
  - 不需要使用者也要能自行恢復、接續測改，週末也一樣，不要停工（2026-10-30 17:53 使用者指定）。每次工作告一段落前，先用排程提醒排好下一次喚醒，避免停在那裡。
  - **使用者不在時，不要送任何需要使用者按確認的請求**（刪除權限、電腦控制權限、資料夾權限…）：請求沒人回應時整個工作會停住（2026-11-02 19:14 等刪除權限，停到隔天 09:25）。
    - git 留下 `.lock` 而沒有刪除權限時，先改名移開（例如 `mv .git/HEAD.lock .git/stale-HEAD-lock`），不要等授權。
    - git commit／push 改用 Desktop Commander（Windows 本機的 git）執行，它能自己清掉 lock；device_bash 只用來讀檔、跑測試。
    - 需要權限的事（例如 Git GUI 推送）留到使用者在的時候做。
- **連續自測含藍牙收音時，先開耳麥的自動連線 (Auto-Connect)（2026-10-30 使用者指定）：**
  - 開跑前，在 BT 管理裡把要用的耳麥「自動連線」打開：`POST /api/bt/trusted/auto_connect`，body 為 `{"mac": "<耳麥 MAC>", "auto_connect": true}`。
  - 原因：兩輪測試之間空檔太久，耳麥會進入睡眠然後關機（10-29 20:48 RichChipAN 就這樣關掉）。一旦關機，只能請人到現場重新開機。
- **喇叭出聲、藍牙耳麥的自測只在晚上 19:00 到隔天早上 07:00 做（2026-11-02 使用者指定，取代原本的午休規則）：**
  - 白天 07:00–19:00 不跑任何「PC 喇叭放音」或「用藍牙耳麥收音」的測項（使用者白天會切換 PC 音源、使用耳麥）。
  - 白天仍可做其他工作：數位直送 e2e（null-sink，不出聲）、離線重放、分析、改程式、寫文件。
  - 開跑前確認 PC 音源輸出是靠近耳麥的喇叭，並看前 30 秒的即時逐字稿有沒有正常內容；只出現重複的幻覺句（例如「I'm a little bit of…」）就代表沒收到聲音，立刻取消。
  - 錄音進行中，不要在 Pi 上跑任何評估或計算。
- **累積 3～5 個 commit 就自動 push（2026-10-30 使用者指定）：**
  - 本機累積 3～5 個已驗證的 commit 時，不必再問，自己找空檔推上 GitHub (origin) 與 GitLab (gitlab)。
  - 空檔：沒有在錄音、也沒有在跑會用到電腦的測試時。
  - 2026-11-03 起用 Desktop Commander MCP 在 F:\14_prj_raspi5_localnote_asia 直接跑 `git push origin main`、`git push gitlab main`（先設 `GIT_TERMINAL_PROMPT=0`、`GCM_INTERACTIVE=never`，出現帳密提示就停下來問）；不必再搶畫面開 Git GUI。
  - 推完回報推了哪些 commit、兩邊是否都成功。
- **No Placeholders:** 嚴禁留下 `// TODO` 或未完成區塊，程式碼產出必須完整且可執行 (Production-ready)。
- **Error Handling:** 顯式錯誤處理 (Explicit Error Handling)，嚴禁使用 bare `try: ... except: pass`。
- **Async First:** 涉及 I/O (網路請求、DB) 一律使用 `async/await`。

---

## 2. 遠端版本控制與推送規範 (Git Remotes & Push Workflow)

本專案配置有 GitHub 與 GitLab 雙遠端倉庫，任何程式碼更新必須保持雙端同步：

- **GitLab (主倉庫 / Remote: gitlab):**
  - URL: `http://andrew.lee@gitlab.mytekcentral.com:8081/andrew.lee/pi5-hailo-localnote-asia.git`
  - 授權身分: `andrew.lee`
  - 推送指令: `git push gitlab main`
- **GitHub (Remote: origin):**
  - URL: `https://alntu2@github.com/leemailto2008/pi5-hailo-localnote-asia.git`
  - 授權身分: `alntu2` (Windows Credential Manager / PAT)
  - 推送指令: `git push origin main`
- **歷史相容倉庫 (Legacy Remotes):**
  - `origin-legacy`: `https://alntu2@github.com/leemailto2008/pi5-llm-localnote.git`
  - `gitlab-legacy`: `http://andrew.lee@gitlab.mytekcentral.com:8081/andrew.lee/pi5-llm-localnote.git`
- **一鍵雙推規範：**
  - 提交訊息遵循 Conventional Commits（`feat:`, `fix:`, `docs:`, `chore:`）。
  - 驗收完成後執行：`git push gitlab main && git push origin main`。

---

## 3. 樹莓派主機環境與 SSH 連線資訊 (Raspberry Pi 5 Environment)

- **硬體平台:** Raspberry Pi 5 (raspi543: 16GB RAM / raspi678: 8GB RAM), Debian 13 (Trixie), kernel 6.18.50 (raspi543 於 2026-10-22 升級；Hailo 驅動 `hailo1x_pci` 走 DKMS)
- **網路 IP 位址 (兩台主機):**
  - `raspi543` 家用 Wi-Fi (STA): `192.168.50.229` (Web UI: `http://192.168.50.229:8000/`，Uvicorn 實際監聽 80，由 `pi5-port8000-proxy.service` 轉發)
  - `raspi678` 家用 Wi-Fi (STA): `192.168.50.228`（常處於熱點模式供測試人員使用）
  - 獨立熱點模式 (AP Mode): `10.20.0.1` (SSID: `raspi543_AI`, Web UI: `http://10.20.0.1:8000/`)
- **SSH 遠端連線 (Paramiko / OpenSSH):**
  - 主機: `192.168.50.228` (或熱點時 `10.20.0.1`)
  - 帳號: `pi`
  - 私鑰路徑: `C:\Users\Andrew\.ssh\id_rsa_pi5`
  - 連線命令: `ssh -i C:\Users\Andrew\.ssh\id_rsa_pi5 pi@192.168.50.228`
- **遠端專案運行目錄:**
  - 主目錄: `/home/pi/code_dispatcher/`
  - 音訊快取 (RAM-Disk): `/dev/shm/audio_cache/`
- **核心 Systemd 服務:**
  - `pi5-dispatcher-api.service`: FastAPI 後端主服務 (Uvicorn 8000 port)
  - 重啟指令: `sudo systemctl restart pi5-dispatcher-api.service`

---

## 4. 核心架構決策與重大避坑記憶 (Critical Architectural Gotchas & Decisions)

### ⚠️ [重點一] 樹莓派 5 藍牙 mSBC 16kHz 硬體 UART 總線特性與音訊零爭搶 (Zero-Contention)
- **硬體物理限制:** 樹莓派 5 的藍牙晶片共用單一實體硬體 UART 串列總線 (`/dev/ttyAMA0`)。藍牙寬頻語音 (mSBC, 16kHz) 採用 SCO 通道，嚴格每 7.5ms 傳輸一幀。
- **嚴格禁忌 1 (禁止錄音中執行推論):** 
  - 錄音進行中（`is_recording == True`），**絕對禁止**在背景啟動 faster-whisper 或 CTranslate2 等 CPU/矩陣計算密集模型。OpenMP 多核心運算會引起記憶體匯流排與 CPU 爭搶，導致 `wireplumber` 錯過 7.5ms 時間窗口，噴發大量 `spa.bluez5.source.sco: decode failed: -3` 造成嚴重視訊碎裂與斷流。
  - **解決方案:** 錄音期間將 CPU 0/1 與記憶體頻寬 100% 獨占保留給音訊守護行程；待錄音結束退出 ffmpeg 後，再釋放全 4 核心（`cpu_threads=4`）進行高精度全軌 STT。
- **嚴格禁忌 2 (禁止錄音中執行 HCI 指令):**
  - 錄音期間**絕對禁止**呼叫 `hcitool lq`、`hcitool rssi` 或高頻 `bluetoothctl info` 輪詢。HCI 控制指令會直接阻塞 UART 佇列，導致 SCO 封包丟失引發斷流與 DC 偏移跳變暴音 (Transient Click Artifact)。
  - **解決方案:** 在 `voice_streaming.py` 實裝 `is_any_recording_active()` 全域守衛；API 端點若處於錄音中直接回傳記憶體快取。

### ⚠️ [重點二] 瞬態平滑帶通濾波器 (Bandpass Filter)
- ffmpeg 錄音參數固定採用 `-af "highpass=f=80,lowpass=f=7600"`，濾除 80Hz 以下低頻共振與 7.6kHz 以上的高頻階躍毛刺，杜絕末端暴音。

### ⚠️ [重點三] 零磁碟寫入原則 (Zero-Disk I/O)
- 音訊捕捉全數掛載於 Linux POSIX 記憶體磁碟 (`/dev/shm/audio_cache/`)，不產生任何實體磁碟 WAV/MP3 寫入 (0 Flash Wear)，極致保護樹莓派 MicroSD / NVMe 壽命。

### ⚠️ [重點四] 即時串流分塊轉譯與打字機動效 (Streaming STT & Speculative LLM)
- 單路 segment 切片錄音 (6s/chunk)，錄音結束後以 ffmpeg concat demuxer copy 合併母帶。
- **LLM 後端統一走 `code_dispatcher/llm_backend.py`**（2026-10-22 起）：`hailo`（hailo-ollama `127.0.0.1:11435` / `qwen3:1.7b` on Hailo-10H，CPU 歸零）優先，健康檢查 20s 快取，失敗自動退避 `cpu`（Ollama `11434` / `qwen2.5:3b-opt` → `qwen2.5:3b`）。環境變數 `PI5_LLM_BACKEND=cpu` 可強制切回。`/health` 回傳 `llm_backend` 顯示當前後端。
- 實測效能：Hailo qwen3:1.7b TTFT ≈ 0.6s、≈ 4.5 tok/s；CPU qwen2.5:3b-opt TTFT ≈ 0.2s、≈ 6 tok/s。**Hailo 版的價值是 CPU 零占用（藍牙零爭搶），不是速度。**
- 所有 LLM 呼叫一律用 `chat_complete / iter_chat_stream / achat_complete / aiter_chat_stream`，嚴禁再直接 `requests.post("…11434/api/generate")`。

### ⚠️ [重點五] 手機端 Web 控制台最佳化 (Mobile Responsive Web UX)
- **文字捲軸 (Scrollbar):** 語音轉錄與即時英文雙語卡片設定 `max-height: 165px; overflow-y: auto;`，並在 SSE 更新時自動 `scrollTop = scrollHeight` 平滑跟隨最新文字。
- **藍牙卡片折疊 (Collapsible Hub):** 支援一鍵折疊，收合時僅留設備名稱、連線狀態與 🔋 電量膠囊，狀態由 `localStorage` 持久化。
- **受信任耳麥清單 (Trusted Devices):** 支援多耳麥環境，每支耳麥可獨立切換「自動連線 (Auto-Connect)」開關，並支援指定耳麥手動連線與設為預設。

### ⚠️ [重點六] 藍牙耳麥掃描與配對：BR/EDR 專掃 + 單一會話 + 守護行程不得碰未配對裝置 (2026-10-22 實測)
- **症狀:** Web 掃描看不到 RichChipAN（iPhone 看得到）、配對回 500、耳麥一被「連線」就退出配對模式。
- **根因 1 — `scan on` 交錯輪詢:** HFP 耳麥走傳統藍牙 (BR/EDR)，`transport auto` 在 LE/BR-EDR 間交錯，8 秒窗口經常錯過；同一支耳麥的 BLE 分身（隨機位址 `C0:…`，名稱 `Air Shutter`）卻每次都看得到，使用者點它 → `trust` 成功 `pair` 失敗 → 留下幽靈。**一律用 `scan bredr`，未配對的 `(random)` 位址不列出。**
- **根因 2 — BlueZ 暫存設備即時清除:** discovery 結束後 `info MAC` 立刻 `not available`，分開呼叫 `scan` 再 `pair` 必失敗。**`scan → pair → trust → connect` 必須在同一個 `bluetoothctl` 會話內完成**（`BluetoothctlSession`，以 pty 驅動；plain pipe 會被 readline 全緩衝）。
- **根因 3 — 自動重連守護行程搶連:** `auto_reconnect_tick()` 對 `default_mac` 無條件 `connect`，耳麥一進配對模式就被它連上又斷開，直接踢出配對模式。**只對 `devices Paired` 的裝置重連；`_bt_exclusive` 鎖住期間（掃描/配對中）一律跳過。**
- **順序原則:** `pair` 成功後才 `trust`，杜絕 trusted-but-unpaired 幽靈。
- **除錯工具:** `tools/pi_run.cmd <ip> <script.sh>`、`tools/pi_push.cmd <ip> <local> <remote> [script.sh]`，輸出在 `tools/pi_probe_out/`（已 gitignore）。

### ⚠️ [重點七] hailo-ollama (0.5.1) API 相容性陷阱 (2026-10-22 實測)
- 只有 `/api/chat` 會遵守 system message；`/api/generate` 的 `system` 欄位被忽略。
- `keep_alive` 必須是整數或省略，Ollama 風格字串 `"24h"` → HTTP 500 `Value is NOT a Primitive type`。
- 回應沒有 `eval_duration / prompt_eval_duration`，TPS 必須在客戶端計時。
- **prompt 內含原始換行 / Tab / 反斜線 → HTTP 500 `Failed to render prompt (status=8)`**（它內部組 JSON 只跳脫引號）。`llm_backend._sanitize_for_hailo()` 把 `\n`→字面`\n`、`\t`→字面`\t`、`\`→`\\`，模型端會還原成真正的換行。
- 並行請求會在 server 端排隊（不會錯），但會拉長 TTFT。
- `curl` 測試務必帶 `-H "Content-Type: application/json"`，否則 oatpp 回 `No suitable mapper`。

### ⚠️ [重點八] 藍牙耳麥錄音靜音/破碎的真正根因：mSBC (EDR 2-EV3) 位元錯誤 → 強制 CVSD (2026-10-22 實測結案)
- **症狀:** 錄音檔 20–70% 樣本為數位零值（100–500ms 整段空洞），wireplumber 大量 `spa.bluez5.source.sco: decode failed: -3`，Whisper 輸出幻覺。
- **已排除（全部實測）:** CPU 爭搶、Wi-Fi 共存（含完全關閉）、PipeWire/bluez/核心版本、Hailo HAT（拆除仍壞）、PCIe Gen1/ASPM、sniff 模式、SCO 雙向保活、AFH 頻道圖、耳麥本身（iPhone 錄音乾淨）。
- **硬證據:** btmon 顯示 SCO 封包 1333/10s **一個不少**地到達主機；但開啟 Erroneous Data Reporting (`hcitool cmd 0x03 0x005B 01`) 後控制器標記 **65% 封包 pkt_status=1（資料損壞）**；payload 的 mSBC H2 標頭有 1–3 bit 隨機錯誤、SBC CRC 失敗。即此 CYW43455 ↔ 耳麥鏈路的 **EDR π/4-DQPSK (2-EV3)** 封包位元錯誤率過高，mSBC 只能走 2-EV3，解碼失敗即補零。
- **解法:** `deploy/wireplumber.conf.d/51-bluez-cvsd.conf` → `bluez5.enable-msbc = false`，HFP 固定 **CVSD（基本速率 GFSK EV3，8kHz）**。profile 名稱仍為 `headset-head-unit`，`voice_pipeline.ensure_bluetooth_recording_ready()` 不需修改。實測零值降至 2–20%，逐字稿恢復可讀。
- **注意:** `hcitool rssi` 對 BR/EDR 回傳的是相對黃金接收範圍的差值，不是 dBm；此板子回報值不隨距離變化，不可作為訊號強度依據。
- **殘餘限制:** CVSD 下仍有 10–20% 封包 `pkt_status=2`（無資料）→ 零值空洞最長可達 1s。這是該射頻鏈路的物理上限；要再改善只能換射頻路徑（USB 藍牙 dongle）或換耳麥。
- **除錯工具:** `tools/pi_scostat` 系列腳本（btsnoop 解析 H2 標頭/CRC/旗標）、`/tmp/analyze.py`（零值統計）。

### ⚠️ [重點九] 逐字稿品質量測與潤稿流程 (2026-11-12 實測，細節見 `claude_context/BIG_CHANGE_STATUS.md`)
- **看 `cer_num` 不要只看 `cer`:** fixture 參考稿數字寫國字（十月十一日、一千五百台），ASR 寫阿拉伯數字，舊 `cer` 有 3/4 以上是寫法差異。`tools/e2e/scoring.cer_num` 用 cn2an 統一數字後再算（Pi 要 `pip install --user --break-system-packages cn2an==0.5.24`）。
- **潤稿流程（`transcript_polish.polish_transcript`）:** 每段依序 → 會議詞彙（`apply_glossary`，使用者在網頁填的人名／公司／產品，同音就換）→ MacBERT4CSC（`PI5_POLISH_PRE_CSC=0` 可關）→ LLM（修同音字 CPU qwen2.5:3b／重新潤稿 Hailo）→ `accept_homophone_edits` 只收同音字與 1 字補字（對齊用 `edit_opcodes`）。
- **程式裡不放測試詞表:** 專有名詞只來自使用者輸入的會議詞彙；`hailo_whisper/engine.fix_meeting_terms` 保留但不再往裡加測試資料的詞。
- **實驗選法:** 先在實錄 5 分／第二次錄／10 分選，再用新錄 10／30（／60）分確認；確認不過或只是持平但更慢就不採用（例：LLM 提示詞帶詞彙，慢 30% 又沒變好）。
- **高精度逐字稿結果**存在 `/dev/shm/localnote_state/refine_last.json`（RAM 磁碟），服務重啟後還在。
- **會後自動快修（2026-11-13，f4ab061）:** 高精度逐字稿完成後自動跑會議詞彙＋MacBERT（`transcript_polish.quick_fix`，`PI5_REFINE_QUICK_FIX=0` 可關）；`/api/refine` 的 `transcript` 是修正稿、`transcript_raw` 是原稿。**量測「原稿 → 潤稿」一律從 `transcript_raw` 起算**。會議詞彙存在盒子上（`GET／POST /api/glossary`，`/dev/shm/localnote_state/glossary.txt`）。
- **會議詞彙也用在紀要（2026-11-13，33c673c）:** `meeting_glossary.apply_to_text` 在紀要前套到即時稿（錄音中預先整理只套當段，整份 60 分要 0.3 s，錄音中不可每 10 秒整份重算）。
- **即時稿可選 SenseVoice（2026-11-13，4a462bc）:** 網頁開關＋`/api/config/live_asr`；`sv_worker` 子行程綁 CPU 2、3。藍牙收音時預設仍用 Hailo Whisper（`PI5_LIVE_SV_ON_BT=1` 放行，夜間量測用）。GS3 實測 cer_num 0.12–0.16 → 0.016–0.031。e2e 用 `stt_sv_ratio` 取代 `stt_npu_ratio`。
- **高精度稿辨識切段（2026-11-13，e19a919）:** 辨識在停頓處切 4–9.5 s 整段做（與即時稿相同），字依時間分回 VAD 句子給分說話人；VAD 句子（約 3 s）上下文太短，cer_num 0.05 → 0.03–0.04。`PI5_REFINE_ASR_SEGMENT=vad` 切回。
- **Windows pytest:** 預設暫存資料夾壞掉時，加 `--basetemp=.cc_scratch\pt_tmp_<時間>`；`tests/test_bt_link_stats.py` 要 fcntl，Windows 上加 `--ignore`。
- **PC → Pi 傳大檔:** scp 原樣傳 7 MB tar 會卡住，加 `-C`（壓縮）約 1 分鐘傳完。

---

## 5. 目錄與模組結構對照 (Module Directory Mapping)

- `code_dispatcher/`: FastAPI 後端 (`main.py`)、語音串流核心 (`voice_streaming.py`)、音訊記憶體緩衝區 (`voice_memory.py`)、LLM 後端選擇層 (`llm_backend.py`)、藍牙管理 (`bluetooth_manager.py`) 與前端儀表板 (`ui.html`)。
- `models/`: Ollama 口譯模型定義檔 (`Modelfile.qwen2.5-3b-opt`)、自動預熱腳本 (`setup_models.sh`) 與模型 Manifests 清單。
- `gpio_driver/`: 樹莓派 5 實體微動按鍵與雙色 LED 狀態指示驅動程式 (`key_led_driver.py`)。
- `telegram_agent/`: Telegram 語音助理 (`agent.py`)、無螢幕藍牙配對管理模組 (`bluetooth_manager.py`) 與自我進化引擎。
- `deploy/`: 樹莓派系統層設定檔（WirePlumber CVSD 強制、systemd 日誌 drop-in），安裝方式見各檔案開頭註解。
- `hotspot.md`: 戶外獨立熱點方案與 nftables 防火牆封包隔離設定指引。
- `todo_tasks.md` & `SPEC.md`: 系統工程規格文件與 30 項模組改良任務追蹤清單。
