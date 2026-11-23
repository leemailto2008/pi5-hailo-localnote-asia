# -*- coding: utf-8 -*-
"""寫檔「先寫暫存檔再 os.replace」的共用小工具 (2026-11-23)。

讀的人永遠只看到完整的舊檔或新檔；寫到一半失敗 (磁碟滿 ENOSPC、序列化錯誤…) 時把寫了一半的暫存檔刪掉再把例外往外拋，
不在 /dev/shm (RAM 磁碟) 留下 *.tmp／*.part。呼叫端原本的錯誤處理 (接住後回 False、或交給 API 回 500) 不變。
"""
import logging
import os
from typing import IO, Callable

logger = logging.getLogger(__name__)


def discard(path: str) -> None:
    """刪掉暫存檔；本來就不在不算錯，刪不掉只記 log (不蓋掉原本的例外)。"""
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError as e:
        logger.warning("[atomic_file] cannot remove partial file %s: %s", path, e)


def write_atomic(path: str, write: Callable[[IO[str]], None], suffix: str = ".tmp", encoding: str = "utf-8") -> None:
    """write(f) 寫進 path+suffix，成功才 os.replace 成 path；任何例外都先刪暫存檔再往外拋。"""
    tmp = path + suffix
    try:
        with open(tmp, "w", encoding=encoding) as f:
            write(f)
        os.replace(tmp, path)
    except BaseException:
        discard(tmp)
        raise
