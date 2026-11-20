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
BATCH_CHARS = 120     # 一次請求的原文字數上限 (= transcript_translate.FIRST_CHUNK_CHARS，一個請求翻完)
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def load_live_translate_preference() -> str:
    try:
        with open(LIVE_TR_PATH, encoding="utf-8") as f:
            pref = json.load(f).get("target", LIVE_TR_DEFAULT)
    except FileNotFoundError:
        return LIVE_TR_DEFAULT
    except (OSError, ValueError, AttributeError) as e:
        logger.warning("[LiveTranslate] preference unreadable (%s); using %s", e, LIVE_TR_DEFAULT)
        return LIVE_TR_DEFAULT
    return pref if pref in LIVE_TR_CHOICES else LIVE_TR_DEFAULT


def save_live_translate_preference(target: str) -> str:
    if target not in LIVE_TR_CHOICES:
        raise ValueError(f"target 必須是 {'/'.join(LIVE_TR_CHOICES)}")
    os.makedirs(os.path.dirname(LIVE_TR_PATH), exist_ok=True)
    tmp = LIVE_TR_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"target": target}, f)
    os.replace(tmp, LIVE_TR_PATH)
    return target


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
                 should_stop: Callable[[], bool] = lambda: False) -> None:
        self.mode = mode
        self.src: List[str] = []
        self.out: Dict[int, str] = {}
        self.targets: Dict[int, str] = {}
        self._added: List[float] = []
        self.latencies: List[float] = []
        self.kept = 0          # 沒翻成 (數值對不上、模型沒回)：顯示原文
        self.requests = 0
        self._event = asyncio.Event()
        self._closed = False
        self._on_update = on_update
        self._should_stop = should_stop

    def add(self, text: str) -> None:
        if text and text.strip():
            self.src.append(text.strip())
            self._added.append(time.time())
            self._event.set()

    def pending(self) -> int:
        """還沒翻的段落數 (錄音中預先整理紀要用來讓路：PI5_PREMAP_YIELD_S)。"""
        return len(self.src) - len(self.out)

    def close(self) -> None:
        self._closed = True
        self._event.set()

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
                "live_tr_requests": self.requests, "live_tr_kept": self.kept,
                "live_tr_lat_p50": _percentile(self.latencies, 0.5), "live_tr_lat_p90": _percentile(self.latencies, 0.9),
                "live_tr_lat_max": round(max(self.latencies), 1) if self.latencies else None}

    def dump(self) -> Dict[str, Any]:
        """逐段原文、譯文、目標語言、延遲 (秒)：存到 RAM 磁碟給量測用 (MeetingMinutes._start_live_translate)。"""
        segs = [{"src": t, "out": self.out.get(i), "target": self.targets.get(i)} for i, t in enumerate(self.src)]
        return {"mode": self.mode, "segments": segs, "latencies": [round(x, 2) for x in self.latencies], **self.stats()}

    def _next_batch(self, start: int) -> List[int]:
        """從 start 起、目標語言相同、合計 ≤ BATCH_CHARS 字的段落 (至少一段)。"""
        tgt = target_for(self.src[start], self.mode)
        idxs, size = [], 0
        for i in range(start, len(self.src)):
            if idxs and (size + len(self.src[i]) > BATCH_CHARS or target_for(self.src[i], self.mode) != tgt):
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
            idxs = self._next_batch(done)
            tgt = target_for(self.src[idxs[0]], self.mode)
            units = [self.src[i] for i in idxs]
            self.requests += 1
            try:
                res = await tt._translate_flat(units, tgt, None, self._should_stop, use_cpu=False)
                got = res["done"]
            except tt.LLMError as e:
                logger.warning("[LiveTranslate] 第 %d–%d 段翻譯失敗，顯示原文：%s", idxs[0] + 1, idxs[-1] + 1, e)
                got = {}
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
