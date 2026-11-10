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
限制：CPU 推論，只能在錄音結束後跑；處理中每隔幾秒音訊檢查 should_stop()，錄音一開始就停（CLAUDE.md 重點一）。
模型：PI5_SHERPA_MODEL_DIR（預設 /home/pi/models/sherpa），安裝見 tools/ci/setup_sherpa_models.sh。
"""

import logging
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from summary_utils import to_taiwan_traditional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MODEL_DIR = os.environ.get("PI5_SHERPA_MODEL_DIR", "/home/pi/models/sherpa")
NUM_THREADS = int(os.environ.get("PI5_SHERPA_THREADS", "4"))
# 分群門檻：sherpa 預設 0.5 在 15 分鐘合成會議切出 8–10 人（實際 4 人）；0.7 在 5／10／15／30 分鐘都找到 4–5 人。
CLUSTER_THRESHOLD = 0.7
# 句子落在分段的空隙裡（分段模型會把句中停頓切掉）時，借用 1 秒內最近的說話人。
NEAREST_TURN_MAX_GAP_S = 1.0
DECODE_TIMEOUT_S = 900
MODEL_FILES = {
    "asr": "sensevoice_small_int8.onnx",
    "tokens": "sensevoice_tokens.txt",
    "vad": "silero_vad.onnx",
    "segmentation": "pyannote_segmentation_3_0.onnx",
    "embedding": "campplus_zh_cn_common.onnx",
}
ENGINE_LABEL = "SenseVoiceSmall int8 + CAM++（sherpa-onnx，CPU）"
_PUNCT = "。！？!?，,、；;：:…"

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


def transcribe(samples, should_stop: StopFn = None, on_progress: ProgressFn = None) -> Optional[List[Sentence]]:
    """VAD 切句後逐句辨識。被 should_stop 中止時回傳 None。"""
    import sherpa_onnx

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=model_path("asr"), tokens=model_path("tokens"), num_threads=NUM_THREADS, language="zh", use_itn=True
    )
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = model_path("vad")
    cfg.silero_vad.min_silence_duration = 0.25
    cfg.silero_vad.min_speech_duration = 0.25
    cfg.silero_vad.max_speech_duration = 20
    cfg.sample_rate = SAMPLE_RATE
    cfg.num_threads = 1
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)

    sentences: List[Sentence] = []

    def drain() -> None:
        while not vad.empty():
            seg = vad.front
            stream = recognizer.create_stream()
            stream.accept_waveform(SAMPLE_RATE, seg.samples)
            recognizer.decode_stream(stream)
            text = stream.result.text.strip()
            if text:
                start = seg.start / SAMPLE_RATE
                sentences.append(Sentence(start, start + len(seg.samples) / SAMPLE_RATE, text))
            vad.pop()

    window = cfg.silero_vad.window_size
    check_every = window * 200  # 約每 6.4 秒音訊檢查一次中止與進度
    total = len(samples)
    for i in range(0, total, window):
        vad.accept_waveform(samples[i:i + window])
        drain()
        if i % check_every == 0:
            if should_stop is not None and should_stop():
                return None
            if on_progress is not None:
                on_progress(i / total)
    vad.flush()
    drain()
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


def _join(texts: Sequence[str]) -> str:
    out = ""
    for t in texts:
        if out and out[-1] not in _PUNCT:
            out += "，"
        out += t
    return out


def format_transcript(sentences: Sequence[Sentence]) -> Tuple[str, int]:
    """同一人連續的句子併成一行「說話人N：…」；N 依第一次出現的順序。回傳 (逐字稿, 說話人數)。"""
    order: Dict[int, int] = {}
    lines: List[str] = []
    cur: Any = object()
    buf: List[str] = []

    def flush() -> None:
        if buf:
            label = f"說話人{order[cur]}" if cur is not None else "說話人?"
            lines.append(f"{label}：{_join(buf)}")

    if all(s.speaker is None for s in sentences):
        return _join([s.text for s in sentences]), 0
    for s in sentences:
        if s.speaker is not None and s.speaker not in order:
            order[s.speaker] = len(order) + 1
        if s.speaker != cur:
            flush()
            buf = []
            cur = s.speaker
        buf.append(s.text)
    flush()
    return "\n".join(lines), len(order)


def refine(path: str, should_stop: StopFn = None,
           on_progress: Optional[Callable[[str, float], None]] = None) -> Dict[str, Any]:
    """整段流程（阻塞，請在執行緒裡跑）。回傳 dict；stopped=True 表示中途被錄音打斷。"""
    reason = check_available()
    if reason:
        raise RefineError(reason)

    def report(phase: str, frac: float) -> None:
        if on_progress is not None:
            on_progress(phase, max(0.0, min(1.0, frac)))

    report("load", 0.0)
    samples = load_audio(path)
    audio_s = len(samples) / SAMPLE_RATE
    out: Dict[str, Any] = {"engine": ENGINE_LABEL, "audio_s": round(audio_s, 1), "stopped": False}

    t0 = time.time()
    sentences = transcribe(samples, should_stop, lambda f: report("asr", f))
    out["asr_s"] = round(time.time() - t0, 1)
    if sentences is None:
        out.update(stopped=True, phase="asr", transcript="", speakers=0, sentences=[])
        return out
    for s in sentences:
        s.text = to_taiwan_traditional(s.text)

    t1 = time.time()
    turns = diarize(samples, should_stop, lambda f: report("diarize", f))
    out["diarize_s"] = round(time.time() - t1, 1)
    if turns is None:
        # 分說話人被打斷：仍交出辨識結果（不分人）。
        text, _ = format_transcript(sentences)
        out.update(stopped=True, phase="diarize", transcript=text, speakers=0,
                   sentences=[asdict(s) for s in sentences])
        return out

    assign_speakers(sentences, turns)
    text, speakers = format_transcript(sentences)
    out.update(transcript=text, speakers=speakers, sentences=[asdict(s) for s in sentences])
    logger.info("[refine] %.0f s audio: asr %.1f s, diarize %.1f s, %d sentences, %d speakers",
                audio_s, out["asr_s"], out["diarize_s"], len(sentences), speakers)
    return out
