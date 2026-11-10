# -*- coding: utf-8 -*-
"""
transcript_polish.py — 逐字稿 LLM 潤稿 (2026-11-10，待辦 #11)。

兩種模式：
  fix      修同音字與漏字。模型只輸出 [{"from": ..., "to": ...}] 修改清單，由程式做精確字串替換。
           模型看不到自由改寫的空間，風險較低，可以較常用。
  rewrite  整段重新潤稿。模型輸出整段改寫後文字，較完整，但較容易改掉原意，只能手動觸發。

處理方式：
  - 長逐字稿切成數段 (每段約 MAX_CHUNK_CHARS 字)，依序送 LLM，避免小模型上下文過長與 NPU 排隊過久。
  - 單段 LLM 失敗 → 保留該段原文；rewrite 輸出長度異常 → 保留原文；fix 輸出格式錯誤 → 該段不套用修改。
  - 只透過 llm_backend.achat_complete 呼叫模型 (Hailo 優先，失敗退 CPU)。
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from llm_backend import LLMError, achat_complete

logger = logging.getLogger(__name__)

MODES = ("fix", "rewrite")
MAX_CHUNK_CHARS = 600
MAX_FIX_ITEMS_PER_CHUNK = 30
MIN_FIX_FROM_CHARS = 2
MAX_FIX_FROM_CHARS = 40
REQUEST_TIMEOUT_SEC = 120.0

_CUT_CHARS = "。！？!?.；;，,"
_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

FIX_SYSTEM = "你是逐字稿校對工具。只輸出 JSON，不輸出任何說明文字。"
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
        "以下是語音辨識 (ASR) 的逐字稿片段。請只找出明顯的錯誤，例如同音字誤認、專有名詞或術語誤寫、明顯漏字。\n"
        "規則：\n"
        "1. 只在有把握時才列出；不確定就不要列。不要改寫語句、不要潤飾、不要增刪內容。\n"
        f"2. 每筆 from 必須是原文中逐字出現的子字串（標點與空白需一致），長度不超過 {MAX_FIX_FROM_CHARS} 字。\n"
        "3. to 是修正後的文字。\n"
        "4. 只輸出 JSON 陣列，格式為 [{\"from\": \"...\", \"to\": \"...\"}]；沒有需要修正的就輸出 []。\n\n"
        f"逐字稿片段：\n{chunk}"
    )


def build_rewrite_prompt(chunk: str) -> str:
    return (
        "以下是語音辨識的逐字稿片段。請在不增加資訊的前提下，把口語贅詞與明顯錯字整理成通順的書面語。\n"
        "規則：保留所有人名、數字、日期、專有名詞與決議內容；使用原文的語言，不要翻譯；只輸出整理後的文字。\n\n"
        f"逐字稿片段：\n{chunk}"
    )


def parse_fix_list(raw: str) -> Optional[List[Dict[str, str]]]:
    """從模型輸出取出修改清單。無法解析回傳 None；解析成功但個別項目不合規則略過該項。"""
    if not raw:
        return None
    match = _ARRAY_RE.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, list):
        return None

    fixes: List[Dict[str, str]] = []
    for item in data[:MAX_FIX_ITEMS_PER_CHUNK]:
        if not isinstance(item, dict):
            continue
        src, dst = item.get("from"), item.get("to")
        if not isinstance(src, str) or not isinstance(dst, str):
            continue
        if len(src) < MIN_FIX_FROM_CHARS or len(src) > MAX_FIX_FROM_CHARS or src == dst:
            continue
        fixes.append({"from": src, "to": dst})
    return fixes


def apply_fixes(text: str, fixes: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, Any]]]:
    """逐筆做精確字串替換；原文找不到的項目略過。回傳 (新文字, 實際套用的紀錄)。"""
    applied: List[Dict[str, Any]] = []
    for fix in fixes:
        count = text.count(fix["from"])
        if count == 0:
            continue
        text = text.replace(fix["from"], fix["to"])
        applied.append({"from": fix["from"], "to": fix["to"], "count": count})
    return text, applied


def _rewrite_length_ok(src: str, out: str) -> bool:
    """擋掉模型截斷或亂加內容：輸出長度須落在原文的 0.5 倍到 1.5 倍 (+20 字) 之間。"""
    return 0.5 * len(src) <= len(out) <= 1.5 * len(src) + 20


async def _run_fix(chunk: str, stats: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    raw, backend = await achat_complete(
        build_fix_prompt(chunk),
        system=FIX_SYSTEM,
        temperature=0.0,
        num_predict=300,
        timeout=REQUEST_TIMEOUT_SEC,
        hailo_retries=1,
    )
    stats["backend"] = backend.label
    fixes = parse_fix_list(raw)
    if fixes is None:
        stats["parse_errors"] += 1
        return chunk, []
    return apply_fixes(chunk, fixes)


async def _run_rewrite(chunk: str, stats: Dict[str, Any]) -> str:
    raw, backend = await achat_complete(
        build_rewrite_prompt(chunk),
        system=REWRITE_SYSTEM,
        temperature=0.2,
        num_predict=max(128, 2 * len(chunk)),
        timeout=REQUEST_TIMEOUT_SEC,
        hailo_retries=1,
    )
    stats["backend"] = backend.label
    out = (raw or "").strip()
    if not _rewrite_length_ok(chunk, out):
        stats["rejected_chunks"] += 1
        return chunk
    return out


async def polish_transcript(text: str, mode: str) -> Dict[str, Any]:
    """逐段潤稿。單段 LLM 失敗時保留原文並計入 failed_chunks，不中斷其他段。"""
    if mode not in MODES:
        raise ValueError(f"unknown polish mode: {mode}")
    chunks = split_chunks(text)
    stats: Dict[str, Any] = {
        "chunks": len(chunks),
        "failed_chunks": 0,
        "rejected_chunks": 0,
        "parse_errors": 0,
        "backend": None,
    }
    parts: List[str] = []
    changes: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        try:
            if mode == "fix":
                new_chunk, applied = await _run_fix(chunk, stats)
                changes.extend(applied)
            else:
                new_chunk = await _run_rewrite(chunk, stats)
        except LLMError as e:
            logger.warning("[polish] chunk %d/%d failed, keep original: %s", idx, len(chunks), e)
            stats["failed_chunks"] += 1
            new_chunk = chunk
        parts.append(new_chunk)
    return {"mode": mode, "polished": "\n\n".join(parts), "changes": changes, **stats}
