# -*- coding: utf-8 -*-
"""
single_job.py — 同時只跑一個的背景工作（潤稿、高精度逐字稿共用，2026-11-10）。

狀態放記憶體，服務重啟就回到 idle；前端看到 idle 就提示重新執行。
給了 persist_path（例如 RAM 磁碟 /dev/shm 上的檔案，不寫實體磁碟）時，done／stopped 的結果另存一份，服務重啟後讀回
（2026-11-12：部署重啟後高精度逐字稿不見，網頁潤稿來源只剩即時稿）。
state：idle → running → done／stopped／error。runner 回傳的 dict 帶 stopped=True 時記為 stopped。
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def meeting_busy_reason(recording_active: bool, meeting_state: Optional[str]) -> Optional[str]:
    """錄音中或會議還在整理（逐字稿收尾、紀要生成）時不可啟動潤稿／高精度逐字稿，回傳給前端看的原因；可啟動回傳 None。

    11-11 實測：紀要生成中按潤稿，潤稿請求在 hailo-ollama 排在紀要後面，等了 120 s 逾時；
    hailo-ollama 不會取消已送出的請求，重試又排在那個被放棄的請求後面，一段要好幾分鐘。
    """
    if recording_active or meeting_state == "recording":
        return "錄音中不可執行，請錄音結束後再試"
    if meeting_state == "processing":
        return "會議紀要還在生成，完成後再試"
    return None


class JobBusyError(RuntimeError):
    """已有同名工作在跑。"""


_PERSISTED_STATES = ("done", "stopped")


class SingleJob:
    def __init__(self, name: str, persist_path: Optional[str] = None) -> None:
        self.name = name
        self.persist_path = persist_path
        self._state: Dict[str, Any] = self._load() or {"state": "idle"}
        self._task: Optional["asyncio.Task[None]"] = None

    def _load(self) -> Optional[Dict[str, Any]]:
        if not self.persist_path or not os.path.isfile(self.persist_path):
            return None
        try:
            with open(self.persist_path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError) as e:
            logger.warning("[%s] ignore unreadable saved result %s: %s", self.name, self.persist_path, e)
            return None
        if not isinstance(state, dict) or state.get("state") not in _PERSISTED_STATES:
            logger.warning("[%s] ignore saved result with state %r", self.name, state.get("state") if isinstance(state, dict) else None)
            return None
        return state

    def _save(self, state: Dict[str, Any]) -> None:
        tmp = self.persist_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False)
            os.replace(tmp, self.persist_path)        # 寫完才換上，讀的人不會看到半個檔
        except (OSError, TypeError, ValueError) as e:  # 存不了只影響重啟後看不到，工作本身已完成
            logger.warning("[%s] could not save result to %s: %s", self.name, self.persist_path, e)

    @property
    def running(self) -> bool:
        return self._state.get("state") == "running"

    def update(self, **fields: Any) -> None:
        """runner 回報進度用 (例如 done、total)；可從工作執行緒呼叫，單純的 dict 更新。"""
        self._state.update(fields)

    def snapshot(self) -> Dict[str, Any]:
        snap = dict(self._state)
        if "started" in snap:
            snap["elapsed"] = round((snap.get("finished") or time.time()) - snap["started"], 1)
        return snap

    def start(self, runner: Callable[["SingleJob"], Awaitable[Dict[str, Any]]], **info: Any) -> Dict[str, Any]:
        """在目前的 event loop 啟動 runner(job)；已有工作在跑就丟 JobBusyError。"""
        if self.running:
            raise JobBusyError(f"{self.name} is already running")
        self._state = {"state": "running", "started": time.time(), **info}
        self._task = asyncio.create_task(self._run(runner))
        return self.snapshot()

    async def _run(self, runner: Callable[["SingleJob"], Awaitable[Dict[str, Any]]]) -> None:
        try:
            result = await runner(self)
        except Exception as e:  # 背景工作：未預期錯誤要寫進狀態，否則前端會永遠停在 running
            logger.exception("[%s] job failed", self.name)
            self._state.update(state="error", error=str(e) or type(e).__name__, finished=time.time())
            return
        self._state.update(
            state="stopped" if result.get("stopped") else "done", result=result, finished=time.time()
        )
        if self.persist_path:
            await asyncio.to_thread(self._save, dict(self._state))
