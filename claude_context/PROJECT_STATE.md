# PROJECT_STATE.md - 專案即時狀態、架構與硬體實測記憶 (Project & Hardware State)

本文件彙整 `F:\14_prj_raspi5_localnote_asia` 專案之硬體環境、資料流架構與實機驗證過的 **8 大關鍵技術決策与避坑記憶**。所有項目皆經樹莓派 5 實機量測證實。

---

## 1. 樹莓派 5 硬體與網路環境 (Raspberry Pi 5 Environment)

- **硬體規格：**
  - `raspi678`: Raspberry Pi 5 (8GB RAM) + Hailo-10H AI HAT+ NPU
  - `raspi543`: Raspberry Pi 5 (16GB RAM) + Hailo-10H AI HAT+ NPU (Debian 13 Trixie, Kernel 6.18.50, `hailo1x_pci` DKMS)
- **網路位址：**
  - `raspi678` 家用 Wi-Fi (STA): `192.168.50.228` (主力 E2E 與聲學實測機)
  - `raspi543` 家用 Wi-Fi (STA): `192.168.50.229` (Uvicorn 監聽 Port 80，由 `pi5-port8000-proxy.service` 轉發 8000)
  - 戶外獨立熱點模式 (AP Mode): `10.20.0.1` (SSID: `raspi543_AI`, Web UI: `http://10.20.0.1:8000/`)
- **SSH 認證與路徑：**
  - 帳號: `pi`
  - 私鑰: `C:\Users\Andrew\.ssh\id_rsa_pi5`
  - 遠端主程式目錄: `/home/pi/code_dispatcher/`
  - 遠端 RAM-Disk 音訊快取: `/dev/shm/audio_cache/`
  - 遠端 E2E 測試資料目錄: `/home/pi/ln_e2e/data/`
- **核心 Systemd 服務：**
  - `pi5-dispatcher-api.service` (FastAPI 主服務)

---

## 2. 系統端到端資料流架構 (End-to-End Architecture)

```mermaid
flowchart LR
    subgraph Input["音訊輸入層 (Audio Input)"]
        BT["藍牙耳麥 HFP CVSD 8kHz<br/>或 USB Mic / Null-Sink"]
        PW["PipeWire + WirePlumber<br/>(51-bluez-cvsd.conf)"]
        FF["FFmpeg Segment 切片<br/>(6s/chunk + 80~7600Hz 帶通)"]
    end

    subgraphPre["前處理層 (/dev/shm RAM-Disk)"]
        ZS["ZeroSplicer (audio_splice.py)<br/>剪除封包丟失靜音空洞"]
        DC["Declicker (audio_declick.py)<br/>消除跳變毛刺"]
    end

    subgraph NPU["Hailo-10H NPU / CPU 推論層 (npu_share.py 協調)"]
        STT["Hailo Whisper STT 子行程<br/>(stt_worker.py / whisper_engine.py)"]
        CLEAN["同音錯字與幻覺清理<br/>(summary_utils.py / stt_segment_clean)"]
        LLM["LLM 雙語口譯與會議紀要<br/>(llm_backend.py: Hailo qwen3:1.7b / CPU qwen2.5:3b-opt)"]
    end

    subgraph Output["輸出與評估層 (UI & E2E)"]
        UI["Web UI (ui.html)<br/>即時轉錄 + 雙語翻譯 + 紀要"]
        SCORE["E2E 自動評分 (scoring.py)<br/>CER / 事實召回 / Recap / 議題覆蓋"]
    end

    BT --> PW --> FF --> ZS --> DC --> STT --> CLEAN --> LLM --> UI
    CLEAN --> SCORE
    LLM --> SCORE
```

---

## 3. 八大關鍵架構決策與避坑記憶 (Critical Architectural Gotchas)

### ⚠️ [記憶 1] 藍牙 UART `/dev/ttyAMA0` 零爭搶原則 (Zero-Contention)
- **物理限制：** Pi 5 藍牙晶片共用單一硬體 UART (`/dev/ttyAMA0`)，SCO 語音通道每 7.5ms 傳輸一幀。
- **嚴格保護：**
  1. 錄音中 (`is_recording == True`) **禁止**啟動 CPU 矩陣密集運算，亦**禁止**呼叫 `hcitool lq`、`hcitool rssi` 或高頻 `bluetoothctl info`。
  2. `voice_streaming.py` 設有 `is_any_recording_active()` 全域守衛；`bt_link_stats.py` 採用被動讀取或非錄音時段查詢。

### ⚠️ [記憶 2] 藍牙 mSBC (EDR 2-EV3) 位元錯誤根因與強制 CVSD (2026-10-22 實測結案)
- **實測真相：** CYW43455 與耳麥間的 EDR π/4-DQPSK (2-EV3) 鏈路有高達 65% 封包發生 1~3 bit 隨機錯誤，導致 mSBC H2 標頭/CRC 驗證失敗而補零（20~70% 靜音空洞）。
- **最終解法：** 於 `deploy/wireplumber.conf.d/51-bluez-cvsd.conf` 設定 `bluez5.enable-msbc = false`，強制採用 **CVSD（基本速率 GFSK EV3，8kHz）**，並搭配 `audio_splice.py` (`ZeroSplicer`) 自動剪除殘餘的短暫 `pkt_status=2` 靜音空洞，搭配 `audio_declick.py` 消除接縫跳變。

### ⚠️ [記憶 3] 瞬態平滑帶通濾波與零磁碟寫入 (Bandpass & Zero-Disk I/O)
- FFmpeg 固定套用 `-af "highpass=f=80,lowpass=f=7600"`。
- 音訊切片與合併全程在 `/dev/shm/audio_cache/` (RAM-Disk) 完成，實現 **0 Flash Wear**。

### ⚠️ [記憶 4] Hailo-10H NPU 共享與行程隔離 (`npu_share.py` + `stt_worker.py`)
- Hailo-10H 同一時間僅允許單一行程持有 VDevice（或需協調 `hailo-ollama` 與 `hailo_whisper`）。
- `stt_worker.py` 將 Hailo Whisper 封裝為獨立子行程，透過 `npu_share.py` 控制暫停/釋放 (`pause` / `release`)，確保 STT 與 LLM 切換時 **`hailo_busy_errors == 0`** 且 **`stt_npu_ratio >= 0.95`**。

### ⚠️ [記憶 5] LLM 雙後端自動切換與 `hailo-ollama` (0.5.1) API 陷阱 (`llm_backend.py`)
- 統一透過 `code_dispatcher/llm_backend.py` 的 `chat_complete / iter_chat_stream / achat_complete / aiter_chat_stream` 呼叫，**嚴禁直接 `requests.post` 到 11434**。
- 優先使用 `hailo-ollama` (`127.0.0.1:11435`, 模型 `qwen3:1.7b`，CPU 零占用)，失敗自動退避至 CPU Ollama (`127.0.0.1:11434`, `qwen2.5:3b-opt`)。
- **`hailo-ollama` 必知陷阱：**
  1. 僅 `/api/chat` 支援 `system` 訊息（`/api/generate` 會忽略 `system`）。
  2. `keep_alive` 必須為整數或省略（傳 `"24h"` 字串會回 HTTP 500）。
  3. Prompt 若含原始 `\n`、`\t`、`\` 會觸發 HTTP 500 `Failed to render prompt (status=8)`，已由 `llm_backend._sanitize_for_hailo()` 自動跳脫。

### ⚠️ [記憶 6] 藍牙 BR/EDR 專掃與單一 PTY 會話配對 (`bluetooth_manager.py`)
- HFP 耳麥走傳統藍牙 BR/EDR，掃描必須用 `scan bredr` 并過濾未配對的 `(random)` BLE 分身。
- BlueZ 在結束 discovery 後會立即清除暫存裝置，因此 `scan → pair → trust → connect` 必須在同一個 `BluetoothctlSession` (PTY 驅動) 內完成，且 `pair` 成功後才可 `trust`。

### ⚠️ [記憶 7] 中英雙語會議紀要結構化與結尾 Recap 保底機制 (`summary_utils.py` / `meeting_minutes.py`)
- **語言自適應：** 中文會議產出中文紀要（`## 重點摘要` / `## 待辦事項` / `## 決議事項`），英文會議產出英文紀要（`## Summary` / `## Action Items` / `## Decisions`）。
- **Web UI 加分項卡片：** 支援 `Translate to Mandarin` 與 `Translate to English` 雙向翻譯紀要，並保留「在耳麥念出來 (TTS Playback)」功能。
- **Recap 決議與待辦精準抽離：**
  - 會議結尾常有口頭總結（Recap），`summary_utils.py` 會自動將結尾 Recap 的決議 (Decisions) 與待辦 (Action Items / Todos) 補齊至對應區塊，並嚴格執行**去重 (Deduplication, `summary_duplicate_lines_max == 0`)**。
  - 待辦事項負責人 (Owner) 必須符合人名或部門單位特徵；截斷標題（如 `## 要`）自動正規化為摘要段落。

### ⚠️ [記憶 8] 聲學實測 (`speaker_selftest.py`) 的 STT 同音錯字校正表
- 透過夜間多輪 3/10/30 分鐘喇叭→藍牙耳麥實測（`night8_*`, `night9_*`），已在 `summary_utils.py` 與 `whisper_engine.py` 建立完整的 CVSD 8kHz 常見同音訛誤校正（如人名「吳副理」、職稱、數字日期、「決議是/決意施」、「電源供應器/電源-in器」、「報名/名額」等），確保聲學路徑下的 `transcript_fact_recall >= 0.6` 與 `summary_recap_recall >= 0.5`。

---

## 4. 關鍵目錄與檔案映射 (Key File Map)

| 路徑 | 職責說明 |
|---|---|
| [code_dispatcher/main.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/main.py) | FastAPI 路由、錄音控制、SSE 串流與靜態檔案服務 |
| [code_dispatcher/voice_pipeline.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/voice_pipeline.py) | 錄音主流程、藍牙就緒檢查、分段 STT 與後處理調度 |
| [code_dispatcher/summary_utils.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/summary_utils.py) | STT 錯字清理、中英紀要解析、去重、Recap 決議/待辦合併核心邏輯 |
| [code_dispatcher/meeting_minutes.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/meeting_minutes.py) | 長短會議分段摘要 Prompt 與 LLM 呼叫封裝 |
| [code_dispatcher/llm_backend.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/llm_backend.py) | Hailo-Ollama (`:11435`) 與 CPU Ollama (`:11434`) 統一抽象層 |
| [code_dispatcher/stt_worker.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/stt_worker.py) | 獨立子行程 Hailo Whisper STT Worker |
| [code_dispatcher/npu_share.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/npu_share.py) | Hailo NPU 資源鎖與 STT/LLM 交握控制 |
| [code_dispatcher/audio_splice.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/audio_splice.py) | `ZeroSplicer` 數位零值空洞偵測與平滑拼接 |
| [code_dispatcher/audio_declick.py](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/audio_declick.py) | 藍牙封包邊界瞬態暴音 (Click) 抑制 |
| [code_dispatcher/ui.html](file:///f:/14_prj_raspi5_localnote_asia/code_dispatcher/ui.html) | **唯一前端原始檔**（部署時自動複製為 `ui_client.html` 與 `static/index.html`） |
| [hailo_whisper/whisper_engine.py](file:///f:/14_prj_raspi5_localnote_asia/hailo_whisper/whisper_engine.py) | Hailo-10H Whisper 編解碼推論與後處理 |
| [tools/e2e/scoring.py](file:///f:/14_prj_raspi5_localnote_asia/tools/e2e/scoring.py) | E2E 品質評分純函式（CER、事實召回、紀要結構與覆蓋率） |

