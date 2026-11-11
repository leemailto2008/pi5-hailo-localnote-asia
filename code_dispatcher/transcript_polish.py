# -*- coding: utf-8 -*-
"""
transcript_polish.py — 逐字稿 LLM 潤稿 (2026-11-10，待辦 #11；2026-11-11 改版)。

兩種模式：
  fix      修同音字與漏字。模型輸出校對後的全文，程式用 difflib 對齊原文，只收同音字替換（pypinyin 拼音相同）
           與 1 字補字，其餘一律保留原文（見 accept_homophone_edits）。
  rewrite  整段重新潤稿。模型輸出整段改寫後文字，較完整，但較容易改掉原意，只能手動觸發。

2026-11-11 GS3 實錄量測（tools：.cc_scratch/pe/polish_eval.py；CER／不計數字 CER，台灣用字修正後的稿為基準）：
  - 舊 fix（模型輸出 [{"from","to"}] 修改清單）：Hailo qwen3:1.7b 與 CPU qwen2.5:3b 幾乎都回空清單，CER 不變。
  - 新 fix（輸出全文）：Hailo qwen3:1.7b 照抄原文（0 處修改）；CPU qwen2.5:3b 只收同音字與 1 字補字時
    SenseVoice 稿 實錄 5 分 0.1791／0.0757 → 0.1761／0.0721、10 分 0.1890／0.0645 → 0.1825／0.0568，事實召回不變；
    Hailo 即時稿 5 分 0.2206／0.1442 → 0.2176／0.1407。
  - rewrite（Hailo qwen3:1.7b）：即時稿 CER 不變（只改標點）。
  → 潤稿改用 CPU Ollama 優先（llm_backend.cpu_first_backends），Hailo 為備援；只在錄音後執行，
    錄音一開始就關掉串流（Ollama 隨即停止生成），剩下的段落保留原文。

處理方式：
  - 長逐字稿切成數段 (每段約 MAX_CHUNK_CHARS 字)，依序送 LLM，避免小模型上下文過長。
  - 單段 LLM 失敗 → 保留該段原文；rewrite 輸出長度異常或數字被改 → 保留原文。
  - 只透過 llm_backend.aiter_chat_stream 呼叫模型。
"""

import contextlib
import difflib
import logging
import os
import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from llm_backend import LLMError, aiter_chat_stream
from summary_utils import to_taiwan_traditional

logger = logging.getLogger(__name__)

MODES = ("fix", "rewrite")
MAX_CHUNK_CHARS = 600
# cpu = CPU Ollama (qwen2.5:3b) 優先、Hailo 備援；hailo = Hailo 優先。量測見檔頭。
POLISH_BACKEND = os.environ.get("PI5_POLISH_BACKEND", "cpu").strip().lower()
FIX_MAX_INSERT = 1    # fix 補字（漏字）一次最多幾個字；更多視為加內容，保留原文
REQUEST_TIMEOUT_SEC = 120.0
OUTPUT_MIN_TOKENS_PER_SEC = 4.0  # 估整段輸出逾時用：Hailo qwen3:1.7b 約 4.5 tok/s、CPU qwen2.5:3b 約 6 tok/s

_CUT_CHARS = "。！？!?.；;，,"
_LABEL_RE = re.compile(r"^說話人\d+：", re.M)   # 高精度逐字稿每段開頭的說話人標籤，潤稿不能動
_CJK_RE = re.compile(r"^[\u4e00-\u9fff]+$")

FIX_SYSTEM = "你是逐字稿校對工具。只輸出校對後的逐字稿全文，不輸出任何說明。"
REWRITE_SYSTEM = "你是會議逐字稿整理工具。只輸出整理後的文字，不輸出任何說明或標題。"


def _find_cut(line: str, max_chars: int) -> int:
    """超過 max_chars 的單行，優先在後半段的標點後面切開；找不到就硬切。"""
    window = line[:max_chars]
    best = max((window.rfind(c) for c in _CUT_CHARS), default=-1)
    if best >= max_chars // 2:
        return best + 1
    return max_chars


def split_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """依換行切成段落，相鄰段落合併到不超過 max_chars；空行略過。"""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    pieces: List[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        while len(line) > max_chars:
            cut = _find_cut(line, max_chars)
            pieces.append(line[:cut])
            line = line[cut:].lstrip()
        if line:
            pieces.append(line)

    chunks: List[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + 1 + len(piece) > max_chars:
            chunks.append(buf)
            buf = piece
        else:
            buf = f"{buf}\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return chunks


def build_fix_prompt(chunk: str) -> str:
    return (
        "以下是語音辨識 (ASR) 的逐字稿片段，裡面有同音字誤認與漏字。\n"
        "請輸出校對後的全文：只把錯字改成正確的字、補上明顯漏掉的字；其他文字與標點一律照抄。\n"
        "不要刪減內容、不要改寫句子、不要加標題或說明。\n\n"
        f"逐字稿片段：\n{chunk}"
    )


def build_rewrite_prompt(chunk: str) -> str:
    return (
        "以下是語音辨識的逐字稿片段。請在不增加資訊的前提下，把口語贅詞與明顯錯字整理成通順的書面語。\n"
        "規則：保留所有人名、數字、日期、專有名詞與決議內容；使用原文的語言，不要翻譯；只輸出整理後的文字。\n\n"
        f"逐字稿片段：\n{chunk}"
    )


def protected_spans(text: str) -> List[Tuple[int, int]]:
    """說話人標籤（「說話人1：」）的位置；潤稿的修改碰到就不收。"""
    return [(m.start(), m.end()) for m in _LABEL_RE.finditer(text)]


def _touches(i1: int, i2: int, spans: Sequence[Tuple[int, int]]) -> bool:
    """原文 [i1, i2) 的修改是否碰到 spans；i1 == i2 是插入點，落在標籤內部才算。"""
    if i2 > i1:
        return any(i1 < b and a < i2 for a, b in spans)
    return any(a < i1 < b for a, b in spans)


def sounds_alike(a: str, b: str) -> bool:
    """兩段中文字數相同、每個字的拼音（不計聲調，pypinyin）都一樣 → 同音字。"""
    from pypinyin import Style, lazy_pinyin
    return len(a) == len(b) and lazy_pinyin(a, style=Style.NORMAL) == lazy_pinyin(b, style=Style.NORMAL)


def accept_homophone_edits(src: str, dst: str,
                           protected: Sequence[Tuple[int, int]] = ()) -> Tuple[str, Dict[str, int]]:
    """把模型的校對全文 dst 對齊原文 src（difflib），只收「修同音字與漏字」，其餘位置保留原文：
      - 替換：兩邊都是中文、字數相同、拼音（不計聲調）相同；
      - 補字：≤ FIX_MAX_INSERT 個中文字；
      - 刪字、改數字或標點、改寫一律不收；protected 範圍（說話人標籤）不動。
    11-11 量測（CPU qwen2.5:3b 的校對全文；SenseVoice 稿）：只收 ≤ 4 字的小修改時，實錄 10 分事實召回 0.879 → 0.871
    （「吳副理→吳部長」「週五前→週前」這類改錯）；改成只收同音字與 1 字補字，0.879 不變、CER 0.189 → 0.1825。
    回傳 (新文字, {"accepted": 處數, "rejected": 處數})。"""
    out: List[str] = []
    stats = {"accepted": 0, "rejected": 0}
    pos = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, src, dst, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append(src[pos:i1])
        old, new = src[i1:i2], dst[j1:j2]
        if not old.strip() and not new.strip():
            ok = False                      # 只差空白／換行：保留原文排版
        elif tag == "replace":
            ok = bool(_CJK_RE.match(old) and _CJK_RE.match(new)) and sounds_alike(old, new)
        elif tag == "insert":
            ok = len(new) <= FIX_MAX_INSERT and bool(_CJK_RE.match(new))
        else:
            ok = False
        ok = ok and not _touches(i1, i2, protected)
        out.append(new if ok else old)
        if old.strip() or new.strip():
            stats["accepted" if ok else "rejected"] += 1
        pos = i2
    out.append(src[pos:])
    return "".join(out), stats


def diff_segments(src: str, dst: str) -> List[List[str]]:
    """網頁標色用的字元級差異 (difflib)。回傳 [[op, text, orig], ...]，依序接起來的 text (del 除外) 就是 dst：
    eq 相同；rep 替換 (text 新字、orig 原字，修同音字)；ins 補上的字 (修漏字)；del 刪掉的字 (text 是原字)。
    autojunk 關掉：中文常用字出現次數多，開著會被當成雜訊而對不齊。"""
    out: List[List[str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, src, dst, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(["eq", dst[j1:j2], ""])
        elif tag == "replace":
            out.append(["rep", dst[j1:j2], src[i1:i2]])
        elif tag == "insert":
            out.append(["ins", dst[j1:j2], ""])
        else:
            out.append(["del", src[i1:i2], ""])
    return out


def _rewrite_length_ok(src: str, out: str) -> bool:
    """擋掉模型截斷或亂加內容：輸出長度須落在原文的 0.5 倍到 1.5 倍 (+20 字) 之間。"""
    return 0.5 * len(src) <= len(out) <= 1.5 * len(src) + 20


_NUMBER_RE = re.compile(r"\d+(?:[.:/]\d+)*")


def _rewrite_numbers_ok(src: str, out: str) -> bool:
    """rewrite 不得改動、刪掉或新增阿拉伯數字（日期、金額、數量、百分比）。

    STT 輸出的數字幾乎都是阿拉伯數字，數字串的多重集合必須完全相同。
    模型把「100臺」改寫成「一百臺」也算不同，該段保留原文（寧可不潤，也不改到事實）。
    中文數字不在檢查範圍內。
    """
    return Counter(_NUMBER_RE.findall(src)) == Counter(_NUMBER_RE.findall(out))


async def _complete(prompt: str, system: str, temperature: float, num_predict: int,
                    stats: Dict[str, Any], should_stop: Optional[Callable[[], bool]]) -> Optional[str]:
    """串流取得模型輸出。should_stop() 成立就關掉串流（Ollama 隨即停止生成）並回傳 None。"""
    parts: List[str] = []
    stream = aiter_chat_stream(
        prompt, system=system, temperature=temperature, num_predict=num_predict,
        timeout=max(REQUEST_TIMEOUT_SEC, 30.0 + num_predict / OUTPUT_MIN_TOKENS_PER_SEC),
        hailo_retries=1, cpu_first=POLISH_BACKEND == "cpu",
    )
    async with contextlib.aclosing(stream):
        async for token, _done, backend in stream:
            stats["backend"] = backend.label
            if should_stop is not None and should_stop():
                return None
            parts.append(token)
    return "".join(parts)


def _strip_echoed_header(out: str) -> str:
    """模型偶爾把提示裡的「逐字稿片段：」也輸出來。"""
    return re.sub(r"^\s*(逐字稿片段|校對後)[：:]\s*", "", out)


async def _run_fix(chunk: str, stats: Dict[str, Any], should_stop: Optional[Callable[[], bool]]) -> Optional[str]:
    raw = await _complete(build_fix_prompt(chunk), FIX_SYSTEM, 0.0, max(128, 2 * len(chunk)), stats, should_stop)
    if raw is None:
        return None
    out = to_taiwan_traditional(_strip_echoed_header((raw or "").strip()))
    new_chunk, edits = accept_homophone_edits(chunk, out, protected_spans(chunk))
    stats["accepted_edits"] += edits["accepted"]
    stats["rejected_edits"] += edits["rejected"]
    return new_chunk


async def _run_rewrite(chunk: str, stats: Dict[str, Any], should_stop: Optional[Callable[[], bool]]) -> Optional[str]:
    raw = await _complete(build_rewrite_prompt(chunk), REWRITE_SYSTEM, 0.2, max(128, 2 * len(chunk)), stats, should_stop)
    if raw is None:
        return None
    out = to_taiwan_traditional(_strip_echoed_header((raw or "").strip()))
    if not _rewrite_length_ok(chunk, out):
        stats["rejected_chunks"] += 1
        return chunk
    if not _rewrite_numbers_ok(chunk, out):
        stats["fact_rejected_chunks"] += 1
        return chunk
    return out


async def polish_transcript(
    text: str,
    mode: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    source: str = "live",
) -> Dict[str, Any]:
    """逐段潤稿。單段 LLM 失敗時保留原文並計入 failed_chunks，不中斷其他段。

    on_progress(done, total)：每段處理完呼叫一次。
    should_stop()：每段開始前與生成中都檢查；回傳 True 就停下（生成中的那段也保留原文），結果帶 stopped=True。
    （錄音一開始就要讓出 CPU/NPU，見 CLAUDE.md 重點一。）
    source：潤稿來源（live＝完整逐字稿、refine＝高精度逐字稿），只記在結果裡給網頁顯示。
    """
    if mode not in MODES:
        raise ValueError(f"unknown polish mode: {mode}")
    if mode == "fix":
        try:
            import pypinyin  # noqa: F401  同音判斷要用
        except ImportError as e:
            raise RuntimeError("缺少 pypinyin（python3 -m pip install --user --break-system-packages pypinyin）") from e
    chunks = split_chunks(text)
    stats: Dict[str, Any] = {
        "chunks": len(chunks),
        "failed_chunks": 0,
        "rejected_chunks": 0,
        "fact_rejected_chunks": 0,
        "accepted_edits": 0,
        "rejected_edits": 0,
        "stopped": False,
        "backend": None,
    }
    parts: List[str] = []
    segments: List[List[str]] = []
    counts = {"rep": 0, "ins": 0, "del": 0}

    def add_segments(src: str, dst: str) -> None:
        if segments:
            segments.append(["eq", "\n\n", ""])
        for seg in diff_segments(src, dst):
            segments.append(seg)
            if seg[0] in counts:
                counts[seg[0]] += 1

    for idx, chunk in enumerate(chunks, start=1):
        new_chunk: Optional[str] = None
        if not (should_stop is not None and should_stop()):
            try:
                if mode == "fix":
                    new_chunk = await _run_fix(chunk, stats, should_stop)
                else:
                    new_chunk = await _run_rewrite(chunk, stats, should_stop)
            except LLMError as e:
                logger.warning("[polish] chunk %d/%d failed, keep original: %s", idx, len(chunks), e)
                stats["failed_chunks"] += 1
                new_chunk = chunk
        if new_chunk is None:
            logger.info("[polish] stopped at chunk %d/%d", idx, len(chunks))
            stats["stopped"] = True
            parts.extend(chunks[idx - 1:])
            for rest in chunks[idx - 1:]:
                add_segments(rest, rest)
            break
        parts.append(new_chunk)
        add_segments(chunk, new_chunk)
        if on_progress is not None:
            on_progress(idx, len(chunks))
    return {"mode": mode, "source": source, "polished": "\n\n".join(parts), "changes": [],
            "segments": segments, "diff_counts": counts, **stats}
