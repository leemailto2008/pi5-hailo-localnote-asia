# -*- coding: utf-8 -*-
"""
sv_lang_guard.py — SenseVoice 不支援的語言改用 Hailo Whisper 的文字（2026-11-18）。

SenseVoiceSmall 只認得中／英／粵／日／韓。德／西／法／印尼語被標成 <|en|> 寫出近似英文的亂碼
（德「Und dann haben wir hier Lemon und alles möglich」→「Then I' here, Limo on Alice Muley here.」），
泰／越語多被標成 <|yue|> 寫出亂碼中文；語言標記本身跟真英文／真粵語一樣，分不出來。
Hailo Whisper（NPU）支援這些語言，同一片會寫出原語言（德／西／法／印尼／越是拉丁字母、泰是泰文）。

做法：SenseVoice 標 en／yue 的片（或這場已判定是外語時的每一片），另外用 Hailo Whisper 解一次（stt_worker，NPU，
不在 CPU 上跑 Whisper，見 CLAUDE.md 重點一），比對兩邊的輸出（whisper_verdict）：
  - Whisper 寫泰文 → 外語。
  - Whisper 寫拉丁字母：SenseVoice 標 en 時看 Whisper 的英文單字有幾成出現在 SenseVoice 的輸出裡
    （真英文兩邊寫的是同一句；亂碼和原語言文字幾乎沒有共同單字）；SenseVoice 寫成中文字（標 yue／zh）→ 外語。
  - Whisper 寫中文／日文／韓文 → SenseVoice 支援的語言，照用 SenseVoice。
單片判斷會誤傷（台語偶爾被 Whisper 寫成泰文 5／106 片），所以記這場會議最近 8 片的判斷，
六成以上、至少 3 片是外語時，判外語的片才改用 Whisper 的文字（ForeignLangGuard）。
高精度逐字稿（refine_transcript）有整場的判斷，用前後各 REFINE_WINDOW 片（refine_whisper_choices）。

量測（.cc_scratch/sv_lang/，YouTube 真實外語 44 段×3 分＋中文 30 分 ×3 等對照，共 2,202 片；同一份切片的 SenseVoice 與 Whisper 輸出）：
  - Whisper 單字在 SenseVoice 輸出裡的比例（SenseVoice 標 en）：英文 196 片 q10 0.90、外國口音中文 q10 0.62；德／西／法／印尼 q90 ≤ 0.12。
  - 改用 Whisper 的片（即時稿／高精度稿）：德 94／102、西 93／101、法 90／98、印尼 80／88、泰 96／104、越 70／76（各約 100 片）；
    中文 854、中英夾雜 107、英文 196、粵 79、日 52、韓 104、台語 106、外國口音中文 103 片：0 片被換。
  - 中文會議要多叫 Whisper 的片：2／854（SenseVoice 標 en 的片）。英文／粵語會議每片都要比對：最近 8 片都判「支援」時改成每 OK_PROBE_EVERY 片比對一次。
限制：印尼語 Whisper 有時直接寫成英文翻譯（Whisper-Small 本身，見 BIG_CHANGE_STATUS #49），仍比 SenseVoice 的亂碼好。
PI5_SV_FOREIGN_GUARD=0 關閉。
"""

import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _ROOT not in sys.path:   # repo 裡 hailo_whisper 在上一層（Pi 上部署在同一層），同 voice_pipeline 的做法
    sys.path.append(_ROOT)
from hailo_whisper.engine import LanguageMemory  # noqa: E402

ENABLED = os.environ.get("PI5_SV_FOREIGN_GUARD", "1").strip() != "0"
PROBE_LANGS = frozenset({"<|en|>", "<|yue|>"})
OK_PROBE_EVERY = 4
REFINE_WINDOW = 4
OVERLAP_OK, OVERLAP_FOREIGN = 0.5, 0.3

_LETTER_RE = re.compile(r"[^\W\d_]")
_THAI_RE = re.compile(r"[฀-๿]")
_CJK_SCRIPT_RE = re.compile(r"[぀-ヿㇰ-ㇿ㐀-䶿一-鿿豈-﫿ᄀ-ᇿ가-힯]")   # 中、日假名、韓
_LATIN_RE = re.compile(r"[A-Za-zÀ-ɏḀ-ỿ]")
_LATIN_WORD_RE = re.compile(r"[A-Za-zÀ-ɏḀ-ỿ']+")
_ASCII_WORD_RE = re.compile(r"[a-z']+")


def whisper_verdict(sv_lang: str, sv_text: str, whisper_text: str) -> Optional[str]:
    """同一片 SenseVoice（語言標記、原始文字）與 Whisper（自動偵測）的輸出 → "foreign"（SenseVoice 不支援的語言）／"ok"／None（看不出來）。"""
    w = whisper_text or ""
    letters = _LETTER_RE.findall(w)
    if len(letters) < 4:
        return None
    n_thai, n_latin = len(_THAI_RE.findall(w)), len(_LATIN_RE.findall(w))
    if n_thai >= 0.5 * len(letters):
        return "foreign"
    # 其他文字 (西里爾、阿拉伯、天城、希伯來、希臘…) 過半也是 SenseVoice 不支援的語言 (2026-11-23：原本「不是拉丁字母就 ok」，
    # 俄文、阿拉伯文會議永遠不改用 Whisper)。中日韓照舊 ok；中英夾雜不受影響 (拉丁字母＋中文不算「其他」)
    if len(letters) - n_thai - n_latin - len(_CJK_SCRIPT_RE.findall(w)) >= 0.5 * len(letters):
        return "foreign"
    if n_latin < 0.8 * len(letters):
        return "ok"   # 中文／日文／韓文
    if len(_LATIN_WORD_RE.findall(w)) < 3:
        return None
    if sv_lang != "<|en|>":
        return "foreign"   # SenseVoice 寫成中文字（標 yue／zh），Whisper 寫拉丁字母
    wh_words = set(_ASCII_WORD_RE.findall(w.lower()))
    if not wh_words:
        return "foreign"   # 全是帶附加符號的字母（越南文）
    overlap = len(wh_words & set(_ASCII_WORD_RE.findall((sv_text or "").lower()))) / len(wh_words)
    if overlap >= OVERLAP_OK:
        return "ok"
    return "foreign" if overlap < OVERLAP_FOREIGN else None


class ForeignLangGuard:
    """一場會議的即時稿用：決定哪些片要另外用 Whisper 比對（should_probe），比對後要不要改用 Whisper 的文字（decide）。"""

    def __init__(self, clock=None) -> None:
        self._memory = LanguageMemory(clock=clock) if clock is not None else LanguageMemory()
        self._skipped = 0
        # 錄音已結束、只剩尾端切片 (meeting_minutes 收尾時設)：還不是外語會議就不再比對。
        # 2026-11-18 21:56 podcast：最後一片底噪「.」標 <|en|> → 送比對，stt_worker 這時才載入 Whisper (5.2 s)，
        # 尾端等待 6.4 s (同一份 podcast 前 12 場 0.9–1.6 s)。最後一兩片少一票不影響即時稿；高精度稿用前後各 4 片判斷。
        self.tail_only = False

    def foreign_mode(self) -> bool:
        return self._memory.dominant() == "foreign"

    def should_probe(self, sv_lang: str) -> bool:
        if not ENABLED:
            return False
        if self.foreign_mode():
            return True
        if self.tail_only:
            return False
        if sv_lang not in PROBE_LANGS:
            return False
        if self._memory.dominant() == "ok" and self._memory_full_ok():
            self._skipped += 1
            if self._skipped < OK_PROBE_EVERY:
                return False
        self._skipped = 0
        return True

    def _memory_full_ok(self) -> bool:
        items = [lg for _, lg in self._memory._items]
        return len(items) >= self._memory.size and all(lg == "ok" for lg in items)

    def decide(self, sv_lang: str, sv_text: str, whisper_text: str) -> Optional[str]:
        """記下這片的判斷；回傳 "whisper"（改用 Whisper 的文字）或 None（照用 SenseVoice）。"""
        verdict = whisper_verdict(sv_lang, sv_text, whisper_text)
        self._memory.add(verdict)
        return "whisper" if verdict == "foreign" and self.foreign_mode() else None


def retro_foreign_segments(guard: Optional["ForeignLangGuard"], segments: List[str], recs: Sequence[Dict[str, Any]],
                           clean: Callable[[str], str]) -> int:
    """錄音結束時這場是外語會議 (guard.foreign_mode())：前面比對過 (rec 有 wtext)、判成外語、但當時還不夠多數沒換的段落，
    就地換成 Whisper 的文字 (clean 是即時稿用的清理)。回傳換了幾段；不是外語會議或沒有這種段落時不動。
    segments 與 recs 一一對應 (meeting_minutes 的 live_segments／live_seg_recs)。"""
    if guard is None or not ENABLED or not guard.foreign_mode():
        return 0
    n = 0
    for k, rec in enumerate(recs):
        w = rec.get("wtext")
        if k >= len(segments) or not w or rec.get("src") != "sv" or rec.get("use") == "whisper":
            continue
        if whisper_verdict(rec.get("lang", ""), rec.get("text", ""), w) != "foreign":
            continue
        t = clean(w.strip())
        if t:
            segments[k] = t
            n += 1
    return n


def refine_whisper_choices(slices: Sequence[Dict[str, Any]]) -> List[int]:
    """高精度逐字稿：slices = 即時切片（有比對過的片帶 sv_lang／sv_text／wtext）。
    回傳要改用 Whisper 文字的片索引：這片判外語，且前後各 REFINE_WINDOW 個有判斷的片（含自己）六成以上、至少 3 片判外語。"""
    if not ENABLED:
        return []
    judged = []
    for k, s in enumerate(slices):
        if s.get("wtext") is None:
            continue
        v = whisper_verdict(s.get("sv_lang", ""), s.get("sv_text", ""), s["wtext"])
        if v:
            judged.append((k, v))
    out = []
    for j, (k, v) in enumerate(judged):
        if v != "foreign":
            continue
        win = [x for _, x in judged[max(0, j - REFINE_WINDOW):j + REFINE_WINDOW + 1]]
        n = win.count("foreign")
        if n >= 3 and n >= 0.6 * len(win):
            out.append(k)
    return out


def pseudo_tokens(text: str, start: float, end: float):
    """Whisper 沒有逐字時間：依字（空白分隔的詞；泰文等沒有空白的就一個字一個字）平均分到 [start, end)，
    回傳 (tokens, times)，tokens 接起來 strip() 後等於 text.strip()（高精度稿依時間把字分回 VAD 句子用）。"""
    t = (text or "").strip()
    toks = re.findall(r"\s*\S+", t)
    if len(toks) <= 1 and len(t) > 1:
        toks = list(t)
    if not toks:
        return [], []
    first = toks[0][:1]
    if _LETTER_RE.match(first) and not _CJK_SCRIPT_RE.match(first) and not _THAI_RE.match(first):
        # 用空白分詞的文字 (拉丁、西里爾、阿拉伯、天城…) 接在前一片後面要有空白（字接起來 strip 後仍等於 text）；
        # 2026-11-23：原本只看拉丁字母，俄文、阿拉伯文的片跟前一片黏在一起
        toks[0] = " " + toks[0]
    step = max(0.0, end - start) / len(toks)
    return toks, [start + i * step for i in range(len(toks))]
