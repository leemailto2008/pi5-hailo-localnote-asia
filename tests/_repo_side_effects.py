"""測試跑完清掉「import 時在 repo 裡建立的空資料夾」（2026-11-23，localnote@mac）。

沒有 /dev/shm 的機器（macOS、Windows）上，import 這些模組會在工作目錄裡建資料夾：
  code_dispatcher/audio_cache   voice_memory.get_in_memory_cache_dir() 退回本機路徑
  code_dispatcher/data          bluetooth_manager 模組層 os.makedirs(DATA_DIR)
  telegram_agent/data           telegram_agent/config.py 模組層 os.makedirs(DATA_DIR)
它們是 gitignore 或空的，git status 看不出來，但每跑一次就留一次。只刪「這次測試開始前不存在、結束時仍是空的」，
原本就有的（例如開發機上真的在用的 audio_cache）或裡面有檔案的一律不動。
"""
import os
from typing import Iterable, List, Set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMPORT_TIME_DIRS = (
    os.path.join("code_dispatcher", "audio_cache"),
    os.path.join("code_dispatcher", "data"),
    os.path.join("telegram_agent", "data"),
)


def snapshot(root: str = ROOT, rel_dirs: Iterable[str] = IMPORT_TIME_DIRS) -> Set[str]:
    """測試開始前已經存在的資料夾（相對路徑）。"""
    return {d for d in rel_dirs if os.path.isdir(os.path.join(root, d))}


def remove_new_empty_dirs(preexisting: Set[str], root: str = ROOT,
                          rel_dirs: Iterable[str] = IMPORT_TIME_DIRS) -> List[str]:
    """刪掉這次新建、而且仍是空的資料夾；回傳刪掉的相對路徑。"""
    removed = []
    for d in rel_dirs:
        path = os.path.join(root, d)
        if d in preexisting or not os.path.isdir(path) or os.path.islink(path):
            continue
        try:
            os.rmdir(path)            # 只會刪空資料夾；有檔案時 OSError，保留
            removed.append(d)
        except OSError:
            continue
    return removed
