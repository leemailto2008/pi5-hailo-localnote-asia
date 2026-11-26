# -*- coding: utf-8 -*-
"""
asr_language.py — 語音語系設定（2026-11-20 使用者要求可選）。

選項：auto（自動偵測，原本的做法）、zh、en、fr、es（11-20 使用者決定）、ms、ar（11-26 使用者加馬來文、阿拉伯文）。網頁選、存在 DATA_DIR/asr_language.json，下一場錄音生效。
  - auto：即時稿照引擎開關 (SenseVoice／Whisper)；SenseVoice 遇到不支援的語言時用 Whisper 比對後改用 (sv_lang_guard)。
  - zh／en：SenseVoice 支援；即時稿照引擎開關，SenseVoice 與 Whisper 都固定這個語言 (不自動偵測、不做外語比對)；
    高精度稿 SenseVoice 固定這個語言。
  - fr／es／ms／ar：SenseVoiceSmall 只認得中／英／粵／日／韓 → 即時稿一律改用 Hailo Whisper (固定語言)，
    高精度稿整份用 Whisper 即時稿的文字 (refine_transcript.apply_whisper_live，force=True)，分說話人照舊。
  - 翻譯：即時翻譯選「自動」時，語系 zh 翻英文、其他語系翻中文 (live_translate.target_for)。
"""

import json
import logging
import os
from typing import Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)

ASR_LANG_CHOICES = ("auto", "zh", "en", "fr", "es", "ms", "ar")
ASR_LANG_DEFAULT = "auto"
SV_SUPPORTED = frozenset({"auto", "zh", "en"})     # SenseVoiceSmall 可固定的語言 (另有 yue／ja／ko，目前選單沒列)
ASR_LANG_PATH = os.path.join(DATA_DIR, "asr_language.json")
LABELS = {"auto": "自動偵測", "zh": "中文 (zh)", "en": "英文 (en)", "fr": "法文 (fr)", "es": "西班牙文 (es)",
          "ms": "馬來文 (ms)", "ar": "阿拉伯文 (ar)"}   # 網頁顯示：名稱後加語言代碼 (11-20 使用者)


def load_asr_language() -> str:
    try:
        with open(ASR_LANG_PATH, encoding="utf-8") as f:
            lang = json.load(f).get("language", ASR_LANG_DEFAULT)
    except FileNotFoundError:
        return ASR_LANG_DEFAULT
    except (OSError, ValueError, AttributeError) as e:
        logger.warning("[AsrLanguage] preference unreadable (%s); using %s", e, ASR_LANG_DEFAULT)
        return ASR_LANG_DEFAULT
    return lang if lang in ASR_LANG_CHOICES else ASR_LANG_DEFAULT


def save_asr_language(lang: str) -> str:
    if lang not in ASR_LANG_CHOICES:
        raise ValueError(f"language 必須是 {'/'.join(ASR_LANG_CHOICES)}")
    os.makedirs(os.path.dirname(ASR_LANG_PATH), exist_ok=True)
    from atomic_file import write_atomic   # 寫到一半失敗不留 .tmp (2026-11-23)
    write_atomic(ASR_LANG_PATH, lambda f: json.dump({"language": lang}, f))
    return lang


def sv_supported(lang: str) -> bool:
    return lang in SV_SUPPORTED


def sv_language(lang: str) -> str:
    """SenseVoice 的 language 參數 (auto／zh／en)；不支援的語系回 auto (呼叫端不該用 SenseVoice)。"""
    return lang if lang in ("zh", "en") else "auto"


# 馬來文用印尼文 (id) 解：Whisper-Small 的 ms 常把馬來語輸出成英文。11-26 .228 實測 7 段 (新聞、訪談、podcast 各 3 分)：
# 英文輸出 28–34% → 20–31%、馬來常用字 1–6% → 5–10%，印尼專用字 ≤ 1.7% (仍是馬來文寫法)，慢約 10% (RTF 0.37)
WHISPER_DECODE_AS = {"ms": "id"}


def whisper_language(lang: str) -> Optional[str]:
    """Hailo Whisper 的 language (ISO-639-1)；auto 回 None (自動偵測)；馬來文用 id 解 (WHISPER_DECODE_AS)。"""
    return None if lang == "auto" else WHISPER_DECODE_AS.get(lang, lang)


def live_engine_for(engine: str, lang: str) -> str:
    """選了 SenseVoice 不支援的語系時，即時稿改用 Whisper。"""
    return engine if sv_supported(lang) else "whisper"
