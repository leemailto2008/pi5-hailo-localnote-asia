"""完整逐字稿翻譯（中 ↔ 英）背景工作（2026-11-19，同事回報「Translate to Mandarin／English 只翻紀要」）。

紀要的翻譯（/api/translate）很短、同步回應；完整逐字稿 30 分鐘約 1 萬字、4 小時約 8 萬字，一次請求翻不完，
所以比照潤稿做成背景工作（main.py 的 SingleJob「translate」），前端輪詢 GET /api/translate_transcript 逐段顯示。

做法：
- 逐字稿依行（高精度稿每行一位說話人「說話人N：…」）再依句末標點切成小單位，每個請求 ≤ UNIT_CHARS 個字、
  單位編號「N| 原文」，模型照編號輸出；對不上的單位單獨重翻一次，還是不行就保留原文（不讓內容消失）。
- 說話人標籤不送模型：翻成英文時換成「Speaker N:」，翻成中文時保留「說話人N：」。
- 已經是目標語言的單位（中英夾雜會議裡整句英文）直接照抄，不送模型。
- 兩路同時翻：Hailo（NPU）與 CPU Ollama 各拿下一段，結果依原順序組回；開始錄音時 CPU 那一路立刻停、
  整個工作在段落之間停下（state=stopped，已翻的保留），符合錄音中不跑 CPU 推論（CLAUDE.md 重點一）。
- 翻成中文的結果經 OpenCC s2twp（台灣用字）。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from llm_backend import LLMError, aiter_chat_stream

logger = logging.getLogger(__name__)

UNIT_CHARS = 140          # 每個翻譯單位最多幾個字（太長的句子再切）
CHUNK_CHARS = 360         # 每個請求的原文字數上限：Hailo qwen3:1.7b 約 4.5 tok/s，中翻英一段約 60 s
REQUEST_TIMEOUT_SEC = 180.0
POLL_SEC = 0.5            # 檢查「開始錄音了沒」的間隔

_LABEL_RE = re.compile(r"^(說話人(\d+)[：:]|Speaker\s*(\d+)\s*[:：])\s*")
_SENT_END_RE = re.compile(r"(?<=[。！？!?；;])|(?<=[.](?=\s))")
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_NUM_LINE_RE = re.compile(r"^\s*(\d+)\s*[|｜.、:：)）]\s*(.*)$")

SYSTEM = {
    "en": ("You are a professional interpreter. Translate each numbered line of a meeting transcript into natural English. "
           "Keep the same numbers, one output line per input line, written as \"N| translation\". "
           "Keep names, company names, product names and numbers as they are. Output only the numbered lines."),
    "zh": ("你是專業口譯員。把會議逐字稿每一行編號的句子翻成通順的台灣繁體中文。"
           "每一行輸入對應一行輸出，格式「N| 翻譯」，編號照原文。人名、公司名、產品名與數字照原文。只輸出編號的各行。"),
}


def in_target_language(text: str, target: str) -> bool:
    """這個單位已經是目標語言 (照抄，不送模型)。英文：沒有中文字；中文：中文字不少於英文字母的一半。"""
    cjk, latin = len(_CJK_RE.findall(text)), len(_LATIN_RE.findall(text))
    if target == "en":
        return cjk == 0
    return cjk > 0 and cjk * 2 >= latin


def _split_long(sentence: str, limit: int) -> List[str]:
    out = []
    while len(sentence) > limit:
        window = sentence[:limit]
        cut = max(window.rfind(c) for c in "，,、 ")
        cut = cut + 1 if cut >= limit // 2 else limit
        out.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    if sentence:
        out.append(sentence)
    return out


def parse_lines(text: str) -> List[Tuple[str, List[str]]]:
    """逐字稿 → [(說話人編號或空字串, [單位…])]，每個元素是原文的一行。"""
    rows: List[Tuple[str, List[str]]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LABEL_RE.match(line)
        spk = (m.group(2) or m.group(3)) if m else ""
        body = line[m.end():] if m else line
        units = [u for s in _SENT_END_RE.split(body) if s.strip() for u in _split_long(s.strip(), UNIT_CHARS)]
        if units:
            rows.append((spk, units))
    return rows


def group_chunks(units: Sequence[Tuple[int, str]], limit: Optional[int] = None) -> List[List[Tuple[int, str]]]:
    """要送模型的 (單位索引, 原文) 依序合成請求，每個請求原文 ≤ limit 字 (預設 CHUNK_CHARS)。"""
    limit = CHUNK_CHARS if limit is None else limit
    chunks: List[List[Tuple[int, str]]] = []
    buf: List[Tuple[int, str]] = []
    size = 0
    for idx, u in units:
        if buf and size + len(u) > limit:
            chunks.append(buf)
            buf, size = [], 0
        buf.append((idx, u))
        size += len(u)
    if buf:
        chunks.append(buf)
    return chunks


def build_prompt(chunk: Sequence[Tuple[int, str]], target: str) -> str:
    lines = "\n".join(f"{n}| {u}" for n, (_i, u) in enumerate(chunk, 1))
    head = "Translate into English:" if target == "en" else "翻成繁體中文："
    return f"{head}\n{lines}"


def parse_output(out: str, n: int) -> Dict[int, str]:
    """模型輸出 → {第幾行 (1 起算): 翻譯}；編號超出範圍、空白的行不收。"""
    got: Dict[int, str] = {}
    for line in (out or "").splitlines():
        m = _NUM_LINE_RE.match(line)
        if not m:
            continue
        k, t = int(m.group(1)), m.group(2).strip()
        if 1 <= k <= n and t and k not in got:
            got[k] = t
    return got


def assemble(rows: Sequence[Tuple[str, List[str]]], done: Dict[int, str], target: str,
             upto: Optional[int] = None) -> str:
    """把翻好的單位依原本的行組回去 (upto：只組到第幾個單位，逐段顯示用；沒翻到的單位保留原文)。"""
    out, idx = [], 0
    sep = " " if target == "en" else ""
    for spk, units in rows:
        if upto is not None and idx >= upto:
            break
        parts = []
        for u in units:
            if upto is not None and idx >= upto:
                break
            parts.append(done.get(idx, u))
            idx += 1
        label = (f"Speaker {spk}: " if target == "en" else f"說話人{spk}：") if spk else ""
        out.append(label + sep.join(p.strip() for p in parts))
    return "\n".join(out)


async def _complete(prompt: str, target: str, num_predict: int, *, hailo_only: bool, cpu_first: bool,
                    should_stop: Callable[[], bool]) -> Optional[str]:
    """串流取得翻譯；should_stop() 成立就關掉串流 (Ollama 隨即停止生成) 回傳 None。
    CPU 預填一段約 40 s 沒有 token，所以另外每 POLL_SEC 秒檢查一次 (同 meeting_minutes.stream_map_notes_cpu)。"""
    async def consume() -> str:
        parts: List[str] = []
        stream = aiter_chat_stream(prompt, system=SYSTEM[target], temperature=0.1, num_predict=num_predict,
                                   timeout=REQUEST_TIMEOUT_SEC, hailo_retries=1, hailo_only=hailo_only, cpu_first=cpu_first)
        async with contextlib.aclosing(stream):
            async for token, _done, _backend in stream:
                parts.append(token)
        return "".join(parts)

    task = asyncio.ensure_future(consume())
    while not task.done():
        await asyncio.wait({task}, timeout=POLL_SEC)
        if not task.done() and should_stop():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            return None
    return task.result()


def _num_predict(chunk: Sequence[Tuple[int, str]], target: str) -> int:
    chars = sum(len(u) for _i, u in chunk)
    # 中翻英：每個中文字約 1.2 token；英翻中：每個英文字元約 0.5 token；加上編號
    est = chars * (1.3 if target == "en" else 0.7) + 6 * len(chunk)
    return int(min(900, max(120, est)))


async def translate_transcript(text: str, target: str,
                               on_progress: Optional[Callable[[int, int, str], None]] = None,
                               should_stop: Callable[[], bool] = lambda: False,
                               use_cpu: bool = True) -> Dict[str, Any]:
    """翻譯完整逐字稿。on_progress(已翻段數, 總段數, 目前連續翻好的部分)；回傳 {text, chunks, kept, fallback_units, stopped}。"""
    if target not in SYSTEM:
        raise ValueError("target 必須是 en 或 zh")
    rows = parse_lines(text)
    flat = [u for _spk, units in rows for u in units]
    done: Dict[int, str] = {}
    todo = []
    for i, u in enumerate(flat):
        if in_target_language(u, target):
            done[i] = u
        else:
            todo.append((i, u))
    chunks = group_chunks(todo)
    total = len(chunks)
    finished = [False] * total
    stats = {"fallback_units": 0, "stopped": False}
    queue = list(range(total))
    lock = asyncio.Lock()

    def prefix_upto() -> int:
        """從頭算起連續翻好的單位數 (逐段顯示時不跳著出現)。"""
        k = 0
        for c, ok in enumerate(finished):
            if not ok:
                return chunks[c][0][0] if chunks[c] else k
            k = chunks[c][-1][0] + 1
        return len(flat)

    def localize(t: str) -> str:
        if target != "zh":
            return t
        from summary_utils import to_taiwan_traditional
        return to_taiwan_traditional(t)

    def report() -> None:
        if on_progress:
            on_progress(sum(finished), total, localize(assemble(rows, done, target, upto=prefix_upto())))

    async def translate_chunk(c: int, *, hailo_only: bool, cpu_first: bool) -> bool:
        chunk = chunks[c]
        out = await _complete(build_prompt(chunk, target), target, _num_predict(chunk, target),
                              hailo_only=hailo_only, cpu_first=cpu_first, should_stop=should_stop)
        if out is None:
            return False
        got = parse_output(out, len(chunk))
        for n, (idx, src) in enumerate(chunk, 1):
            if n in got:
                done[idx] = got[n]
                continue
            # 對不上的單位單獨重翻一次 (模型偶爾合併或跳過一行)；還是不行就保留原文
            one = await _complete(build_prompt([(idx, src)], target), target, _num_predict([(idx, src)], target),
                                  hailo_only=hailo_only, cpu_first=cpu_first, should_stop=should_stop)
            if one is None:
                return False
            single = parse_output(one, 1).get(1)
            if single:
                done[idx] = single
            else:
                stats["fallback_units"] += 1
        return True

    async def worker(name: str, *, hailo_only: bool, cpu_first: bool) -> None:
        while True:
            if should_stop():
                stats["stopped"] = True
                return
            async with lock:
                if not queue:
                    return
                c = queue.pop(0)
            try:
                ok = await translate_chunk(c, hailo_only=hailo_only, cpu_first=cpu_first)
            except LLMError as e:
                logger.warning("[Translate] %s 第 %d/%d 段失敗：%s", name, c + 1, total, e)
                async with lock:
                    queue.insert(0, c)          # 交給另一路；兩路都失敗時下面的保底會留原文
                return
            if not ok:                          # 開始錄音：停在段落之間
                stats["stopped"] = True
                async with lock:
                    queue.insert(0, c)
                return
            finished[c] = True
            report()

    report()
    workers = [worker("Hailo", hailo_only=True, cpu_first=False)]
    if use_cpu and total >= 2:
        workers.append(worker("CPU", hailo_only=False, cpu_first=True))
    await asyncio.gather(*workers)
    if queue and not stats["stopped"]:          # 兩路都失敗：最後再用預設順序試一次
        for c in list(queue):
            try:
                if await translate_chunk(c, hailo_only=False, cpu_first=False):
                    finished[c] = True
                    queue.remove(c)
            except LLMError as e:
                logger.warning("[Translate] 第 %d/%d 段保底也失敗，保留原文：%s", c + 1, total, e)
    out = localize(assemble(rows, done, target))
    return {"text": out, "chunks": total, "translated_chunks": sum(finished), "kept_units": len(flat) - len(todo),
            "units": len(flat), "fallback_units": stats["fallback_units"], "stopped": stats["stopped"]}
