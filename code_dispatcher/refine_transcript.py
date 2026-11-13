# -*- coding: utf-8 -*-
"""
refine_transcript.py — 錄音結束後的高精度逐字稿：SenseVoice 重新辨識＋CAM++ 分說話人（大改第 2、3 項，2026-11-10）。

為什麼（tools/e2e 合成會議，量測記錄見 claude_context/BIG_CHANGE_STATUS.md）：
  - 同一份 10 分鐘音檔：Hailo Whisper（錄音中串流）CER 0.3135、不計數字格式 0.234；
    SenseVoiceSmall int8 CER 0.177、不計數字格式 0.047。
  - Pi 5 CPU 4 執行緒：SenseVoice RTF 0.048（10 分鐘 30 s）；CAM++ 分說話人 RTF 0.235（147 s）。
  - 分說話人逐句歸屬正確率：5／10／15／30 分鐘合成會議 89–98%。
做法（全部用 sherpa-onnx 現成元件）：
  ffmpeg 解成 16 kHz 單聲道 → Silero VAD 切句 → SenseVoice 逐句辨識（ITN 開，數字為阿拉伯數字）
  → pyannote-3.0 分段＋CAM++ 嵌入＋FastClustering 分說話人
  → 每句取重疊最長的說話人 → 依第一次出現的順序編成「說話人1、2…」，同一人連續的句子併成一段。
限制：CPU 推論，只能在錄音結束後跑；錄音一開始就停（CLAUDE.md 重點一）。
執行方式：服務用 run_in_subprocess() 在子行程（nice 10）跑。sherpa-onnx 的分說話人整段持有 GIL，
  11-10 實測放在服務行程的執行緒裡跑時 /api/status 逾時（整個 API 卡住約 2 分鐘）；子行程也能在錄音開始時直接終止。
模型：PI5_SHERPA_MODEL_DIR（預設 /home/pi/models/sherpa），安裝見 tools/ci/setup_sherpa_models.sh。
"""

import asyncio
import collections
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from summary_utils import to_taiwan_traditional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MODEL_DIR = os.environ.get("PI5_SHERPA_MODEL_DIR", "/home/pi/models/sherpa")
NUM_THREADS = int(os.environ.get("PI5_SHERPA_THREADS", "4"))
# SenseVoice 語言：auto 每句自動判斷。2026-11-11 實測：中文合成會議 CER 與 zh 相當（5／10／15 分：auto 0.166／0.179／0.1858，zh 0.166／0.177／0.1875）；
# 英文新聞夾中文廣告，zh 把英文段辨成亂碼中文，auto 英文段正常、中文廣告也正確。見 claude_context/BIG_CHANGE_STATUS.md。
ASR_LANGUAGE = os.environ.get("PI5_SENSEVOICE_LANGUAGE", "auto")
# VAD 切句的最短靜音（秒）。2026-11-11 GS3 實錄 5／10 分：0.25 → CER 0.181／0.1915，0.4 → 0.170／0.184，0.6 → 0.169／0.1815；
# 乾淨音檔 0.163／0.164／0.162（不變）。調大會讓停頓短於它的換人併成同一句，逐句分說話人就分不開；
# 合成資料換人停頓都 ≥ 0.8 s，量不到這個風險，真人會議驗證前維持 0.25。
VAD_MIN_SILENCE_S = float(os.environ.get("PI5_VAD_MIN_SILENCE", "0.25"))
# 辨識怎麼切段（2026-11-13）：pause = 跟即時逐字稿一樣在停頓處切 4–9.5 秒（audio_splice.pause_cut_index）整段辨識，
# 再依 token 時間把字分回 VAD 句子（分說話人仍用 VAD 句子，與之前相同）；vad = 舊法，每個 VAD 句子各自辨識。
# 量測（同一份 OGG 母帶、只比辨識，.cc_scratch/pe/exp_refine_seg.py，cer_num）：調參 實錄 5 分 0.0572 → 0.0337、
# 第二次錄 0.048 → 0.0388、10 分 0.0463 → 0.0337；驗證 新錄 10 分 0.0519 → 0.0342、30 分 0.0504 → 0.0326。VAD 句子平均才 3 秒，上下文太短。
# 整條流程（.cc_scratch/pe/exp_refine_full.py，含分說話人）：同上 3 份 cer_num 0.0572／0.048／0.0463 → 0.0337／0.0388／0.0342，
# 逐句歸屬正確率都 100%、4 人、句數相同；逐段 token 接起來都等於文字（0 段例外）。代價：辨識變慢約 50%（5 分 18 → 27 s、10 分 35 → 53 s）。
# 驗證 新錄 5／10 分、即時 SenseVoice 那兩場 5／10 分：cer_num 0.0541／0.0519／0.0501／0.0524 → 0.0439／0.0347／0.0409／0.0302，逐句正確率都 100%；
# 唯一差異：即時 SenseVoice 那場 10 分多分出 1 人（只有一句 1.31 s 的「主要是外殼刮傷，」，剛好超過 CLUSTER_MIN_LONGEST_S；已由 CLUSTER_MIN_UNITS 解決）。
ASR_SEGMENTATION = os.environ.get("PI5_REFINE_ASR_SEGMENT", "pause")
ASR_SLICE_MIN_S, ASR_SLICE_MAX_S = 4.0, 9.5
# 分說話人方法（2026-11-11）：sentence = 每句（SenseVoice 的 VAD 句子）算 CAM++ 嵌入後 FastClustering；
# pyannote = 舊流程（pyannote 分段 + CAM++ + FastClustering，再把句子對到重疊最長的分段）。
# 分群後再把「群中心餘弦相似度 ≥ CENTROID_MERGE_COS」的群合併（同一人被拆成兩群時中心很近）。
# 2026-11-11 量測（CAM++ 嵌入）：不同人的群中心最高 0.70（兩個相近的 TTS 女聲），同一人被拆開的兩群 0.875。
# 逐句正確率（門檻 0.55、合併 0.8、MIN_EMBED_S 1.0）：合成會議 5／15／30／60／240 分 100%（4 人；pyannote 86／76／93／96.5／94.0%，
# 60、240 分分出 6、8 人）；GS3 喇叭→麥克風實錄 5／10 分 100%／100%（4 人；pyannote 90.0%／84.1%）。
# 不合併時門檻 0.5 實錄分太多人，0.65 起合成會議兩個相近女聲併成一人。
# Pi 上分說話人耗時：5 分鐘 5.4 s（pyannote 67 s）、60 分鐘 74 s（824 s）、240 分鐘約 284 s（3258 s）。
# 逐句法無法切開同一句內換人（VAD 停頓 < 0.25 s 的搶話），必要時用環境變數切回 pyannote。
DIARIZE_METHOD = os.environ.get("PI5_DIARIZE_METHOD", "sentence")
SENTENCE_CLUSTER_THRESHOLD = 0.55
CENTROID_MERGE_COS = 0.8
MIN_EMBED_S = 1.0   # 比這短的句子嵌入不可靠（「好。」「對。」、實錄的殘響），借時間上最近的長句的說話人
# 句內換人：辨識仍用 VAD_MIN_SILENCE_S 的長句（上下文較好），另跑一個靈敏的 VAD（最短靜音 0.1 s），
# 在它的停頓處依 token 時間把句子切成小段再分說話人。2026-11-11 量測（合成會議重新拼接，換人停頓 0.05–0.3 s／0.3–0.6 s）：
# 現行 VAD 只切開 6／79、28／79 個換人點，逐句法 frame 正確率 42%／46%；加切段後 77%／70.5%（另一份 15 分 44% → 70%）；
# 原合成會議 5／15／30 分維持 100%（4 人）。改用 token 間隔 ≥ 0.35–0.45 s 也切，換人資料更好（82–94%）但原會議掉到 88–93%、分出 9–14 人，不採用。
# 分群後再看長段（≥ WINDOW_SPLIT_MIN_S）：1.5 s 視窗、0.75 s 步進，每個視窗比對各群中心；連續 ≥ 2 個視窗屬於別人就在該處切開。
# 同一批快速換人資料：77／70／70.5% → 92／90／95%（hop 0.5／need 3：90／91／96%；hop 1.0：89／89／94%）；原合成會議 5／15／30 分仍 100%。
# 切開的片段要 ≥ PIECE_MIN_EMBED_S 才自己算嵌入，否則借同句的長片段；同句沒有長片段時整句當一個單位算嵌入（片段共用說話人）。
# 2026-11-11 GS3 實錄 5／10 分：片段也用 1.0 s 時 frame 正確率 99.49／99.79%（「週五回報。」1.02 s 片段自己分群分錯；
# 「3月8日／有一場／自安課程。」切成三段都短，後面的「名額20。」借到下一個人），改後 100／100%。
# 調參（x86，實錄 5 分＋快速換人 fast10，皆含整句單位）：1.0 → 99.49／92.29、1.1 → 100／92.29、1.25 → 100／92.04、1.5 → 100／91.06、2.0 → 100／86.71。
# 1.1 在實錄 60 分驗證失敗：99.86%、5 人（三個 1.1–1.2 s 的「週X回報。」片段字一樣，自成一群）；1.25 → 100%、4 人。
# 1.25 全部資料：實錄 5／10／30／60 分 100／100／99.74／100%（片段 1.0 s 時 99.49／99.79／99.45／99.68%；未切段的舊法 100／100／99.74／100%），
# 快速換人 fast10／fast15／mid10 92.0／90.1／96.2%（舊法 42／44／46%），乾淨合成 5／15／30 分 100%。
PIECE_MIN_EMBED_S = 1.25
# 分群後，最長單位都 < CLUSTER_MIN_LONGEST_S 的群不算一個人：它的單位不參與分群結果，改用下面的「借最近單位」。
# 約 1 s 的單位嵌入不可靠，字一樣的短句會自成一群：GS3 實錄 5 分（第二次錄，m_1794387394）兩個 1.0 s 的「週五回報。」「招募方面。」
# 自成第 5 人，frame 99.0%（未切段的舊法同樣 99.0%、5 人）→ 100%、4 人。其他資料都不變（實錄 5／10／30／60、快速換人、乾淨 5／15／30，x86）。
# 2.0 會把實錄 5 分只講一行（最長 1.5–2.0 s）的真人併掉（97.7%、3 人）；1.25 與片段門檻相同。
CLUSTER_MIN_LONGEST_S = 1.25
# 只有 1 個單位的群也不算一個人（2026-11-13，.cc_scratch/pe/exp_diar_units.py；同一次辨識，GS3 9 份＋藍牙 3 份，實際 4 人）：
# 1（原行為）→ 2：只有即時 SenseVoice 那場 10 分由 5 人變 4 人（一句 1.31 s 的「主要是外殼刮傷，」自成一群）、時間正確率 99.67 → 100%，
# 其他 11 份完全相同（藍牙 30 分仍是 5 人：多出的那群有 2 個單位，3 才併得掉）；3 會把 5 分會議裡只講 2 段的真人併掉
# （4 份變 3 人、逐句 97.8%），不用。
# 代價：整場只講一段（≥ 1.25 s）的人會併到時間上最近的人。PI5_CLUSTER_MIN_UNITS=1 切回。
CLUSTER_MIN_UNITS = int(os.environ.get("PI5_CLUSTER_MIN_UNITS", "2"))
WINDOW_S = 1.5
WINDOW_HOP_S = 0.75
WINDOW_SPLIT_MIN_S = 3.0
WINDOW_SPLIT_RUN = 2
FINE_VAD_MIN_SILENCE_S = 0.1
SPLIT_EDGE_S = 0.2           # 切點離句首、句尾至少這麼遠
SPLIT_MAX_TOKEN_DIST_S = 0.6  # 切點附近 0.6 s 內要有 token 起點，才對得到字
# pyannote 流程的分群門檻：sherpa 預設 0.5 在 15 分鐘合成會議切出 8–10 人（實際 4 人）；0.7 在 5／10／15／30 分鐘都找到 4–5 人。
CLUSTER_THRESHOLD = 0.7
# 句子落在分段的空隙裡（分段模型會把句中停頓切掉）時，借用 1 秒內最近的說話人。
NEAREST_TURN_MAX_GAP_S = 1.0
# 同一人相鄰兩句的停頓 ≤ 此秒數 → 前句結尾的「。」改「，」（VAD 句中切開，不是句界）。
# 調參用 10 分鐘合成會議（句中停頓 0.22–0.54 s，句界 ≥ 1.50 s）；驗證用 60 分鐘（句界最短 0.83 s）。見 claude_context/BIG_CHANGE_STATUS.md。
MERGE_GAP_S = 0.6
DECODE_TIMEOUT_S = 900
CHILD_NICE = 10
STOP_POLL_S = 1.0
STOP_GRACE_S = 5.0
CHILD_LINE_LIMIT = 32 * 1024 * 1024  # 結果是一行 JSON；4 小時會議約數 MB，asyncio 預設 64 KB 不夠
MODEL_FILES = {
    "asr": "sensevoice_small_int8.onnx",
    "tokens": "sensevoice_tokens.txt",
    "vad": "silero_vad.onnx",
    "segmentation": "pyannote_segmentation_3_0.onnx",
    "embedding": "campplus_zh_cn_common.onnx",
}
ENGINE_LABEL = "SenseVoiceSmall int8 + CAM++（sherpa-onnx，CPU）"


def pipeline_labels() -> Dict[str, str]:
    """網頁顯示用：這次高精度逐字稿實際用的 ASR／VAD／分說話人組合（數值取自本模組的設定，不另寫一份）。"""
    if DIARIZE_METHOD == "pyannote":
        diar = f"pyannote-3.0 分段＋CAM++ 嵌入＋FastClustering（門檻 {CLUSTER_THRESHOLD:g}）"
    else:
        diar = (f"CAM++ 逐句分群（門檻 {SENTENCE_CLUSTER_THRESHOLD:g}、群中心合併 {CENTROID_MERGE_COS:g}）"
                f"＋滑動視窗找句內換人（{WINDOW_S:g} s 視窗、{WINDOW_HOP_S:g} s 步進）")
    return {
        "asr": f"SenseVoiceSmall int8（sherpa-onnx，CPU {NUM_THREADS} 執行緒，語言 {ASR_LANGUAGE}，ITN）",
        "vad": (f"辨識：停頓處切 {ASR_SLICE_MIN_S:g}–{ASR_SLICE_MAX_S:g} s 整段辨識；" if ASR_SEGMENTATION == "pause" else "")
               + f"Silero VAD 切句（最短靜音 {VAD_MIN_SILENCE_S:g} s；分說話人另用 {FINE_VAD_MIN_SILENCE_S:g} s 找句內停頓）",
        "diarize": diar,
        "post": "OpenCC s2twp＋台灣用字修正",
    }
_PUNCT = "。！？!?，,、；;：:…"
_ASCII_PUNCT = ".!?,;:"

Turn = Tuple[float, float, int]
StopFn = Optional[Callable[[], bool]]
ProgressFn = Optional[Callable[[float], None]]


class RefineError(RuntimeError):
    """可預期的失敗（缺套件、缺模型、解碼失敗），訊息直接給前端看。"""


@dataclass
class Sentence:
    start: float
    end: float
    text: str
    speaker: Optional[int] = None
    cont: bool = False   # 同一個 VAD 句子在短停頓處切開的後半段（接回時不加標點）
    # SenseVoice 的 token 與起點時間（秒），切段用；不輸出（見 _public）
    tokens: Optional[List[str]] = field(default=None, repr=False)
    times: Optional[List[float]] = field(default=None, repr=False)


def _public(s: Sentence) -> Dict[str, Any]:
    d = asdict(s)
    d.pop("tokens", None)
    d.pop("times", None)
    return d


def model_path(key: str) -> str:
    return os.path.join(MODEL_DIR, MODEL_FILES[key])


def check_available() -> Optional[str]:
    """可用回傳 None；不可用回傳原因。"""
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError as e:
        return f"未安裝 sherpa-onnx（{e}）"
    missing = [name for name in MODEL_FILES.values() if not os.path.isfile(os.path.join(MODEL_DIR, name))]
    if missing:
        return f"缺少模型檔 {', '.join(missing)}（{MODEL_DIR}）"
    return None


def load_audio(path: str):
    """用 ffmpeg 解成 16 kHz 單聲道 float32。"""
    import numpy as np

    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True, timeout=DECODE_TIMEOUT_S)
    except FileNotFoundError as e:
        raise RefineError("找不到 ffmpeg") from e
    except subprocess.CalledProcessError as e:
        raise RefineError(f"音檔解碼失敗：{e.stderr.decode('utf-8', 'replace')[:200]}") from e
    except subprocess.TimeoutExpired as e:
        raise RefineError("音檔解碼逾時") from e
    samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        raise RefineError("音檔沒有內容")
    return samples


def token_pieces(start: float, end: float, tokens: Sequence[str], times: Sequence[float],
                 cuts: Sequence[float]) -> List[Tuple[float, float, int, int]]:
    """依 token 起點時間把一句切在 cuts（秒）附近：切點取最近的 token 起點與前一個 token 起點的中點。
    token 與時間數量不符、切點附近 SPLIT_MAX_TOKEN_DIST_S 內沒有 token、或離句首尾太近時不切。
    只剩標點的片段併回前一段。回傳 [(start, end, token 起索引, token 迄索引)]。"""
    if len(tokens) < 2 or len(tokens) != len(times):
        return [(start, end, 0, len(tokens))]
    idx_bounds, t_bounds = [0], [start]
    for c in sorted(cuts):
        k = min(range(1, len(times)), key=lambda i: abs(times[i] - c))
        if abs(times[k] - c) > SPLIT_MAX_TOKEN_DIST_S or k <= idx_bounds[-1]:
            continue
        b = (times[k - 1] + times[k]) / 2
        if t_bounds[-1] + SPLIT_EDGE_S < b < end - SPLIT_EDGE_S:
            idx_bounds.append(k)
            t_bounds.append(b)
    idx_bounds.append(len(tokens))
    t_bounds.append(end)
    pieces: List[Tuple[float, float, int, int]] = []
    for i in range(len(idx_bounds) - 1):
        i0, i1 = idx_bounds[i], idx_bounds[i + 1]
        if pieces and not any(ch.isalnum() for ch in "".join(tokens[i0:i1])):
            s0, _, j0, _ = pieces[-1]
            pieces[-1] = (s0, t_bounds[i + 1], j0, i1)
            continue
        pieces.append((t_bounds[i], t_bounds[i + 1], i0, i1))
    return pieces


def split_at_pauses(start: float, end: float, tokens: Sequence[str], times: Sequence[float],
                    cuts: Sequence[float]) -> List[Tuple[float, float, str]]:
    """同 token_pieces，回傳 [(start, end, text)]。"""
    return [(a, b, "".join(tokens[i0:i1]).strip()) for a, b, i0, i1 in token_pieces(start, end, tokens, times, cuts)]


def pause_slices(samples) -> List[Tuple[int, int]]:
    """跟即時逐字稿相同的切法：每段在 ASR_SLICE_MIN_S–ASR_SLICE_MAX_S 秒內能量最低處下刀。回傳 [(起樣本, 迄樣本)]。"""
    from audio_splice import pause_cut_index
    n_samples = len(samples)
    out, pos, hi = [], 0, int(ASR_SLICE_MAX_S * SAMPLE_RATE)
    while n_samples - pos > hi:
        cut = pause_cut_index(samples[pos:pos + hi + 1], SAMPLE_RATE, ASR_SLICE_MIN_S, ASR_SLICE_MAX_S)
        out.append((pos, pos + cut))
        pos += cut
    if n_samples - pos > 0:
        out.append((pos, n_samples))
    return out


def assign_tokens(regions: Sequence[Tuple[float, float]], tokens: Sequence[str],
                  times: Sequence[float]) -> List[Tuple[List[str], List[float]]]:
    """每個 token 依起點時間（已排序）歸到所在的 VAD 句子；落在兩句之間（VAD 沒收的停頓）就歸到較近的那句。"""
    out: List[Tuple[List[str], List[float]]] = [([], []) for _ in regions]
    if not regions:
        return out
    j = 0
    for tok, t in zip(tokens, times):
        while j + 1 < len(regions) and regions[j + 1][0] <= t:
            j += 1
        k = j
        if t >= regions[j][1] and j + 1 < len(regions) and regions[j + 1][0] - t < t - regions[j][1]:
            k = j + 1
        out[k][0].append(tok)
        out[k][1].append(t)
    return out


def transcribe(samples, should_stop: StopFn = None, on_progress: ProgressFn = None) -> Optional[List[Sentence]]:
    """VAD 切句後逐句辨識，再依靈敏 VAD 的短停頓把句子切成小段（見 FINE_VAD_MIN_SILENCE_S；
    後段的 cont=True）。被 should_stop 中止時回傳 None。"""
    import sherpa_onnx

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=model_path("asr"), tokens=model_path("tokens"), num_threads=NUM_THREADS, language=ASR_LANGUAGE, use_itn=True
    )

    def make_vad(min_silence: float, min_speech: float):
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = model_path("vad")
        cfg.silero_vad.min_silence_duration = min_silence
        cfg.silero_vad.min_speech_duration = min_speech
        cfg.silero_vad.max_speech_duration = 20
        cfg.sample_rate = SAMPLE_RATE
        cfg.num_threads = 1
        return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120), cfg.silero_vad.window_size

    vad, window = make_vad(VAD_MIN_SILENCE_S, 0.25)
    fine_vad, _ = make_vad(FINE_VAD_MIN_SILENCE_S, 0.1)
    raw: List[Tuple[float, float, str, List[str], List[float]]] = []
    fine_regions: List[Tuple[float, float]] = []

    regions: List[Tuple[float, float]] = []

    def drain() -> None:
        while not vad.empty():
            seg = vad.front
            if ASR_SEGMENTATION == "pause":   # 只記句子範圍，辨識另外整段做
                start = seg.start / SAMPLE_RATE
                regions.append((start, start + len(seg.samples) / SAMPLE_RATE))
                vad.pop()
                continue
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, seg.samples)
            recognizer.decode_stream(stream)
            res = stream.result
            text = res.text.strip()
            if text:
                start = seg.start / SAMPLE_RATE
                raw.append((start, start + len(seg.samples) / SAMPLE_RATE, text,
                            list(res.tokens), [start + t for t in res.timestamps]))
            vad.pop()
        while not fine_vad.empty():
            seg = fine_vad.front
            fine_regions.append((seg.start / SAMPLE_RATE, (seg.start + len(seg.samples)) / SAMPLE_RATE))
            fine_vad.pop()

    check_every = window * 200  # 約每 6.4 秒音訊檢查一次中止與進度
    total = len(samples)
    for i in range(0, total, window):
        chunk = samples[i:i + window]
        vad.accept_waveform(chunk)
        fine_vad.accept_waveform(chunk)
        drain()
        if i % check_every == 0:
            if should_stop is not None and should_stop():
                return None
            if on_progress is not None:   # pause 模式 VAD 只切句、很快，辨識另算（進度 10% 之後）
                on_progress(i / total * (0.1 if ASR_SEGMENTATION == "pause" else 1.0))
    vad.flush()
    fine_vad.flush()
    drain()

    if ASR_SEGMENTATION == "pause":
        all_tokens: List[str] = []
        all_times: List[float] = []
        slices = pause_slices(samples)
        for n, (i0, i1) in enumerate(slices):
            if should_stop is not None and should_stop():
                return None
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples[i0:i1])
            recognizer.decode_stream(stream)
            res = stream.result
            if len(res.tokens) == len(res.timestamps):
                all_tokens.extend(res.tokens)
                all_times.extend(i0 / SAMPLE_RATE + t for t in res.timestamps)
            elif res.text.strip():   # 沒有逐字時間（不應發生）：整段文字放在段落中點
                all_tokens.append(res.text.strip())
                all_times.append((i0 + i1) / 2 / SAMPLE_RATE)
            if on_progress is not None:
                on_progress(0.1 + 0.9 * (n + 1) / len(slices))
        for (start, end), (toks, tms) in zip(regions, assign_tokens(regions, all_tokens, all_times)):
            text = "".join(toks).strip()
            if text:
                raw.append((start, end, text, toks, tms))

    pauses = [(a[1] + b[0]) / 2 for a, b in zip(fine_regions, fine_regions[1:])]
    sentences: List[Sentence] = []
    for start, end, text, tokens, times in raw:
        # tokens 接起來要等於 text（ITN 後的文字）才能依 token 切，否則保留整句、不帶 token
        if "".join(tokens).strip() != text or len(tokens) != len(times):
            sentences.append(Sentence(start, end, text))
            continue
        cuts = [p for p in pauses if start < p < end]
        for j, (a, b, i0, i1) in enumerate(token_pieces(start, end, tokens, times, cuts)):
            piece = "".join(tokens[i0:i1]).strip()
            if piece:
                sentences.append(Sentence(a, b, piece, cont=j > 0, tokens=tokens[i0:i1], times=times[i0:i1]))
    return sentences


def diarize(samples, should_stop: StopFn = None, on_progress: ProgressFn = None) -> Optional[List[Turn]]:
    """回傳 [(start, end, speaker)]，依開始時間排序。被 should_stop 中止時回傳 None。"""
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=model_path("segmentation")),
            num_threads=NUM_THREADS,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path("embedding"), num_threads=NUM_THREADS),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=CLUSTER_THRESHOLD),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RefineError("分說話人設定無效（請檢查模型檔）")
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)
    stopped = False

    def callback(done: int, total: int) -> int:
        nonlocal stopped
        if on_progress is not None and total:
            on_progress(done / total)
        if should_stop is not None and should_stop():
            stopped = True
            return 1  # 非 0 = 要求 sherpa 中止
        return 0

    result = sd.process(samples, callback=callback).sort_by_start_time()
    if stopped:
        return None
    return [(r.start, r.end, r.speaker) for r in result]


def merge_close_clusters(labels: Sequence[int], embeddings, min_cos: float) -> List[int]:
    """群中心（正規化嵌入的平均再正規化）兩兩餘弦相似度最高的一對若 ≥ min_cos 就合併，重複到沒有為止。"""
    import numpy as np

    lab = np.asarray(labels, dtype=int).copy()
    unit = np.asarray(embeddings, dtype=np.float64)
    unit = unit / np.maximum(np.linalg.norm(unit, axis=1, keepdims=True), 1e-12)
    while True:
        ids = sorted(set(lab.tolist()))
        if len(ids) < 2:
            break
        cen = np.stack([unit[lab == k].mean(axis=0) for k in ids])
        cen = cen / np.maximum(np.linalg.norm(cen, axis=1, keepdims=True), 1e-12)
        sim = cen @ cen.T
        np.fill_diagonal(sim, -1.0)
        a, b = np.unravel_index(int(np.argmax(sim)), sim.shape)
        if sim[a, b] < min_cos:
            break
        lab[lab == ids[b]] = ids[a]
    return lab.tolist()


def embedding_units(sentences: Sequence[Sentence]) -> Tuple[List[Tuple[float, float, List[int]]], List[int]]:
    """決定要算嵌入的單位。回傳 (units, groups)：units = [(start, end, [句子索引])]，groups = 每句所屬的 VAD 句（cont 串）編號。
    沒切開的句子 ≥ MIN_EMBED_S 自成一個單位；切開的句子裡 ≥ PIECE_MIN_EMBED_S 的片段各自一個單位；
    切開後沒有夠長的片段時，整句（≥ MIN_EMBED_S）當一個單位，所有片段共用它的說話人。"""
    groups: List[int] = []
    g = -1
    for s in sentences:
        g += 0 if s.cont else 1
        groups.append(g)
    members: Dict[int, List[int]] = {}
    for i, gi in enumerate(groups):
        members.setdefault(gi, []).append(i)
    units: List[Tuple[float, float, List[int]]] = []
    for idx in members.values():
        first, last = sentences[idx[0]], sentences[idx[-1]]
        if len(idx) == 1:
            if first.end - first.start >= MIN_EMBED_S:
                units.append((first.start, first.end, idx))
            continue
        longs = [i for i in idx if sentences[i].end - sentences[i].start >= PIECE_MIN_EMBED_S]
        units.extend((sentences[i].start, sentences[i].end, [i]) for i in longs)
        if not longs and last.end - first.start >= MIN_EMBED_S:
            units.append((first.start, last.end, idx))
    units.sort(key=lambda u: u[0])
    return units, groups


def diarize_sentences(samples, sentences: List[Sentence], should_stop: StopFn = None,
                      on_progress: ProgressFn = None) -> bool:
    """逐句分說話人：每個單位（見 embedding_units）算一個 CAM++ 嵌入，FastClustering 分群後寫入 sentence.speaker；
    不屬於任何單位的短片段先借同一 VAD 句內時間上最近的單位，同句沒有才借全場最近的單位。
    被 should_stop 中止時回傳 False（speaker 維持 None）。"""
    import numpy as np
    import sherpa_onnx

    units, groups = embedding_units(sentences)
    if not units:
        for s in sentences:
            s.speaker = 0
        return True
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path("embedding"), num_threads=NUM_THREADS)
    if not config.validate():
        raise RefineError("說話人嵌入模型設定無效（請檢查模型檔）")
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
    embeddings = []
    for k, (a, b, _) in enumerate(units):
        if k % 20 == 0:
            if should_stop is not None and should_stop():
                return False
            if on_progress is not None:
                on_progress(0.6 * k / len(units))
        stream = extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)])
        stream.input_finished()
        embeddings.append(extractor.compute(stream))
    clustering = sherpa_onnx.FastClustering(
        sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=SENTENCE_CLUSTER_THRESHOLD))
    emb = np.ascontiguousarray(np.array(embeddings, dtype=np.float32))
    labels = merge_close_clusters(clustering(emb), emb, CENTROID_MERGE_COS)
    longest: Dict[int, float] = {}
    count: Dict[int, int] = {}
    for (a, b, _), label in zip(units, labels):
        longest[label] = max(longest.get(label, 0.0), b - a)
        count[label] = count.get(label, 0) + 1
    keep = [k for k, label in enumerate(labels)
            if longest[label] >= CLUSTER_MIN_LONGEST_S and count[label] >= CLUSTER_MIN_UNITS]
    if not keep:   # 每群都只有一個單位（很短的錄音）：只看最長單位
        keep = [k for k, label in enumerate(labels) if longest[label] >= CLUSTER_MIN_LONGEST_S]
    if keep and len(keep) < len(units):
        units = [units[k] for k in keep]
        labels = [labels[k] for k in keep]
        emb = np.ascontiguousarray(emb[keep])
    for (_, _, idx), label in zip(units, labels):
        for i in idx:
            sentences[i].speaker = int(label)
    units_in_group: Dict[int, List[int]] = {}
    for u, (_, _, idx) in enumerate(units):
        units_in_group.setdefault(groups[idx[0]], []).append(u)
    mids = np.array([(a + b) / 2 for a, b, _ in units])
    for n, s in enumerate(sentences):
        if s.speaker is None:
            mid = (s.start + s.end) / 2
            same = units_in_group.get(groups[n])
            if same:
                u = min(same, key=lambda v: abs(mids[v] - mid))
            else:
                u = int(np.argmin(np.abs(mids - mid)))
            s.speaker = int(labels[u])

    unit = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-12)
    lab_arr = np.asarray(labels)
    centroids = {}
    for k in sorted(set(labels)):
        c = unit[lab_arr == k].mean(axis=0)
        centroids[int(k)] = c / max(float(np.linalg.norm(c)), 1e-12)
    if len(centroids) >= 2:
        refined = split_by_windows(samples, sentences, extractor, centroids, should_stop,
                                   None if on_progress is None else (lambda f: on_progress(0.6 + 0.4 * f)))
        if refined is None:
            for s in sentences:
                s.speaker = None
            return False
        sentences[:] = refined
    if on_progress is not None:
        on_progress(1.0)
    return True


def window_runs(labels: Sequence[int], current: int) -> List[Tuple[int, int]]:
    """視窗標籤序列裡「連續 ≥ WINDOW_SPLIT_RUN 個視窗不是目前說話人」的換人點。回傳 [(視窗索引, 新說話人)]。"""
    changes: List[Tuple[int, int]] = []
    cur, i = current, 0
    while i < len(labels):
        if labels[i] != cur:
            j = i
            while j < len(labels) and labels[j] == labels[i]:
                j += 1
            if j - i >= WINDOW_SPLIT_RUN:
                changes.append((i, labels[i]))
                cur = labels[i]
                i = j
                continue
        i += 1
    return changes


def split_by_windows(samples, sentences: List[Sentence], extractor, centroids: Dict[int, Any],
                     should_stop: StopFn = None, on_progress: ProgressFn = None) -> Optional[List[Sentence]]:
    """長段內用滑動視窗找換人點，依 token 時間切開並各自標上說話人。被中止時回傳 None。"""
    import numpy as np

    keys = list(centroids)
    cen = np.stack([centroids[k] for k in keys])
    out: List[Sentence] = []
    n_windows = 0
    for n, s in enumerate(sentences):
        if on_progress is not None and n % 20 == 0:
            on_progress(n / len(sentences))
        if s.end - s.start < WINDOW_SPLIT_MIN_S or not s.tokens or s.speaker is None:
            out.append(s)
            continue
        starts, labels = [], []
        t = s.start
        while t + WINDOW_S <= s.end + 1e-6:
            n_windows += 1
            if n_windows % 50 == 0 and should_stop is not None and should_stop():
                return None
            stream = extractor.create_stream()
            stream.accept_waveform(SAMPLE_RATE, samples[int(t * SAMPLE_RATE):int((t + WINDOW_S) * SAMPLE_RATE)])
            stream.input_finished()
            v = np.asarray(extractor.compute(stream), dtype=np.float64)
            v = v / max(float(np.linalg.norm(v)), 1e-12)
            starts.append(t)
            labels.append(keys[int(np.argmax(cen @ v))])
            t += WINDOW_HOP_S
        changes = window_runs(labels, s.speaker)
        if not changes:
            out.append(s)
            continue
        bounds = [(starts[i] + WINDOW_S / 2, k) for i, k in changes]
        pieces = token_pieces(s.start, s.end, s.tokens, s.times, [b for b, _ in bounds])
        for j, (a, b, i0, i1) in enumerate(pieces):
            mid = (a + b) / 2
            speaker = s.speaker
            for cut, k in bounds:
                if mid >= cut:
                    speaker = k
            text = to_taiwan_traditional("".join(s.tokens[i0:i1]).strip())
            if text:
                out.append(Sentence(a, b, text, speaker=speaker, cont=s.cont if j == 0 else True,
                                    tokens=s.tokens[i0:i1], times=s.times[i0:i1]))
    return out


def assign_speakers(sentences: List[Sentence], turns: Sequence[Turn]) -> None:
    """每句取重疊時間最長的說話人；沒有重疊就借 NEAREST_TURN_MAX_GAP_S 內最近的說話人。"""
    for s in sentences:
        overlap: Dict[int, float] = {}
        nearest: Optional[int] = None
        nearest_gap = NEAREST_TURN_MAX_GAP_S
        for start, end, speaker in turns:
            ov = min(end, s.end) - max(start, s.start)
            if ov > 0:
                overlap[speaker] = overlap.get(speaker, 0.0) + ov
            elif -ov <= nearest_gap:
                nearest, nearest_gap = speaker, -ov
        if overlap:
            s.speaker = max(overlap, key=overlap.get)
        else:
            s.speaker = nearest


def _is_ascii_word_char(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _join(parts: Sequence[Sentence]) -> str:
    """同一人的連續句子接成一段。前句結尾是「。」且與下一句的停頓很短（VAD 在句中切開）→ 「。」改「，」；
    英文（前句以半形標點或英數字結尾，後句以英數字開頭）用空格接；其他沒有標點的前句補「，」。
    11-11：英文會議原本會接成「meeting.，We have」。"""
    out = ""
    prev: Optional[Sentence] = None
    for s in parts:
        if prev is not None and out:
            last = out[-1]
            first = s.text[:1]
            if s.cont:
                # 同一個 VAD 句子切開的後段：原樣接回，只補英文詞之間的空格
                if last in _ASCII_PUNCT or (_is_ascii_word_char(last) and _is_ascii_word_char(first)):
                    out += " "
            elif prev.text.endswith("。") and s.start - prev.end <= MERGE_GAP_S:
                out = out[:-1] + "，"
            elif last in _ASCII_PUNCT or (_is_ascii_word_char(last) and _is_ascii_word_char(first)):
                out += " "
            elif last not in _PUNCT:
                out += "，"
        out += s.text
        prev = s
    return out


def format_transcript(sentences: Sequence[Sentence]) -> Tuple[str, int]:
    """同一人連續的句子併成一行「說話人N：…」；N 依第一次出現的順序。回傳 (逐字稿, 說話人數)。"""
    order: Dict[int, int] = {}
    lines: List[str] = []
    cur: Any = object()
    buf: List[Sentence] = []

    def flush() -> None:
        if buf:
            label = f"說話人{order[cur]}" if cur is not None else "說話人?"
            lines.append(f"{label}：{_join(buf)}")

    if all(s.speaker is None for s in sentences):
        return _join(sentences), 0
    for s in sentences:
        if s.speaker is not None and s.speaker not in order:
            order[s.speaker] = len(order) + 1
        if s.speaker != cur:
            flush()
            buf = []
            cur = s.speaker
        buf.append(s)
    flush()
    return "\n".join(lines), len(order)


def refine(path: str, should_stop: StopFn = None,
           on_progress: Optional[Callable[[str, float], None]] = None,
           on_partial: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """整段流程（阻塞）。回傳 dict；stopped=True 表示中途被打斷。

    on_partial(結果)：辨識完成、開始分說話人之前呼叫一次，內容是還沒分人的逐字稿；分說話人被打斷時用得到。
    """
    reason = check_available()
    if reason:
        raise RefineError(reason)

    def report(phase: str, frac: float) -> None:
        if on_progress is not None:
            on_progress(phase, max(0.0, min(1.0, frac)))

    report("load", 0.0)
    samples = load_audio(path)
    audio_s = len(samples) / SAMPLE_RATE
    out: Dict[str, Any] = {"engine": ENGINE_LABEL, **pipeline_labels(), "audio_s": round(audio_s, 1), "stopped": False}

    t0 = time.time()
    sentences = transcribe(samples, should_stop, lambda f: report("asr", f))
    out["asr_s"] = round(time.time() - t0, 1)
    if sentences is None:
        out.update(stopped=True, phase="asr", transcript="", speakers=0, sentences=[])
        return out
    for s in sentences:
        s.text = to_taiwan_traditional(s.text)
    if on_partial is not None:
        text, _ = format_transcript(sentences)
        on_partial({**out, "phase": "diarize", "transcript": text, "speakers": 0,
                    "sentences": [_public(s) for s in sentences]})

    t1 = time.time()
    if DIARIZE_METHOD == "pyannote":
        turns = diarize(samples, should_stop, lambda f: report("diarize", f))
        done = turns is not None
        if done:
            assign_speakers(sentences, turns)
    else:
        done = diarize_sentences(samples, sentences, should_stop, lambda f: report("diarize", f))
    out["diarize_s"] = round(time.time() - t1, 1)
    out["diarize_method"] = DIARIZE_METHOD
    if not done:
        # 分說話人被打斷：仍交出辨識結果（不分人）。
        for s in sentences:
            s.speaker = None
        text, _ = format_transcript(sentences)
        out.update(stopped=True, phase="diarize", transcript=text, speakers=0,
                   sentences=[_public(s) for s in sentences])
        return out

    text, speakers = format_transcript(sentences)
    out.update(transcript=text, speakers=speakers, sentences=[_public(s) for s in sentences])
    logger.info("[refine] %.0f s audio: asr %.1f s, diarize %.1f s, %d sentences, %d speakers",
                audio_s, out["asr_s"], out["diarize_s"], len(sentences), speakers)
    return out


async def run_in_subprocess(path: str, should_stop: StopFn = None,
                            on_progress: Optional[Callable[[str, float], None]] = None,
                            cmd: Optional[List[str]] = None) -> Dict[str, Any]:
    """在子行程執行 refine()（見檔頭「執行方式」）。should_stop() 每秒檢查一次，成立就終止子行程，
    回傳 stopped=True 與已完成的部分（辨識完就有逐字稿，只是沒分人）。cmd 只給測試替換子行程用。"""
    argv = cmd or ["nice", "-n", str(CHILD_NICE), sys.executable, "-m", "refine_transcript", path]
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, limit=CHILD_LINE_LIMIT,
    )
    partial: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    stopped = False
    stderr_tail: "collections.deque[str]" = collections.deque(maxlen=20)

    async def read_stderr() -> None:
        async for line in proc.stderr:
            stderr_tail.append(line.decode("utf-8", "replace").rstrip())

    async def watch_stop() -> None:
        nonlocal stopped
        while proc.returncode is None:
            await asyncio.sleep(STOP_POLL_S)
            if should_stop is not None and should_stop() and proc.returncode is None:
                stopped = True
                logger.info("[refine] recording started, terminating child %d", proc.pid)
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), STOP_GRACE_S)
                except asyncio.TimeoutError:
                    proc.kill()
                except ProcessLookupError:
                    pass
                return

    err_task = asyncio.create_task(read_stderr())
    stop_task = asyncio.create_task(watch_stop())
    try:
        async for raw in proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                logger.warning("[refine] unexpected child output: %r", raw[:200])
                continue
            if "progress" in msg and on_progress is not None:
                on_progress(*msg["progress"])
            elif "partial" in msg:
                partial = msg["partial"]
            elif "result" in msg:
                result = msg["result"]
            elif "error" in msg:
                error = msg["error"]
        await proc.wait()
    finally:
        stop_task.cancel()
        if proc.returncode is None:  # 上層被取消：不留孤兒行程
            proc.kill()
            await proc.wait()
        await asyncio.gather(stop_task, err_task, return_exceptions=True)

    if stopped:
        out = dict(partial) if partial else {"engine": ENGINE_LABEL, **pipeline_labels(), "phase": "asr", "transcript": "",
                                              "speakers": 0, "sentences": []}
        out["stopped"] = True
        return out
    if error:
        raise RefineError(error)
    if result is None or proc.returncode != 0:
        detail = " | ".join(list(stderr_tail)[-3:])
        raise RefineError(f"處理程序異常結束（exit {proc.returncode}）：{detail}")
    return result


def _cli(argv: List[str]) -> int:
    """子行程入口：python3 -m refine_transcript <錄音檔>。stdout 每行一個 JSON：progress／partial／result／error。"""
    if len(argv) != 2:
        print("usage: python3 -m refine_transcript <audio file>", file=sys.stderr)
        return 2

    def emit(obj: Dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    try:
        result = refine(argv[1], on_progress=lambda phase, frac: emit({"progress": [phase, round(frac, 3)]}),
                        on_partial=lambda part: emit({"partial": part}))
    except RefineError as e:
        emit({"error": str(e)})
        return 1
    emit({"result": result})
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    sys.exit(_cli(sys.argv))
