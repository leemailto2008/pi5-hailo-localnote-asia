# API_AND_TEST_REFERENCE.md - API 端點、自動化測試套件與評分門檻參考 (API, Test Suite & Scoring Reference)

本文件詳細列出 LocalNote 後端 API 端點、離線單元測試 (`pytest`)、線上全流程 E2E 測試 (`tools/e2e/`) 以及自動評分門檻 (`thresholds.json`)。

---

## 1. 核心 HTTP / WebSocket API 端點參考 (FastAPI Endpoints)

| 方法 | 路徑 | 說明 |
|---|---|---|
| `GET` | `/health` | 健康檢查，回傳 `status`、`llm_backend` (`hailo` 或 `cpu`)、NPU 狀態 |
| `GET` | `/api/status` | 查詢當前錄音/推論狀態 (`idle` / `recording` / `processing`)、當前 `job` ID、即時逐字稿與紀要 |
| `POST` | `/api/record` | 啟動錄音（支援參數：`duration` 秒數上限 14400s、`bypass_summary: false`） |
| `POST` | `/api/stop` | 停止當前錄音並觸發尾端 STT 與會議紀要生成 |
| `GET` | `/api/last_meeting` | 讀取最近一次完成的會議完整記錄（逐字稿、紀要、雙語翻譯、音訊統計） |
| `POST` | `/api/translate_summary` | 將會議紀要翻譯為指定語言（`Mandarin` / `English`） |
| `GET` | `/api/bt/status` | 查詢藍牙連線狀態與電量（錄音中自動回傳記憶體快取，零 HCI 爭搶） |
| `GET` | `/api/bt/trusted` | 取得已配對/受信任耳麥清單與各裝置 `auto_connect` 狀態 |
| `POST` | `/api/bt/trusted/auto_connect` | 切換指定耳麥 MAC 的自動重連開關 `{"mac": "...", "auto_connect": true}` |
| `WS` | `/ws/vu` | WebSocket 即時音量表 (VU Meter) 與狀態推播 |

---

## 2. 離線單元測試套件 (Offline Unit Tests — `tests/`)

目前共有 **13 個測試模組、超過 515 項測試案例**：

| 測試檔案 | 測試範圍 |
|---|---|
| [tests/test_summary_utils.py](file:///f:/13_prj_raspi5_localnote/tests/test_summary_utils.py) | 中英紀要解析、標題正規化 (`## 要` → 摘要)、待辦表格抽取、負責人驗證、結尾 Recap 合併與去重 |
| [tests/test_whisper_engine.py](file:///f:/13_prj_raspi5_localnote/tests/test_whisper_engine.py) | STT 同音錯字修正（如「決意施→決議是」「電源-in器→電源供應器」「吳副理」「報名/名額」等） |
| [tests/test_stt_segment_clean.py](file:///f:/13_prj_raspi5_localnote/tests/test_stt_segment_clean.py) | 分段逐字稿幻覺過濾、重複贅詞（目前/已經/我們/然後）清理 |
| [tests/test_audio_splice.py](file:///f:/13_prj_raspi5_localnote/tests/test_audio_splice.py) | `ZeroSplicer` 封包丟失零值空洞偵測與無縫剪接 |
| [tests/test_audio_declick.py](file:///f:/13_prj_raspi5_localnote/tests/test_audio_declick.py) | 藍牙邊界瞬態暴音 (Click) 偵測與平滑修復 |
| [tests/test_scoring.py](file:///f:/13_prj_raspi5_localnote/tests/test_scoring.py) | E2E 評分演算法（CER、Fact Recall、Recap Recall、Topic Coverage、中英雙語標題相容） |
| [tests/test_fixtures.py](file:///f:/13_prj_raspi5_localnote/tests/test_fixtures.py) | `tools/e2e/fixtures/meeting_*min.json` 結構與時間軸一致性驗證 |
| [tests/test_llm_stream.py](file:///f:/13_prj_raspi5_localnote/tests/test_llm_stream.py) | `llm_backend.py` 串流輸出、`hailo-ollama` 字串跳脫與 CPU Fallback |
| [tests/test_npu_share.py](file:///f:/13_prj_raspi5_localnote/tests/test_npu_share.py) | Hailo NPU 鎖定、STT Worker 暫停與釋放（需 Linux POSIX `select`） |
| [tests/test_stt_worker.py](file:///f:/13_prj_raspi5_localnote/tests/test_stt_worker.py) | STT 子行程通訊與崩潰自動重啟（需 Linux POSIX `select`） |
| [tests/test_bt_link_stats.py](file:///f:/13_prj_raspi5_localnote/tests/test_bt_link_stats.py) | 藍牙鏈路品質統計（需 Linux `fcntl`） |
| [tests/test_last_meeting.py](file:///f:/13_prj_raspi5_localnote/tests/test_last_meeting.py) | 會議記錄持久化與讀取 |
| [tests/test_mic_detection.py](file:///f:/13_prj_raspi5_localnote/tests/test_mic_detection.py) | 音訊輸入源自動偵測與優先序 |

**執行指令：**
- **Linux / `claude-code-vm` / Raspberry Pi（全套 530+ 項測試）：**
  ```bash
  python3 -m pytest -q tests
  ```
- **Windows 本機 PowerShell（513 項跨平台測試）：**
  ```powershell
  C:\Python313\python.exe -m pytest --ignore=tests/test_bt_link_stats.py --ignore=tests/test_npu_share.py --ignore=tests/test_stt_worker.py -q tests
  ```

---

## 3. 線上全流程 E2E / HIL 自測系統 (`tools/e2e/`)

### A. 數位直送 E2E（Null-Sink 注入，24 小時皆可跑，不出聲）
透過 `/dev/shm/ln_force_source` 將預先合成的測試會議音訊直接注入 PipeWire Null-Sink，完整測試「錄音 → ZeroSplicer → Hailo Whisper STT → LLM 會議紀要 → 自動評分」：

```bash
# 在 Pi (192.168.50.228) 上執行：
# 1. 快速回歸測試 (1 分鐘 + 3 分鐘，約 10 分鐘完成)
python3 tools/e2e/run_suite.py --minutes 1 3

# 2. 標準完整測試 (1, 3, 5, 10, 15, 30 分鐘，約 2 小時完成)
python3 tools/e2e/run_suite.py --minutes 1 3 5 10 15 30

# 3. 長時間壓力測試 (45, 60, 90, 120, 180, 240 分鐘)
python3 tools/e2e/run_suite.py --minutes 45 60

# 4. 僅測錄音 + STT (跳過 LLM 紀要)
python3 tools/e2e/run_suite.py --minutes 5 --allow-bypass
```

### B. 英文會議 E2E 測試 (`en_short` / `en_long`)
- 已建立美式英文三聲線合成之英文會議測試集：
  - `en_short` (127 秒，4 個議題 + 口頭總結)
  - `en_long` (339 秒，8 個議題 + 口頭總結)
- `scoring.py` 原生支援英文紀要標題（`Summary` / `Action Items` / `Decisions`）與不分大小寫之事實比對。

### C. 實境聲學自測 (`speaker_selftest.py` — ⚠️ 僅限夜間 19:00–07:00 執行)
在接有喇叭的電腦上播放測試會議 WAV，由藍牙耳麥收音後透過藍牙傳入 Pi：
```powershell
python tools/e2e/speaker_selftest.py --pi http://192.168.50.228 --wav <path_to_meeting_wav>
```

---

## 4. E2E 品質與系統健康門檻 (`tools/e2e/thresholds.json`)

每次 E2E 測試必須同時通過以下所有指標（任一未過 `run_suite.py` 回傳 `exit 1`）：

| 指標名稱 (Metric) | 門檻值 (Threshold) | 物理意義 |
|---|---|---|
| `transcript_cer_max` | `<= 0.40` | 逐字稿字元錯誤率 (Character Error Rate) 上限 |
| `transcript_fact_recall_min` | `>= 0.60` | 逐字稿內建關鍵事實召回率下限 |
| `summary_required` | `true` | 必須成功產出結構化會議紀要 |
| `summary_duplicate_lines_max` | `== 0` | 紀要內重複列數必須為 **0**（零重複容忍） |
| `summary_recap_recall_min` | `>= 0.50` | 會議結尾總結 (Recap) 之決議與待辦召回率下限 |
| `summary_topic_coverage_min` | `>= 0.50` | 會議各議題於紀要中之覆蓋率下限 |
| `summary_latency_base_s` | `120s + 12s/min` | 紀要生成允許最大延遲 |
| `stt_npu_ratio_min` | `>= 0.95` | STT 分段使用 Hailo NPU 加速之比例（>= 95%） |
| `hailo_busy_errors_max` | `== 0` | Hailo VDevice 資源衝突錯誤次數必須為 **0** |
| `stt_tail_wait_max_s` | `<= 10s` (30m+ 為 `15s`) | 錄音結束後等待最後一段 STT 完成之秒數上限 |
| `rec_cpu_avg_max` | `<= 15%` | 錄音期間平均 CPU 佔用率上限（確保零爭搶） |
| `cpu_temp_max` | `<= 75°C` | 樹莓派 CPU 最高溫度上限 |
| `ram_peak_mb_max` | `<= 3500 MB` | 記憶體峰值上限 |
| `swap_growth_mb_max` | `<= 64 MB` | Swap 增長量上限（防記憶體洩漏） |
| `api_max_gap_s_max` | `<= 8s` | `/api/status` 輪詢最大無回應間隙上限 |

