# -*- coding: utf-8 -*-
"""
live_translate.py — 錄音中的即時翻譯（2026-11-20，使用者決定做）。

做法：SenseVoice（或 Whisper）即時稿每出一段，就排進這裡；背景工作把還沒翻的段落依序合成一次請求，
用網頁翻譯同一套逐行翻譯 (transcript_translate._translate_flat：數字保護、已是目標語言的照抄、對不上的單獨重翻)。
只用 Hailo (錄音中禁止 CPU 推論，CLAUDE.md 重點一)；和錄音中預先整理紀要都送 hailo-ollama，由它依序排隊，兩者輪流用 NPU。
翻譯落後時下一次請求自動多帶幾段 (最多 BATCH_CHARS 字)，追得上。

目標語言 (網頁選，下一場錄音生效，存在 DATA_DIR/live_translate.json)：
  auto = 外語翻中文、中文翻英文 (同網頁「翻譯」的預設)；en／zh = 一律翻成英文／中文；off = 不翻。
不用兩個 Whisper：11-19 實測 Hailo Whisper 的 TRANSLATE 只能翻成英文，GS3 中文 16 片有 3 片卡在重複迴圈、數字翻錯 (BIG_CHANGE_STATUS #57)。
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from config import DATA_DIR
import transcript_translate as tt

logger = logging.getLogger(__name__)

LIVE_TR_CHOICES = ("off", "auto", "en", "zh")
LIVE_TR_DEFAULT = os.environ.get("PI5_LIVE_TRANSLATE_DEFAULT", "auto")   # 2026-11-20 使用者確認預設：外語翻中文、中文翻英文
LIVE_TR_PATH = os.path.join(DATA_DIR, "live_translate.json")
BATCH_CHARS = 120     # 一次請求的原文字數上限 (跟得上時)
# 落後時一次最多帶幾字：每次請求 NPU 都要在 Whisper 與 LLM 之間切換，外語一段就約 120 字，只帶一段時翻譯追不上
# (11-20 德文 6 分：52 段 30 次請求、只翻 30 段、延遲 p50 136 s)
# 即時稿不用 NPU (SenseVoice、中英文會議)：480 字 (11-20 SenseVoice 30 分 p50 20.3 s、紀要 58.7 s；240 字時 23.4 s、72 s)
BATCH_MAX_CHARS = 480
# 即時稿也用 NPU (Hailo Whisper／外語比對)：480 字一次生成約 1 分鐘，期間 Whisper 只能排隊 (德文尾端 21.3 s)，改 240
BATCH_MAX_CHARS_NPU = 240
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


# 即時翻譯開著時錄音中要不要照常預先整理紀要 (2026-11-21 做成選項，預設 True＝維持原本做法；使用者週一決定)：
# 中文 30 分 (.228 W7)：不預先整理時即時翻譯 p50 11.6 s、p90 29.3 s，錄音後紀要 141 s；預先整理時 26.0／64.9 s、紀要 66 s。
# 語速快的 podcast (W8) 不預先整理也追不上 (p50 57 s)，紀要卻從 43 s 變 156 s。
PREMAP_WITH_TRANSLATE_DEFAULT = True


def _read_pref() -> Dict[str, Any]:
    try:
        with open(LIVE_TR_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("[LiveTranslate] preference unreadable (%s); using defaults", e)
        return {}


def _write_pref(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(LIVE_TR_PATH), exist_ok=True)
    from atomic_file import write_atomic   # 寫到一半失敗不留 .tmp (2026-11-23)
    write_atomic(LIVE_TR_PATH, lambda f: json.dump(data, f))


def load_live_translate_preference() -> str:
    pref = _read_pref().get("target", LIVE_TR_DEFAULT)
    return pref if pref in LIVE_TR_CHOICES else LIVE_TR_DEFAULT


def save_live_translate_preference(target: str) -> str:
    if target not in LIVE_TR_CHOICES:
        raise ValueError(f"target 必須是 {'/'.join(LIVE_TR_CHOICES)}")
    _write_pref({**_read_pref(), "target": target})
    return target


def load_premap_with_translate() -> bool:
    v = _read_pref().get("premap", PREMAP_WITH_TRANSLATE_DEFAULT)
    return v if isinstance(v, bool) else PREMAP_WITH_TRANSLATE_DEFAULT


def save_premap_with_translate(enabled: bool) -> bool:
    _write_pref({**_read_pref(), "premap": bool(enabled)})
    return bool(enabled)


def effective_mode(pref: str, asr_lang: str) -> str:
    """這場即時翻譯實際的模式：網頁選「自動」且語音語系選定時跟著語系 (中文翻英文、其他翻中文)；語系 auto 時逐段判斷。"""
    if pref == "auto" and asr_lang not in ("", "auto"):
        return "en" if asr_lang == "zh" else "zh"
    return pref


def target_for(text: str, mode: str) -> str:
    """這段要翻成哪種語言：auto 時中文 (中文字不少於英文字母的一半) 翻英文，其他翻中文。"""
    if mode in ("en", "zh"):
        return mode
    return "en" if len(_CJK_RE.findall(text)) * 2 >= len(_LATIN_RE.findall(text)) and _CJK_RE.search(text) else "zh"


def _percentile(xs: List[float], q: float) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 1)


class LiveTranslator:
    """一場錄音的即時翻譯。add() 每段即時稿；run() 是背景工作；close() 後翻完剩下的段落就結束。
    on_update(self) 每翻好一批呼叫一次 (更新網頁)。"""

    def __init__(self, mode: str, on_update: Optional[Callable[["LiveTranslator"], Awaitable[None]]] = None,
                 should_stop: Callable[[], bool] = lambda: False, npu_busy: Callable[[], bool] = lambda: False,
                 npu_shared: Callable[[], bool] = lambda: False) -> None:
        self.mode = mode
        self.src: List[str] = []
        self.out: Dict[int, str] = {}
        self.targets: Dict[int, str] = {}
        self._added: List[float] = []
        self.latencies: List[float] = []
        self.kept = 0          # 沒翻成 (數值對不上、模型沒回)：顯示原文
        self.requests = 0
        self.llm_calls = 0     # 含單句重翻
        self._event = asyncio.Event()
        self._closed = False
        self._go = asyncio.Event()      # 清掉時暫停送新請求 (pause／resume)
        self._go.set()
        self._on_update = on_update
        self._should_stop = should_stop
        # 即時稿也在用 NPU (Hailo Whisper 即時稿，或 SenseVoice 的外語比對) 而且還有切片沒轉完時，先不送翻譯請求
        # (11-20 Whisper＋即時翻譯 5 分：尾端等待 15–24 s，門檻 10 s)
        self._npu_busy = npu_busy
        self._npu_shared = npu_shared   # 這場即時稿也用 NPU：落後時批次上限用 BATCH_MAX_CHARS_NPU

    def add(self, text: str) -> None:
        if text and text.strip():
            self.src.append(text.strip())
            self._added.append(time.time())
            self._event.set()

    def pause(self) -> None:
        """暫停送新請求 (進行中的那次照常翻完)：即時稿用 Hailo Whisper 時，錄音結束後 NPU 先讓給最後幾段即時稿
        (11-20 Whisper＋即時翻譯 5 分：尾端等待 23.6 s，門檻 10 s)。"""
        self._go.clear()

    def resume(self) -> None:
        self._go.set()

    def close(self) -> None:
        self._closed = True
        self._event.set()

    @property
    def closed(self) -> bool:
        return self._closed

    def text(self) -> str:
        """目前翻好的部分 (從頭連續)，依目標語言接起來。"""
        parts, prev_t = [], None
        for i in range(len(self.src)):
            if i not in self.out:
                break
            t = self.out[i]
            if parts:
                parts.append(" " if self.targets.get(i) == "en" or prev_t == "en" else "")
            parts.append(t)
            prev_t = self.targets.get(i)
        return "".join(parts)

    def stats(self) -> Dict[str, Any]:
        return {"live_tr_mode": self.mode, "live_tr_segments": len(self.src), "live_tr_done": len(self.out),
                "live_tr_requests": self.requests, "live_tr_llm_calls": self.llm_calls, "live_tr_kept": self.kept,
                "live_tr_lat_p50": _percentile(self.latencies, 0.5), "live_tr_lat_p90": _percentile(self.latencies, 0.9),
                "live_tr_lat_max": round(max(self.latencies), 1) if self.latencies else None}

    def dump(self) -> Dict[str, Any]:
        """逐段原文、譯文、目標語言、延遲 (秒)：存到 RAM 磁碟給量測用 (MeetingMinutes._start_live_translate)。"""
        segs = [{"src": t, "out": self.out.get(i), "target": self.targets.get(i)} for i, t in enumerate(self.src)]
        return {"mode": self.mode, "segments": segs, "latencies": [round(x, 2) for x in self.latencies], **self.stats()}

    def _next_batch(self, start: int) -> List[int]:
        """從 start 起、目標語言相同的段落 (至少一段)：合計 ≤ BATCH_CHARS 字；落後 (還沒翻的超過 BATCH_CHARS 字) 時最多 BATCH_MAX_CHARS 字。"""
        tgt = target_for(self.src[start], self.mode)
        pending = sum(len(t) for t in self.src[start:])
        cap = BATCH_MAX_CHARS_NPU if self._npu_shared() else BATCH_MAX_CHARS
        limit = max(BATCH_CHARS, min(cap, pending)) if pending > BATCH_CHARS else BATCH_CHARS
        idxs, size = [], 0
        for i in range(start, len(self.src)):
            if idxs and (size + len(self.src[i]) > limit or target_for(self.src[i], self.mode) != tgt):
                break
            idxs.append(i)
            size += len(self.src[i])
        return idxs

    async def run(self) -> None:
        done = 0
        while True:
            if self._should_stop():
                return
            if done >= len(self.src):
                if self._closed:
                    return
                self._event.clear()
                await self._event.wait()
                continue
            await self._go.wait()
            while self._npu_busy() and not self._should_stop():
                await asyncio.sleep(0.3)
            if self._should_stop():
                return
            idxs = self._next_batch(done)
            tgt = target_for(self.src[idxs[0]], self.mode)
            units = [self.src[i] for i in idxs]
            self.requests += 1
            # 暫停 (錄音結束、紀要要用 NPU) 時連進行中的請求也停掉，紀要出來後這批整批重翻
            # (11-20：只在批次之間暫停時，進行中的那批連重翻可跑 30 s 以上，紀要仍比關翻譯慢 20–28 s)
            interrupted = lambda: self._should_stop() or not self._go.is_set()
            try:
                res = await tt._translate_flat(units, tgt, None, interrupted, use_cpu=False, one_chunk=True)
                got = res["done"]
                self.llm_calls += res.get("llm_calls", 0)
            except tt.LLMError as e:
                logger.warning("[LiveTranslate] 第 %d–%d 段翻譯失敗，顯示原文：%s", idxs[0] + 1, idxs[-1] + 1, e)
                got = {}
            if not self._go.is_set() and not self._should_stop():
                self.requests -= 1
                continue
            now = time.time()
            for k, i in enumerate(idxs):
                if k in got:
                    self.out[i] = got[k]
                else:
                    self.out[i] = self.src[i]
                    self.kept += 1
                self.targets[i] = tgt
                self.latencies.append(now - self._added[i])
            done = idxs[-1] + 1
            if self._on_update is not None:
                try:
                    await self._on_update(self)
                except Exception as e:   # 網頁推送失敗不影響翻譯
                    logger.warning("[LiveTranslate] 更新網頁失敗：%s", e)
