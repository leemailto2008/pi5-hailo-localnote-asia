# -*- coding: utf-8 -*-
"""
meeting_glossary.py — 會議詞彙（2026-11-13）：使用者在網頁「錄一段會議」卡片填的人名、公司、產品、術語。

存在盒子上（RAM 磁碟，與高精度逐字稿同一個資料夾，零磁碟寫入；重開機清掉，網頁開頁時會把瀏覽器記的那份再送上來），
後端各處都讀這一份：
  - 會議紀要：紀要前先把即時稿裡同音的錯字改成詞彙（apply_to_text；錄音中預先整理、重新整理紀要也一樣）。
    11-13 量測（exp_summary_gloss.py，紀要召回每份 3 次）：調參 a5／a5b／a10 平均 0.944 → 1.0（a10 每次漏的韌體負責人補回）；
    驗證 n10 1.0 → 1.0、n30 0.833 → 1.0（每次漏的「供應商」補回），紀要耗時不變。
  - 會後自動快修（main.py → transcript_polish.quick_fix）與兩種潤稿。
"""

import logging
import os
from typing import List, Tuple

from voice_memory import get_in_memory_cache_dir

logger = logging.getLogger(__name__)

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(get_in_memory_cache_dir())), "localnote_state")
GLOSSARY_PATH = os.path.join(STATE_DIR, "glossary.txt")
MAX_CHARS = 5000


def read_text() -> str:
    try:
        with open(GLOSSARY_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as e:   # 讀不到只影響少了詞彙，不擋其他功能
        logger.warning("[glossary] cannot read %s: %s", GLOSSARY_PATH, e)
        return ""


def write_text(text: str) -> None:
    os.makedirs(os.path.dirname(GLOSSARY_PATH), exist_ok=True)
    tmp = GLOSSARY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, GLOSSARY_PATH)   # 寫完才換上，讀的人不會看到半個檔


def terms() -> List[str]:
    from transcript_polish import parse_glossary
    return parse_glossary(read_text())


def apply_to_text(text: str) -> Tuple[str, int]:
    """把逐字稿裡跟會議詞彙同音的錯字換成詞彙（transcript_polish.apply_glossary；字數不變）。
    沒有詞彙、沒裝 pypinyin 就原樣回傳。回傳 (文字, 改了幾處)。"""
    words = terms()
    if not words or not text:
        return text, 0
    try:
        from transcript_polish import apply_glossary, protected_spans
        return apply_glossary(text, words, protected_spans(text))
    except ImportError as e:
        logger.warning("[glossary] not applied (%s)", e)
        return text, 0
