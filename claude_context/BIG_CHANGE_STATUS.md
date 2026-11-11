# BIG_CHANGE_STATUS.md — 大改三項循環狀態（2026-11-10 起）

（已過期的互動鎖已於 2026-11-10 23:24 移除）


## 狀態：三項 DONE（2026-11-10 19:40）。後續改善：#2–#4 已完成；#1 阻塞（耳麥未連線，見 2026-11-10 23:24、2026-11-11 00:26、01:24 排程輪次）；#5 待使用者決定。排程停用被權限拒絕，排程仍啟用（見排程輪次紀錄）

## 目標與順序（使用者指定）
1. 潤稿區（待辦 #11）→ 2. SenseVoice 比較（ASR 品質與效能）→ 3. CAM++ 分說話人

## 完成定義（DONE）
三項都要符合：
- 已實作；或已有結論（採用／不採用）與理由。
- 以 tools/e2e/fixtures 合成資料量測，數值寫入下方「量測紀錄」。
- 若改變 app 行為：已 commit、依 tools/ci/deploy_on_pi.sh 部署、健康檢查通過、功能在 raspi678 上實測。

## 結論

### 1 潤稿區 — DONE
- commit：c00999d → 1b532e9 → c7981b6 → 0ee3ba5 → 098beda；部署 raspi678（最後一次備份 .deploy_backup/20261110_191846）。
- 架構：POST /api/polish 啟動背景工作、GET 查進度（single_job.SingleJob）；錄音中 409；錄音一開始在段落之間停下。
  Pi 實測：idle → running(0/1) → 第二次 POST 409 → 錯誤 mode／空字串 400 → done。
- fix（修同音字與漏字）結論：小模型在真實 ASR 文字上幾乎沒有修正能力，保留功能但不再投入。
  實錄 60 分鐘會議 22 段：Hailo 正式 prompt 套用 9 筆（有益 2、有害 3），CER 0.2826 → 0.2820；
  通用 prompt 在 Hailo 15 筆（有益 1、有害 4）CER 0.2829、在 CPU 48 筆（有益 6、有害 8）CER 0.2831。
  已擋下的有害類型：繁轉簡（OpenCC s2twp）、刪字、相似度過低的改寫、補字重複補。
- rewrite（整段重新潤稿）：輸出先轉台灣繁體；阿拉伯數字（日期、金額、數量）與原文不同就整段保留原文；
  逾時依輸出長度放寬。Pi 實測單段 11.8 s，數字保留（10月11日、100臺）。
  限制：中文數字不檢查；改寫品質普通（例：「市跑」改成「上架跑」而非「試跑」）。

### 2 SenseVoice — DONE（採用為「錄音後高精度逐字稿」，錄音中的即時逐字稿仍用 Hailo Whisper）
- 品質（同一套 tools/e2e/scoring.py CER；「不計數字」= 去掉阿拉伯數字與中文數字後的 CER，排除 ITN 格式差異）：
  | 音訊 | 引擎 | CER | 不計數字 | 事實召回 |
  |---|---|---|---|---|
  | 10 分鐘，e2e 數位錄音（m_1794307922） | Hailo Whisper 即時（目前版本） | 0.2265 | 0.127 | 0.871 |
  | 同一錄音檔 | SenseVoice＋CAM++（/api/refine） | 0.184 | 0.057 | 0.879 |
  | 10 分鐘 WAV | SenseVoice（x86） | 0.177 | 0.047 | 0.893 |
  | 10 分鐘 WAV | SenseVoice（ITN 關） | 0.0295 | 0.035 | 0.879 |
  5／15／30 分鐘 WAV：CER 0.166／0.188／0.193，事實召回 0.866／0.899／0.922。
- 效能（Pi 5 CPU）：RTF 0.048（4 執行緒）／0.056（2 執行緒），10 分鐘 30 s；RSS 約 620 MB。
- 為什麼不取代即時逐字稿：錄音中不能跑 CPU 推論（CLAUDE.md 重點一）；Hailo 版是 CPU 零占用。

### 3 CAM++ 分說話人 — DONE
- sherpa-onnx：pyannote-3.0 分段＋3D-Speaker CAM++ zh-cn common 嵌入，FastClustering threshold 0.7。
- 逐句歸屬正確率（fixture timeline 的 voice 為真值，4 人）：10 分 97.8%、15 分 91.9%（調參用）；5 分 89.1%、30 分 90.7%（未調參驗證）。
  Pi 上 e2e 數位錄音 10 分鐘：找到 5 人，逐句 86.7%。錯誤集中在兩個相近的女聲 TTS。
- 效能（Pi 5 CPU 4 執行緒）：RTF 0.235（10 分鐘 140 s）。60 分鐘：見量測紀錄。
- 上線：code_dispatcher/refine_transcript.py、POST/GET /api/refine、前端「高精度逐字稿＋分說話人」面板（按鈕觸發）。
  子行程執行（nice 10）：處理中 /api/status 延遲最大 10 ms（執行緒版會卡住 API 約 2 分鐘）；
  開始錄音後 2 秒內（量測的輪詢間隔）子行程就已結束（Pi 實測，e2e 1 分鐘錄音）。
- Pi 安裝：tools/ci/setup_sherpa_models.sh（sherpa-onnx 2.0.1 裝在 pi 使用者 site-packages；模型 /home/pi/models/sherpa，5 檔 md5 已驗）。

## 後續改善（排程循環接著做，一次做一項，照常 commit／部署／實測）
1. 夜間聲學實測（19:00–07:00，依 CLAUDE.md 流程：開耳麥自動連線、確認 PC 喇叭、看前 30 秒逐字稿）：
   用 tools/e2e/speaker_selftest.py 播 10 分鐘會議 → 藍牙耳麥錄音 → /api/refine，比較 Hailo 即時與 SenseVoice 的 CER、分說話人正確率。
   這是 SenseVoice 在真實藍牙音訊（CVSD 8 kHz、有掉包）上的表現，目前只有數位音訊的數據。
2. 長會議：Pi 上用 python3 -m refine_transcript 跑 120／240 分鐘 WAV（.cc_scratch/sv/run_with_rss.py 量峰值記憶體），確認不會 OOM。
3. 句子合併：VAD 切在句中，SenseVoice 每段加「。」（例：「不良率從5%。降到1%。」）。同一人、間隔很短的相鄰句，前句的「。」改「，」。先寫單測。
4. rewrite 實測（已完成 22:14，見量測紀錄）：實錄逐字稿 22 段跑 rewrite，記錄 fact_rejected_chunks、耗時。
5. 待使用者決定（不要自行實作）：錄音結束自動跑高精度逐字稿；紀要改用高精度逐字稿。

## 量測紀錄
- 2026-11-10 16:43 fix 3min（Pi）：chunks=2，elapsed 16.6 s，changes=0，err 0.0133 → 0.0133。
- 2026-11-10 16:52 rewrite 單段 585 字（Pi）：98.8 s，out 623 字。
- 2026-11-10 17:25 fix 3min 合成（Pi，Hailo qwen3:1.7b，.cc_scratch/exp_fix.py 同 noisy3 文本，5 組注入錯字）：baseline prompt 16.5 s，提出 0 筆，hits 0/5，err 0.0133 → 0.0133。
- 同上 v2 prompt（逐句檢查＋同音例）：196.9 s，提出 0 筆，hits 0/5，parse_fail 2（num_predict=300 內輸出大量 from==to 無效項，陣列被截斷），err 0.0133 → 0.0133。（此時互動 session 的實驗也在用 NPU，耗時受排隊影響。）
- 2026-11-10 17:16 1b532e9 部署（備份 .deploy_backup/20261110_171718）。POST /api/polish 冒煙測試 200，Hailo：1 筆修改（涼率→良率，正確），漏掉 李協里。
- 2026-11-10 17:22 CPU qwen2.5:3b-opt（含安全檢查），noisy3：baseline 39.3 s、0 筆；v2 109.6 s、7 筆（李協里→李協理 ×2 正確；誤改 4 筆），err 0.0133 → 0.0148。v2 prompt 含「協理、課長」等領域提示，貼近測試資料，不可用於正式版。
- 2026-11-10 17:26–18:47 實錄逐字稿實驗（Pi /tmp/real_exp.py；資料 .cc_scratch/real_asr.txt、.cc_scratch/sv/real_raw.jsonl；評估 .cc_scratch/sv/eval_real.py）：m_1794284740（meeting_60min 經藍牙錄音），ASR 12554 字、22 段，CER 0.2826。
  - prod_hailo：1542 s（每段約 67 s）；未過濾 17 筆有 12 筆是繁轉簡，CER 0.2854；加 s2twp 過濾 9 筆，CER 0.2820。
  - generic_cpu：1821 s；48 筆，有益 6、有害 8，CER 0.2831。
  - generic_hailo：1447 s；15 筆，有益 1、有害 4，CER 0.2829。
- 2026-11-10 17:55 SenseVoiceSmall int8（x86 2 核，.cc_scratch/sv/sv_eval.py）：10 分 CER 0.177、事實召回 0.893、RTF 0.057。ITN 關：CER 0.0295。5／15／30 分：0.166／0.188／0.193。
- 2026-11-10 18:10 CAM++（x86，.cc_scratch/sv/diar_eval.py）：zh-cn common、threshold 0.7：10 分 97.8%／15 分 91.9%／5 分 89.1%／30 分 90.7%；DER 0.20／0.28／0.29／0.24（DER 的漏判約 18%，多為句中停頓）。zh_en advanced 15 分 77.9%，不採用。
- 2026-11-10 18:47 Pi 5 CPU：SenseVoice 10 分 RTF 0.048（4 執行緒）／0.056（2 執行緒），RSS 620 MB；CAM++ 10 分 147 s（RTF 0.235），RSS 308 MB。
- 2026-11-10 18:53 Pi e2e 10 分鐘（目前版本 Hailo Whisper，數位注入，PASS）：CER 0.2265、不計數字 0.127、事實召回 0.871（10/31 舊版為 0.3135／0.234／0.786）。
- 2026-11-10 18:50 c7981b6..098beda 部署（備份 20261110_185011）；/api/polish 背景工作 Pi 實測通過。
- 2026-11-10 19:04 5755688 部署（備份 20261110_190436）；/api/refine 對 m_1794307922：170 s（辨識 28.8、分說話人 140.1），CER 0.184、不計數字 0.057，5 人、逐句 86.7%。執行緒版處理中 GET 逾時 30 s → 改子行程。
- 2026-11-10 19:10 327f47d 部署（備份 20261110_190959）：子行程版 169.9 s，處理中 /api/status 延遲最大 0.010 s（n=86）。
- 2026-11-10 19:14 中止測試：refine 辨識中開始 e2e 1 分鐘錄音 → 2 秒內 state=stopped、子行程結束；e2e 1 分 PASS。
- 2026-11-10 19:17 無頭瀏覽器（PC Playwright）測前端：按鈕觸發 1 分鐘會議 → 「完成：3 位說話人，錄音 75 秒，辨識 5.1 秒，分說話人 16.1 秒」；發現開頁顯示上一場結果 → 8161b38 修正（備份 20261110_191846）。
- 2026-11-10 19:20 推送 gitlab、origin：7a2661e..8161b38（9 個 commit）。
- 2026-11-10 19:20– Pi 60 分鐘 refine CLI（/home/pi/ln_e2e/data/meeting_60min.wav → /tmp/refine_60min.jsonl）：音訊 3691 s，辨識 168.6 s、分說話人 824.4 s（RTF 0.223），wall 995.1 s，峰值 RSS 1024 MB（未 OOM），692 句，分出 6 個說話人（真值 4 人，多出的 2 群在 timeline 上無對應句）。逐句歸屬正確率：timeline 行級 0.9547（530 行）、句子級 0.9653（692 句）；計算：.cc_scratch/sv/acc_refine.py（句子標籤版，與上方 diar_eval 的 turn 級口徑不完全相同）。

- 2026-11-10 21:33 240 分鐘 refine CLI（Pi，run_240.sh，meeting_240min.wav，音訊 14383 s，rc=0）：ASR 652.9 s、分說話人 3258.0 s，wall 3919.6 s（RTF 0.272），峰值 RSS 4644 MB（8 GB 機器，未 OOM），2647 句，hyp 8 人（真值 4 人）。逐行歸屬 0.9228（2047 行，未歸屬 0）、句子級 0.9403（2647 句），計算 .cc_scratch/sv/acc_refine.py + tools/e2e/fixtures/meeting_240min.json。8 群中 4 群對應真值，其餘 4 群未對應（過度分群）；60 分鐘為 6 群、0.9547／0.9653。未調參，僅記錄。
- 2026-11-10 21:33 句子合併離線重放（240 分鐘，.cc_scratch/sv/replay_merge_240.py）：句號 2683 → 2130（改 553 處），去標點後文字與舊版相同。
- 2026-11-10 21:35 122051e 部署（備份 .deploy_backup/20261110_213534；py_compile、健康檢查通過）。POST /api/refine 冒煙（最後一場 m_1794309254，音訊 75.3 s）：完成，22.5 s，3 位說話人；同一說話人短停頓已見逗號（例：「好，我們開始今天的週會，今天有幾個議題要討論。」）。/health 回 status=degraded、redis_connected=false（觀察）。本次部署只改 refine_transcript.py，與 redis 判定無關（推論，非已查證）；是否為既有狀態尚未查證。
- 2026-11-10 21:37 #4 rewrite 實測啟動（Pi，/tmp/rewrite_real_check.py，實錄 22 段 12554 字，/api/polish mode=rewrite）：結果（22:14 完成）：state=done，wall 2291.4 s（服務內 elapsed 2290.8 s，約每段 104 s），fact_rejected_chunks 5、rejected_chunks 0、failed_chunks 0，backend Hailo-10H NPU qwen3:1.7b，輸入 12554 字、輸出 12578 字。原始結果 Pi 上 /tmp/rewrite_real.json、日誌 /tmp/rewrite_real.log；只記錄上述數值，未與人工參考文字比對品質。

- 2026-11-11 09:03 使用者手動測試（耳麥已重新連線，5 分鐘 Podcast 內容，m_1794358697）：紀要 09:03:23 開始用 NPU，09:03:54 按「修同音字與漏字」→ 潤稿請求在 hailo-ollama 排在紀要後面，120 s 逾時；hailo-ollama 不取消已送出的請求，重試又排在被放棄的請求後面，2 段共 300 s。日誌只印「failed (attempt 1):」。
  - 修正 bedd4e3（部署 09:11，備份 .deploy_backup/20261111_091108，LN_DEPLOY_FORCE=1：使用者的會議在 15 分鐘內，部署腳本預設擋下）：錄音中或 processing 時 POST /api/polish、/api/refine 回 409；前端停用按鈕並顯示原因；LLM 失敗日誌印例外類型。
  - Pi 實測（09:16 e2e 1 分鐘，數位注入，PASS）：processing 期間 POST /api/polish、/api/refine 皆 409「會議紀要還在生成，完成後再試」；PC Playwright 看到 recording／processing 時按鈕停用、狀態列顯示原因，done 後恢復。
  - 同一次潤稿結果（Podcast，無真值）：7 筆修改，至少 3 筆明顯有害（「節目開始前讓我們」→「節目前讓讓我們」、「主客觀條」→「主客觀」、「我們就組成了」→「我們就這樣」）。離線比較「只允許同長度換字與補字」的過濾（.cc_scratch/eval_real.py s2t+struct）：60 分鐘實錄三組有害 15 → 7 筆，但有益 10 → 4 筆、淨編輯距離 +2 → +7，沒有比現行好，未採用。fix 模式維持「效果接近零」的結論。

- 2026-11-11 英文會議：14473f1 高精度逐字稿英文句子改用空格接（原本接成「meeting.，We have」），中英混排仍用「，」；新增 2 個單測。
- 2026-11-11 SenseVoice 語言設定（.cc_scratch/sv/sv_eval.py --language，x86）：
  | 音訊 | zh | en | auto |
  |---|---|---|---|
  | 中文合成會議 5／10／15 分 CER | 0.166／0.177／0.1875 | — | 0.166／0.179／0.1858 |
  | 英文 TTS en_short CER | 0.028 | 0.032 | 0.030 |
  | 英文 TTS en_long CER | 0.073 | 0.074 | 0.075 |
  .229 真實英文新聞（夾一段中文廣告，無真值）輸出的 CJK 字數：zh 1125、en 3、auto 1102。zh 把英文段辨成中文亂碼；en 把中文廣告辨成英文亂碼；auto 英文段正常、中文廣告正確。
  → 5fb7473：refine_transcript.ASR_LANGUAGE 預設 auto（環境變數 PI5_SENSEVOICE_LANGUAGE 可覆寫），新增單測；Windows pytest 563 passed。
  部署 raspi678（10:18，備份 .deploy_backup/20261111_101830，健康檢查通過）。Pi 實測 python3 -m refine_transcript meeting_en_short.wav（127 s 英文 TTS）：asr 7.2 s、diarize 26.1 s，3 位說話人，逐字稿 CJK 字 0（不含說話人標籤）、英文詞 257。
  部署注意：Windows 上 git archive 要加 -c core.autocrlf=false，否則 deploy_on_pi.sh 變 CRLF，在 set -euo pipefail 就失敗（rc=2，未安裝任何檔案）。
- 2026-11-11 raspi543（.229）更新到 14473f1，tools/ci/setup_sherpa_models.sh 直接從 HF／GitHub 下載模型（scp 239 MB 太慢，約 0.1 MB/s，已放棄）；/api/refine 回 unavailable=null（可用）。.229 給其他人測試，之後部署不加 LN_DEPLOY_FORCE。
- 2026-11-11 .228 接 USB 音訊 Plextone GS3（ALSA card 2；sink alsa_output.usb-GS3_GS3_20180508-00.analog-stereo，source alsa_input.usb-GS3_GS3_20180508-00.analog-stereo）：硬體 PCM 音量原本 0%，PipeWire sink 音量設 1.0 後 PCM 100%。GS3 喇叭播放、同時錄音的電平：藍牙耳麥 −39.7 dBFS、GS3 麥克風 −53 dBFS；示範錄音逐字稿只出現「×.」，已取消。
  - 10:06–10:26 多次播放（ffmpeg→pulse、pw-play、aplay plughw:2,0 44.1 kHz 直送），使用者現場都聽不到。數位端正常：pcm0p status RUNNING、hw_ptr 前進；sink monitor mean −26.4 dB／max −10.6 dB，與原檔相同。
  - ALSA 只有 PCM Playback Switch／Volume、Mic Capture Switch／Volume。USB ID 8888:1234（非正式廠商 ID）；核心警告「Unlikely big volume range (=999), cval->res is probably wrong」，PCM 原始值 0–999、Mic 0–3996。插上時預設 PCM 0、Mic 3932/3780，WirePlumber 隨即設為 999／3996。
  - 喇叭→GS3 麥克風自測：PCM {0,250,500,750,999} × Mic {0,1000,2000,3000,3996}，1 kHz 測試音全部偵測不到（1 kHz 相對鄰頻 −2.2～+1.1 dB）。Mic 0 為數位靜音；Mic 1000–3000 底噪都是 −76.7 dBFS（不隨增益變）。使用者敲麥克風、講話時峰值只到 −39／−45 dBFS。結論：類比輸入幾乎沒有訊號；喇叭端無法用麥克風自測。
  - 推測（未驗證）：兩支 3.5 mm 插頭插反，或插在 4 極孔；或 GS3 機身的喇叭／麥克風靜音鍵、音量轉盤（產品資料有，Pi 看不到）。已請使用者現場檢查。10:25:44 起循環播放語音最多 30 分鐘，麥克風每秒記錄於 Pi /tmp/gs3_meter_cont.log；停止：touch /dev/shm/gs3_stop 後 pkill -x pw-play。
  - 10:37 解決：使用者把 Pi 移到關門的小房間、調大 GS3 硬體音量、Pi 重開機。之後 1 kHz 相對鄰頻 +21.3 dB，麥克風 −23～−30 dBFS，15 秒錄音的 SenseVoice 逐字稿與正在播的會議內容一致。三個動作中是哪一個修好的未確定（推測硬體音量）。
  - 換 USB 口時 PipeWire 會把播放／錄音串流改接到預設裝置（藍牙耳麥）；自測腳本改用 pw-play／pw-record 加 node.dont-fallback／node.dont-reconnect。

### 2026-11-11 GS3 接進系統、聲學實測、ASR 比較、逐句分說話人（使用者 10:43 指示：GS3 白天也可整天測；SenseVoice／CAM++ 深入改良並與 Whisper 比較）
- 系統整合（6ba1c9d，部署 .228 10:58，備份 20261111_105806）：沒有藍牙耳麥時錄 USB 麥克風；偏好 bluetooth／usb 存 data/mic_preference.json；
  GET/POST /api/config/mic；前端「🎙️ 錄音麥克風」切換鈕（Playwright 實點來回切換正常）。
  正式路徑實測（不用 ln_force_source，偏好 usb）：log「偏好 USB 麥克風：alsa_input.usb-GS3…」，1 分鐘會議 CER 0.2458、事實召回 0.818；測完改回 bluetooth。
- e2e 聲學模式（a5a727e）：--play-sink／--source。GS3 聲學 e2e 全部門檻 PASS：
  | 會議 | Hailo 即時 CER／事實 | SenseVoice CER／事實 | 紀要回顧召回／議題覆蓋 | 紀要延遲 |
  |---|---|---|---|---|
  | 5 分（m_1794365242） | 0.2206／0.896 | 0.1812／0.881 | 1.0／1.0 | 129 s |
  | 10 分（m_1794367149） | 0.2555／0.807 | 0.1915／0.864 | 0.833／1.0 | 80 s |
  錄音相對原檔延遲 1.62–1.64 s（互相關估計，/home/pi/ln_e2e/acoustic_gs3/shift_fixture.py），說話人評分用平移後的 fixture。
- ASR 比較（5 分會議，Pi 5，compare_asr.py；faster-whisper 參數同 voice_pipeline 的 CPU 路徑，beam 5 另加）：
  | 引擎 | 乾淨 CER（不計數字） | GS3 聲學 CER（不計數字） | RTF |
  |---|---|---|---|
  | SenseVoice small int8 | 0.163（0.056） | 0.181（0.078） | 0.05 |
  | faster-whisper small int8 beam 5 | 0.178（0.083） | 0.182（0.083） | 0.65 |
  | faster-whisper small int8 beam 1 | 0.266（0.181） | 0.212（0.119） | 0.44 |
  | Hailo Whisper-Small 即時（NPU） | 0.2277（0.145）* | 0.221（0.144） | CPU 0 |
  *12:22 數位 e2e 5 分（/home/pi/ln_e2e/digital_1111/5min，PASS，紀要延遲 91.7 s）。「不計數字」去掉阿拉伯與中文數字，排除 ITN 格式差異
  （/home/pi/ln_e2e/acoustic_gs3/cer_table.py）。
  結論：SenseVoice 準確度最好（不計數字：乾淨 5.6% vs Whisper beam 5 8.3%、Hailo 即時 14.5%），速度快 9–13 倍；維持「錄音中 Hailo Whisper、錄音後 SenseVoice」。
- 分說話人改為逐句法（DIARIZE_METHOD=sentence）：每句（SenseVoice VAD 句子，≥ 1.0 s）算 CAM++ 嵌入、sherpa FastClustering 門檻 0.6；短句借時間上最近的長句。
  句子級正確率（一對一對應，.cc_scratch 外的 /home/pi/ln_e2e/sec_test、acoustic_gs3 腳本）：
  | 音訊 | pyannote（舊） | 逐句法 0.6／1.0 s |
  |---|---|---|
  | 合成 5／15／30 分（x86） | 86.4／76.4／92.9% | 100／100／100%（4 人） |
  | 合成 60 分（Pi） | 96.5%，6 人 | 100%，4 人（門檻 0.5 那輪；最終參數見下） |
  | GS3 實錄 5 分 | 90.0%，4 人 | 100%，4 人 |
  | GS3 實錄 10 分 | 84.1%，5 人 | 96.6%，5 人 |
  耗時（Pi）：5 分 5.4 s（pyannote 67 s）、10 分 10.6 s（139 s）、60 分 74 s（824 s）。
  門檻掃描：合成會議 0.65 起兩個相近女聲（HsiaoChen／HsiaoYu）併成一人；實錄 0.5 分成 8–12 人。0.6 是兩者都 ≥ 96% 的唯一值，邊界窄。
  其他嵌入模型（逐句法，同資料）：ERes2Net base 合成 ≤ 0.7 正確、實錄 10 分需 ≥ 0.75，沒有共同區間；ERes2NetV2、ERes2Net large、CAM++ zh_en advanced 合成區間不比 CAM++ 寬；
  WeSpeaker ResNet34-LM 實錄 74–77%。嵌入先減會議平均再分群：實錄大幅變差，不採用。小群併入大群（< 5% 時長）：會把只講一行的第 4 人併掉，不採用。
  限制：逐句法切不開同一句內換人（VAD 停頓 < 0.25 s）；合成資料沒有搶話，真人會議未驗證。PI5_DIARIZE_METHOD=pyannote 可切回。
  - 3fcf849（門檻 0.6、無合併）部署 .228 11:38（備份 20261111_113813）；/api/refine 對 m_1794367149：done、diarize_method=sentence、96.6%、5 人。推送 gitlab／origin 9fa2ef8..a643cf0。
  - 實錄 10 分多出的第 5 群：HsiaoChen 的 6 句（全是同一人，群都純）。群中心餘弦（CAM++）：同一人被拆開 0.875；不同人最高 0.700（HsiaoChen~HsiaoYu，兩段實錄），乾淨 0.641。
    → 加「群中心 cos ≥ 0.8 就合併」並把門檻改 0.55：實錄 5／10 分 100%／100%（4 人），合成 5／15／30（x86）、60（Pi）全 100%（4 人）。
    合併的掃描（門檻 0.5／0.55／0.6 × 合併 0.75／0.8／0.85）：實錄 10 分只有門檻 0.5 為 99.4%（5 人），其餘 100%；合成全部 100%。
  - 240 分（Pi，meeting_240min.wav，2647 句）：門檻 0.6 無合併（3fcf849 的完整 CLI）100%、4 人，分說話人 283.7 s（pyannote 3258 s、94.0%、8 人）；
    同一批句子用門檻 0.55＋合併 0.8 也是 100%、4 人（門檻 0.5 為 99.96%、多 1 個 1 句的群）。此輪 ASR 1547.7 s 是與其他測試同時跑的值（單獨跑約 653 s）。
  - b4c9140（門檻 0.55＋合併 0.8＋PI5_VAD_MIN_SILENCE）部署 .228 12:21（備份 20261111_122107）；/api/refine 對 m_1794367149：100%、4 人，asr 28.6 s、diarize 10.6 s。
- SenseVoice VAD 掃描（/home/pi/ln_e2e/sec_test/vad_sweep.py，min_silence × max_speech × 門檻）：
  | min_silence | 實錄 5 分 CER（句數） | 實錄 10 分 CER（句數） | 乾淨 5 分 CER（句數） |
  |---|---|---|---|
  | 0.25（現行） | 0.181（90） | 0.1915（176） | 0.163（59） |
  | 0.4 | 0.170（64） | 0.184（126） | 0.164（55） |
  | 0.6 | 0.169（59） | 0.1815（118） | 0.162（49） |
  max_speech 12 與 20 結果相同；VAD 門檻 0.35 乾淨音檔句數掉到 37／28（-55 dBFS 底噪讓 VAD 不斷開，跨人風險），不採用。
  min_silence 調大會把停頓短於它的換人併成同一句（逐句分說話人分不開），合成資料換人停頓 ≥ 0.8 s 量不到 → 維持 0.25，加 PI5_VAD_MIN_SILENCE 供真人會議 A/B；已請使用者決定。

## 排程輪次紀錄（2026-11-10 20:24 起，台北時間）
- 互動鎖：本輪 20:24 已過 19:50，忽略。Pi state=done、無 real_exp.py，允許評估；後續 #1（喇叭／耳麥）依排程指示不做。
- 後續 #2 長會議：60 分鐘完成（見上方量測紀錄，未 OOM）。240 分鐘：2026-11-10 20:28 起在 Pi 背景跑（.cc_scratch/sv/run_240.sh，音檔 /home/pi/ln_e2e/data/meeting_240min.wav，nice 10）；腳本會在 state 為 recording／processing 時自行 pkill。輸出 /tmp/refine_240min.jsonl、/tmp/refine_240min.err（結束行 EXIT n；ABORT／KILL 行表示沒跑完）。結果見量測紀錄（21:33）。120 分鐘未單獨跑。
- 後續 #3 句子合併（已部署 21:35）：code_dispatcher/refine_transcript.py 新增 MERGE_GAP_S = 0.6：同一人相鄰兩句停頓 ≤ 0.6 s 時，前句結尾的「。」改「，」；「？！」不改，跨人不併。tests/test_refine_transcript.py：2 個舊期望值依新規則更新，新增 4 個單測。Windows pytest：tests（同 CLAUDE.md 的 ignore 清單）558 passed。
  - 另修測試（與本改動無關）：Windows 上 3 個子行程測試因子行程 stdout 為 cp950 而失敗，已在測試用的子行程設 UTF-8（只改測試，production 路徑不變）。
  - 調參（10 分鐘 fixture，refine_result_10min.json，.cc_scratch/sv/gap_stats.py）：單句行內的句中停頓 27 處，0.224–0.544 s；相鄰行界（句界）62 處，最短 1.504 s → 取 0.6。
  - 驗證（60 分鐘，refine_60min.jsonl）：相鄰單句行界 359 處，最短 0.832 s → 0.6 下誤合併 0 處。句中樣本為 0（60 分鐘的行多為多句，無法判定句中斷點），所以召回率在 60 分鐘未驗證。多句行內的斷點也未以真值驗證。
  - 離線重放（同一份 refine 結果，只比較標點）：60 分鐘「。」696 → 552（改 144 處）；10 分鐘 160 → 122（改 38 處）。去掉標點後文字完全相同；CER 不變（0.3478、0.3530；此 CER 含說話人標籤字元，絕對值不可與上方表格比較）。
  - 已部署（21:35，見量測紀錄）；後續 #3 完成。
- 誤建檔（待使用者手動刪）：/home/pi/ln_stress/meeting_10min.wav（20 MB 複本，本輪誤建，未用到）。依規則不做刪除。

- 2026-11-10 22:28 排程最終輪（台北時間）：互動鎖 19:50 已過期。Pi：/api/status state=done、無 recording／processing；pgrep real_exp.py 無實際程序（只匹配到檢查指令本身）。git：未推送的只有 b2b1f34（文件）。
  - 後續改善清單：#1 需喇叭／耳麥（本排程指示目前不做）；#2–#4 已完成；#5 待使用者決定。無剩餘可做項目。
  - /health 回 status=degraded、redis_connected=false、ollama_running=true、queue_length=0。raspi678 的 redis-server 為 inactive，redis-cli 未安裝；自 2026-11-09 起即如此（ACTIVE_BACKLOG_AND_NEXT_STEPS.md 第 8 項）。本大改的 /api/refine、/api/polish 不依賴 redis，已實測通過。部署腳本的健康檢查只判斷 HTTP 200，故通過；嚴格的 status=healthy 未達成，屬第 8 項，不在本大改範圍，未處理。
  - 本輪未部署、未在 Pi 跑評估。推送 gitlab、origin 完成（bf18d83，含 b2b1f34）。
  - 排程停用未完成：update_trigger 將 trig_01XfezGs1zV3uroLZy1NZm4D 設為 enabled=false 被自動權限分類器拒絕（Cowork Scheduled Task Delete）。排程仍啟用；未以其他途徑繞過。每輪讀到本檔 DONE 且無可做項目時，只需回報、不需再改程式；是否停用由使用者決定。
  - 誤建檔 /home/pi/ln_stress/meeting_10min.wav（20 MB）仍在，待使用者手動刪除。

- 2026-11-10 22:35 互動 session：排程提示已改成「後續改善」版（名稱「claude_localnote 大改後續改善循環」）。新提示要求夜間（19:00–07:00）照 CLAUDE.md 流程做 #1 聲學實測；#1 完成後排程會再嘗試停用，若仍被權限拒絕，由使用者手動停用。

- 2026-11-10 23:24 排程輪次（台北，夜間窗）：互動鎖 19:50 已過期（已刪該行）。Pi：/api/status state=done；pgrep real_exp、refine_transcript、run_suite、speaker_selftest 無實際程序。
  - #1 聲學實測：未執行，阻塞於耳麥連線。GET /api/bt/status：耳麥 RichChipAN（A0:D1:2A:42:12:34）為受信任裝置、auto_connect 原本已是 true，本輪以 POST /api/bt/trusted/auto_connect 再次確認為啟用；connected=false。
  - POST /api/bt/connect 無回應（逾時，已 force_terminate）；Pi 上 bluetoothctl connect 回 org.bluez.Error.InProgress br-connection-busy；bluetoothctl scan 15 s 兩次（相隔約 2 分鐘）皆未看到該 MAC。推測：耳麥關機或超出範圍（未查證）。PC 端裝置清單無 RichChip（耳麥未連到 PC）。
  - 因未見耳麥，本輪未播放 10 分鐘會議、未錄音、未跑 /api/refine；PC 喇叭與耳麥位置未確認（需人工）。未改程式、未部署、未重啟、未 commit 程式。
  - 注意：GET /api/bt/trusted 不存在（404），信任清單請用 GET /api/bt/status 的 trusted_devices；連線端點是 POST /api/bt/connect（body {"mac": ...}）。
  - 排程仍啟用（#1 未完成）。耳麥開機並靠近 Pi 與喇叭後，下一個夜間窗輪次可照 CLAUDE.md 流程重試。
  - 寫入限制：Desktop Commander 的 write_file 只能寫入 F:\ 下的專案資料夾，暫存 JSON 放在 F:\14_prj_raspi5_localnote_asia\.cc_scratch\（未追蹤，不 commit）。

- 2026-11-11 00:26 排程輪次（台北，夜間窗）：Pi /api/status state=done；pgrep 檢查 real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無實際評估程序（唯一匹配為檢查指令本身）。
  - #1 聲學實測：仍阻塞於耳麥未連線。POST /api/bt/trusted/auto_connect（body {"mac": "A0:D1:2A:42:12:34", "auto_connect": true}）回 success，auto_connect 維持 true；POST /api/bt/connect（body {"target": "A0:D1:2A:42:12:34"}）回 400（連線失敗，回應內文未讀到）；bluetoothctl info：Paired／Bonded／Trusted yes、Connected no；bluetoothctl scan 15 s 未見 A0:D1:2A:42:12:34。推測：耳麥關機或不在範圍內（未查證）。
  - API 欄位更正：/api/bt/connect 的 body 是 {"target": ...}（main.py BTConnectRequest），不是 {"mac": ...}；23:24 紀錄的寫法有誤。
  - 本輪未播放、未錄音、未跑 /api/refine；未改程式、未部署、未重啟、未 commit；未發送任何權限請求。
  - 本輪 device_bash 回報「未連接資料夾」，改以 Desktop Commander start_process（PowerShell）執行 SSH 與 Pi HTTP。
  - 無新進度（阻塞與 23:24 相同），本輪不回報。排程仍啟用。耳麥開機並靠近 Pi 與喇叭後，下一個夜間窗輪次重試。
- 2026-11-11 01:24 排程輪次（台北，夜間窗）：互動鎖已無（標頭行已移除）。Pi：/api/status state=done（最後一場 m_1794309254，無錄音／處理）；pgrep real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無實際評估程序。
  - #1 聲學實測：仍阻塞於耳麥未連線。GET /api/bt/status：connected=false、trusted auto_connect=true；POST /api/bt/connect（body {"target": "A0:D1:2A:42:12:34"}）回 Page Timeout（連線超時），錯誤訊息要求確認耳麥已開機、未在充電倉、未被其他裝置佔線；bluetoothctl info：Paired yes、Trusted yes、Connected no。
  - 本輪 device_bash 因未連接資料夾無法使用，未請求資料夾權限；改用 Desktop Commander start_process 執行 SSH 與 Pi 指令。
  - 未播放、未錄音、未跑 /api/refine；未改程式、未部署、未重啟、未 commit；未發送任何權限請求。無新進度，本輪不回報。排程仍啟用。

## 工作規則
- 白天（07:00–19:00）：只做數位工作（pytest、離線重放、合成資料 E2E、程式與文件）；不用 PC 喇叭放音、不用藍牙耳麥。
- 例外（2026-11-11 10:43 使用者指定）：.228 上的 USB 音效卡 GS3（喇叭＋麥克風，放在關門的小房間）白天也可以整天測。
  聲學 e2e：tools/e2e/run_suite.py --play-sink alsa_output.usb-GS3_GS3_20180508-00.analog-stereo --source alsa_input.usb-GS3_GS3_20180508-00.analog-stereo；
  Pi 上的包裝腳本 /home/pi/ln_e2e/acoustic_gs3/run_acoustic.sh <分鐘> <repo 目錄>（e2e → 存錄音 → /api/refine → 兩套逐字稿評分）。
- 錄音或處理中（/api/status 的 state 為 recording 或 processing）：Pi 上不跑任何評估、不部署、不重啟。
- 部署前一律 commit；用 Desktop Commander 的 Windows git 做 add／commit。累積 3–5 個已驗證 commit 才推送。
- 不做刪除，不送需使用者確認的權限請求（包括內建瀏覽器的網站授權；要看前端用 PC 上的 Playwright 無頭模式）。
- .cc_scratch/ 為未追蹤暫存，不 commit。
- 不要測一次就停著等：長任務放背景，等待時做別的數位工作（2026-11-10 使用者指定）。


## 排程輪次紀錄（續）
- 2026-11-11 02:24 排程輪次（台北，夜間窗）：Pi /api/status state=done（最後一場 m_1794309254，無錄音／處理）。遠端 pgrep -fl 只匹配到檢查指令本身的 bash（PID 146941），無 real_exp、refine_transcript、run_suite、speaker_selftest 評估程序。
  - #1 聲學實測：仍阻塞於耳麥未連線。GET /api/bt/status：connected=false、auto_connect=true、paired／trusted 清單含 RichChipAN（A0:D1:2A:42:12:34）。POST /api/bt/trusted/auto_connect（body {"mac", "auto_connect": true}）回 success；POST /api/bt/connect（body {"target": ...}）回 400，錯誤為 Page Timeout，訊息要求確認耳麥已開機、未在充電倉、未被其他裝置佔線。
  - 本輪 device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell（bt_try.ps1）與 read_file／write_file 讀寫檔並呼叫 Pi HTTP。未發送任何刪除權限、資料夾權限、電腦控制請求。
  - 未播放、未錄音、未跑 /api/refine；未改程式、未部署、未重啟、未 commit。
  - 暫存腳本 F:\14_prj_raspi5_localnote_asia\.cc_scratch\bt_try.ps1（未追蹤，不 commit）。
  - 無新進度（與 23:24、00:26、01:24 相同阻塞），本輪不回報。排程仍啟用。耳麥開機並靠近 Pi 與喇叭後，下一個夜間窗輪次重試。
- 2026-11-11 03:24 排程輪次（台北，夜間窗）：Pi /api/status state=done（m_1794309254，無錄音／處理）；ps 比對 real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無評估程序。
  - 本輪 device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell 執行 SSH 與 Pi HTTP。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - #1 聲學實測：仍阻塞於耳麥未連線。POST /api/bt/trusted/auto_connect（body {"mac", "auto_connect": true}）回 success；POST /api/bt/connect（body {"target": ...}）逾時無回應（curl -m 60，以 force_terminate 結束）；GET /api/bt/status：controller_ok=true、connected=false、trusted 清單含 A0:D1:2A:42:12:34（auto_connect=true）。推測：耳麥關機或不在範圍內（未查證）。
  - 未播放、未錄音、未跑 /api/refine；未改程式、未部署、未重啟、未 commit。後續改善 #2–#4 已完成，#5 待使用者決定，#1 須待耳麥連線。
  - 無新進度（同上阻塞），本輪不回報。排程仍啟用。耳麥開機並靠近 Pi 與喇叭後，下一個夜間窗輪次重試。

- 2026-11-11 04:24 排程輪次（台北，夜間窗）：互動鎖無（標頭無該行）。Pi /api/status state=done（m_1794309254，無錄音／處理）；SSH pgrep real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無評估程序。
  - #1 聲學實測：仍阻塞於耳麥未連線。GET /api/bt/status：controller_ok=true、connected=false、auto_connect=true（RichChipAN，A0:D1:2A:42:12:34）。POST /api/bt/trusted/auto_connect（body {"mac", "auto_connect": true}）回 success；POST /api/bt/connect（body {"target": ...}）回 Page Timeout，訊息要求確認耳麥已開機、未在充電倉、未被其他裝置佔線。耳麥是否開機、位置是否在範圍內，本環境無法查證。
  - 本輪 device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 執行 SSH、curl 與讀寫檔。JSON 請求 body 以 F:\14_prj_raspi5_localnote_asia\.cc_scratch\bt_auto.json、bt_connect.json 傳入（PowerShell 直接傳參會吃掉內層雙引號，回 json_invalid）。
  - 未播放、未錄音、未跑 /api/refine；未改程式、未部署、未重啟、未 commit。未發送任何刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - 無新進度（與 23:24 起相同阻塞），本輪不回報。後續改善 #2–#4 已完成，#5 待使用者決定，#1 須待耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）後，下一個夜間窗輪次重試。排程仍啟用。

- 2026-11-11 05:24 排程輪次（台北，夜間窗）：互動鎖無（標頭無該行）。Pi /api/status state=done（m_1794309254，無錄音／處理）；SSH ps 比對 real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無評估程序（none）。
  - #1 聲學實測：仍阻塞於耳麥未連線。GET /api/bt/status：connected=false、auto_connect=true（RichChipAN，A0:D1:2A:42:12:34）。POST /api/bt/trusted/auto_connect 回 success；POST /api/bt/connect（body {"target": ...}）回 Page Timeout，訊息要求確認耳麥已開機、未在充電倉、未被其他裝置佔線。
  - 本輪 device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell（暫存腳本 F:\14_prj_raspi5_localnote_asia\.cc_scratch\bt_round.ps1，未追蹤，不 commit）執行 SSH 與 Pi HTTP。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - 未播放、未錄音、未跑 /api/refine；未改程式、未部署、未重啟、未 commit。
  - 無新進度（與 23:24 起相同阻塞），本輪不回報。後續改善 #2–#4 已完成，#5 待使用者決定，#1 須待耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）後，下一個夜間窗輪次重試。排程仍啟用。
- 2026-11-11 06:24 排程輪次（台北 06:24 前後，夜間窗末段，07:00 進入白天）：互動鎖無（標頭無該行）。Pi /api/status state=done（m_1794309254，無錄音／處理）；SSH ps 比對 real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無評估程序。
  - #1 聲學實測：仍阻塞於耳麥未連線。GET /api/bt/status：controller_ok=true、connected=false、auto_connect=true（RichChipAN，A0:D1:2A:42:12:34）。POST /api/bt/trusted/auto_connect 回 success；POST /api/bt/connect（body {"target": ...}）回「連線失敗：請確認耳麥處於開機或待連線狀態後重試」。耳麥是否開機、是否在範圍內，本環境無法查證。
  - 未播放、未錄音、未跑 /api/refine；未改程式、未部署、未重啟、未 commit 程式；未發送任何刪除、資料夾、電腦控制或內建瀏覽器授權請求。device_bash 仍回報「未連接資料夾」，改用 Desktop Commander 的 PowerShell（暫存腳本 .cc_scratch\round_check.ps1、bt_round2.ps1，未追蹤，不 commit）。
  - 數位工作：清單 #2–#4 已完成，#1 需人工開機耳麥並確認喇叭位置，#5 待使用者決定，無其他可做的數位改善；本輪不改程式、不跑 pytest。
  - 無新進度，本輪不回報。排程仍啟用；耳麥開機並靠近 Pi 與喇叭後，下一個夜間窗（19:00 後）輪次重試 #1。

- 2026-11-11 07:24 排程輪次（台北，白天窗 07:00 起）：互動鎖無（標頭無該行）。Pi /api/status state=done（job m_1794309254，無錄音／處理）；SSH ps 比對 real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無評估程序。
  - #1 聲學實測：白天不做（只能在 19:00–07:00 進行）。耳麥仍未連線（06:24 紀錄為連線失敗），本輪未呼叫 /api/bt，未放音、未用耳麥。
  - 數位工作：清單 #2–#4 已完成，#5 待使用者決定，無剩餘可做的數位改善；本輪未改程式、未跑 pytest、未部署、未 commit。
  - device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell 執行 curl 與 SSH（其中一次 SSH 無輸出，已 force_terminate 後重試成功）。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - 無新進度，本輪不回報。排程仍啟用；#1 待耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）後，下一個夜間窗（19:00 後）輪次重試。

- 2026-11-11 08:24 排程輪次（台北 08:24，白天窗）：互動鎖無（標頭無該行）。Pi /api/status state=done（m_1794309254，無錄音／處理）；SSH ps 比對 python3 程序，僅見 key_led_driver 與 uvicorn，無評估程序。
  - #1 聲學實測：白天不做（須待 19:00 後）。未呼叫 /api/bt、未放音、未用耳麥。
  - 數位工作：清單 #2–#4 已完成，#5 待使用者決定；本輪重讀狀態檔與 CLAUDE.md，確認沒有剩餘可做的數位改善，未改程式、未跑 pytest、未部署、未 commit。
  - device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell 執行 curl 與 SSH。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - 無新進度，本輪不回報。排程仍啟用；#1 待耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）後，下一個夜間窗（19:00 後）輪次重試。

- 2026-11-11 09:24 排程輪次（台北，白天窗）：互動鎖無（標頭無該行）。Pi /api/status state=done（m_1794359755，無錄音／處理）；SSH pgrep real_exp、refine_transcript、run_suite、speaker_selftest 無評估程序。
  - #1 聲學實測：白天不做（須待 19:00 後）。未呼叫 /api/bt、未放音、未用耳麥。09:03 使用者手動測試時耳麥曾連線，本輪未查其目前狀態。
  - 數位工作：清單 #2–#4 已完成，#5 待使用者決定；本輪未改程式、未跑 pytest、未部署。
  - git：工作區有他人未提交的 claude_context/ACTIVE_BACKLOG_AND_NEXT_STEPS.md 修改，未併入本次 commit。
  - device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 執行 SSH 與 Pi HTTP。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - 無新進度，本輪不回報。排程仍啟用；#1 待 19:00 後、耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）時重試。

- 2026-11-11 10:24 排程輪次（台北，白天窗）：互動鎖無（標頭無該行）。Pi /api/status state=done（job m_1794359755，無錄音／處理）；SSH pgrep real_exp、refine_transcript、run_suite、speaker_selftest、run_240、run_with_rss 無評估程序。
  - #1 聲學實測：白天不做（須待 19:00 後）；本輪未呼叫 /api/bt、未放音、未用耳麥。#2–#4 已完成，#5 待使用者決定；清單內無剩餘可做的數位改善，本輪未改程式、未跑 pytest、未部署。
  - device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell 執行 curl 與 SSH。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - git：工作區另有他人未提交的 claude_context/ACTIVE_BACKLOG_AND_NEXT_STEPS.md 修改，未併入；本輪只記錄本檔。
  - 無新進度，本輪不回報。排程仍啟用；#1 待 19:00 後、耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）時重試。

- 2026-11-11 11:25 排程輪次（台北，白天窗）：互動鎖無（標頭無該行）。Pi /api/status state=recording（job m_1794367149，錄音進度 61%，eta 約 243 s）→ 本輪不在 Pi 上跑評估、不部署、不重啟。
  - Pi ps 觀察：另有一個 run_suite.py --minutes 10 --no-fail --play-sink alsa_output.usb-GS3… --source alsa_input.usb-GS3…（輸出 /home/pi/ln_e2e/acoustic_gs3/20261111_111905_10min，11:19:05 起），與上述錄音同時進行。非本輪啟動，來源未查證（可能為使用者手動測試）；本輪未終止、未干預。pw-play 無程序。
  - #1 聲學實測：白天（07:00–19:00）不做，GS3 白天條款只在 Pi 非錄音時才適用；本輪未呼叫 /api/bt、未放音、未用耳麥。
  - 數位工作：清單 #2–#4 已完成，#5 待使用者決定，無剩餘可做的數位改善；本輪未改程式、未跑 pytest、未部署、未 commit。
  - device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell 執行 SSH 與 Pi HTTP。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - 無新進度，本輪不回報。排程仍啟用；#1 待 19:00 後、耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）時重試。

- 2026-11-11 12:24 排程輪次（台北 12:24，白天窗）：互動鎖無（標頭無該行）。Pi /api/status state=recording（job m_1794370929，錄音進度 45%，elapsed 142.7 s／total 316 s，非本輪啟動，來源未查證）→ 本輪不在 Pi 上跑評估、不部署、不重啟；未呼叫 /api/bt、未 SSH。
  - #1 聲學實測：白天不做（須待 19:00 後）；耳麥連線狀態本輪未查。
  - 數位工作：清單 #2–#4 已完成，#5 待使用者決定，無剩餘可做的數位改善；本輪未改程式、未跑 pytest、未部署、未 commit。
  - device_bash 仍回報「未連接資料夾」，未請求資料夾權限；改用 Desktop Commander 的 PowerShell 讀取 Pi /api/status。未發送刪除、資料夾、電腦控制或內建瀏覽器授權請求。
  - 無新進度，本輪不回報。排程仍啟用；#1 待 19:00 後、耳麥開機並靠近 Pi 與喇叭（喇叭位置需人工確認）時重試。
