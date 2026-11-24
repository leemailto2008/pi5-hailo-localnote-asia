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
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from llm_backend import LLMError, aiter_chat_stream

logger = logging.getLogger(__name__)

UNIT_CHARS = 140          # 每個翻譯單位最多幾個字（太長的句子再切）
CHUNK_CHARS = 360         # 每個請求的原文字數上限：Hailo qwen3:1.7b 約 4.5 tok/s，中翻英一段約 60 s
FIRST_CHUNK_CHARS = 120   # 第一個請求的原文字數上限 (先讓網頁出現第一段)
REQUEST_TIMEOUT_SEC = 180.0
POLL_SEC = 0.5            # 檢查「開始錄音了沒」的間隔

_LABEL_RE = re.compile(r"^(說話人(\d+)[：:]|Speaker\s*(\d+)\s*[:：])\s*")
_SENT_END_RE = re.compile(r"(?<=[。！？!?；;])|(?<=[.](?=\s))")
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_NON_EN_LATIN_RE = re.compile(r"[À-ɏḀ-ỿ]")     # 帶附加符號的拉丁字母：德、法、西、越…
_OTHER_SCRIPT_RE = re.compile(r"[฀-๿぀-ヿ가-힯Ѐ-ӿ]")   # 泰、假名、韓、俄
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")


def is_japanese(text: str) -> bool:
    """日文 (含漢字也算)：假名 ≥ 3 個且佔假名＋漢字一成五以上；中文句子裡偶爾一個「キ」不算。
    條件和 hailo_whisper.engine.text_language 的 "ja" 相同 (tests/test_translate_japanese_not_chinese.py 比對兩者)；
    這裡不 import engine (它會載入 numpy，也要另外處理 sys.path)。"""
    kana = len(_KANA_RE.findall(text or ""))
    return kana >= 3 and kana >= 0.15 * (kana + len(_CJK_RE.findall(text or "")))
# 西、法、德、印尼文常見功能詞 (不收跟英文同形的 a、in、an、die、no…)
_FOREIGN_FUNCTION_WORDS = frozenset(
    "de la el los las que y del por para con una se lo su al es "            # 西
    "le les et des du est une pour dans avec sur au aux pas qui ce sont "     # 法
    "der das und ist nicht mit ein eine ich wir sie auf zu den dem von auch "  # 德
    "yang dan di ini itu dengan untuk tidak ada kami kita akan dari ke juga".split())   # 印尼
_NUM_LINE_RE = re.compile(r"^\s*(\d+)\s*[|｜.、:：)）]\s*(.*)$")
_LITERAL_N_RE = re.compile(r"^\s*N\s*[|｜]\s*(.*)$")

SYSTEM = {
    "en": ("You are a professional interpreter. Translate each numbered line of a meeting transcript into natural English. "
           "Keep the same numbers, one output line per input line, written as \"N| translation\". "
           "Keep names, company names and product names as they are. Copy every number with the same digits "
           "(write 12,500 as 12,500; never spell numbers out in words). Output only the numbered lines. "
           # 11-19 exp_cpu：CPU qwen2.5:3b 中翻英 60 句 16 句回（簡體）中文；加這句 0 句 (Hailo 那路同一句提示；
           # 原文也可能是德／西／日…文，所以不寫「輸入是中文」)
           "Every output line must be in English, never in Chinese or in the original language."),
    "zh": ("你是專業口譯員。把會議逐字稿每一行編號的句子翻成通順的台灣繁體中文。"
           "每一行輸入對應一行輸出，格式「N| 翻譯」，編號照原文。人名、公司名、產品名照原文。"
           "數字一律用阿拉伯數字、數值不可改變（12,500 可寫成 12,500 或 1.25萬，不可寫成國字）。只輸出編號的各行。"),
}


def in_target_language(text: str, target: str) -> bool:
    """這個單位已經是目標語言 (照抄，不送模型)。
    英文：沒有中文字、沒有英文以外的拉丁字母 (ä é ñ ß…)、英文功能詞比例夠 (summary_utils.english_share ≥ 0.5)。
    只看「沒有中文字」不夠：11-19 德文會議按 Translate to English，134 句德文全被當成英文照抄。太短的英文句 (「Yes.」) 會送模型，只是多花一點時間。
    中文：中文字不少於英文字母的一半，而且不是日文 (is_japanese；S14：含漢字的日文「今日の会議を始めます」原本被當成中文照抄不翻)。"""
    cjk, latin = len(_CJK_RE.findall(text)), len(_LATIN_RE.findall(text))
    if not re.search(r"[^\W\d_]", text):       # 只有標點／數字 (「...」「.」)：照抄
        return True
    if target == "en":
        from summary_utils import english_share
        if cjk or _NON_EN_LATIN_RE.search(text) or _OTHER_SCRIPT_RE.search(text):
            return False
        # 紀要條目很精簡 (「Government policies affect rental and sales prices」幾乎沒有 the／is)，只看英文功能詞會被當成外語重翻
        # (11-19 自測)；所以 4 個字以上、沒有西／法／德／印尼文常見功能詞的也算英文 (「Wunderbar.」「medio ambientales.」這種短句仍送翻)；
        # 英文功能詞夠多時夾一兩個外語功能詞也算。
        words = re.findall(r"[A-Za-z]+", text.lower())
        foreign = sum(w in _FOREIGN_FUNCTION_WORDS for w in words)
        share = english_share(text)
        return (share >= 0.5 and foreign * 5 <= len(words)) or (foreign == 0 and len(words) >= 4)
    return cjk > 0 and cjk * 2 >= latin and not is_japanese(text)


def untranslated_left(translation: str, target: str) -> bool:
    """譯文沒翻乾淨：翻成英文還夾著中文字 (模型把職稱、人名留成中文)；翻成中文卻一個中文字都沒有
    (11-19 自測：en_short 3 行、德文那份 8 行模型原樣回英文，原本被當成翻好了)。"""
    if target == "en":
        return bool(_CJK_RE.search(translation))
    cjk, latin = len(_CJK_RE.findall(translation)), len(_LATIN_RE.findall(translation))
    if cjk == 0:
        return latin >= 4   # 「AfD」「IBM」這種縮寫翻中文本來就保留
    # 只翻了開頭幾個字、後面還是原文 (11-20 法文即時翻譯「前年45,000 l'an dernier, donc c'est bon…」)
    return latin >= 12 and latin > 4 * cjk   # 人名多的「Ijasa Jokowi再度接受Forensik驗證」(20 對 6) 不算


def mostly_translated(translation: str, target: str) -> bool:
    """沒翻乾淨的譯文還能不能用：翻英文時中文字只佔少數 (「Complete全员 training」可用)；整句還是中文 (模型改寫成簡體中文、
    11-19 GS3 完整逐字稿中翻英 4 句「已经安装了8个警示灯…」) 不能用，保留原文。翻中文沒有此限制。"""
    if target != "en":
        return True
    cjk = len(_CJK_RE.findall(translation))
    return cjk <= 0.3 * (cjk + len(_LATIN_RE.findall(translation)))


# 數字保護 (2026-11-19 紀要翻譯自測：中翻英「200萬」→「200,000」、「40萬」→「40,000」；法→中「11 billion」→「十億」、
# 「200 million」→「二百萬」；英→中「$800,000」→「八百萬美元」)：中翻英前先把「N萬／N億／N千」換成完整阿拉伯數字，
# 不讓模型自己換算；翻完比對數值 (萬、億、thousand、million、billion 都換算成數值)，原文的數值譯文要都有，
# 不符就單獨重翻，仍不符就保留原文 (寧可不翻，也不能翻錯數字)。月份 (9月→September) 不比。
_CN_SCALE = {"千": 10 ** 3, "萬": 10 ** 4, "万": 10 ** 4, "億": 10 ** 8, "亿": 10 ** 8}
# 英、西、法、德、印尼文的大數單位 (11-19 完整逐字稿自測：西文「6 millones」譯成「6 million」被當成數值不符)
_EN_SCALE = {"thousand": 10 ** 3, "million": 10 ** 6, "millions": 10 ** 6, "billion": 10 ** 9, "billions": 10 ** 9,
             "millón": 10 ** 6, "millon": 10 ** 6, "millones": 10 ** 6, "milliard": 10 ** 9, "milliards": 10 ** 9,
             "millionen": 10 ** 6, "milliarde": 10 ** 9, "milliarden": 10 ** 9,
             "juta": 10 ** 6, "miliar": 10 ** 9}
_SCALE_WORDS = "|".join(sorted(_EN_SCALE, key=len, reverse=True))
# 千分位：逗號、或空格／不換行空格 (法文「105 000 hectares」)
# 千分位後面可以接小數「1,234.5」(S18 fuzz：原本讀成 1234 與 5 兩個數)
_NUM_RE = re.compile(r"(\d{1,3}(?:[,\u00a0\u202f ]\d{3})+(?:\.\d+)?(?!\d)|\d+(?:\.\d+)?)\s*(千|萬|万|億|亿|(?:" + _SCALE_WORDS + r")\b)?(?!\d)",
                     re.I)
_CN_SCALED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(千|萬|万|億|亿)")
# 「5萬3135円」「1萬5000元」= 53,135／15,000：萬後面直接接 1–4 位數字 (11-22 full8 日文翻英「5萬3135円」被換成「50,0003135」、數值對不上保留原文)
# 後面接的不能是單位 (N2：「2萬3萬」原本變成 200,030,000；「2萬5千」由 _CN_COMPOSITE_RE 先處理)
_CN_WAN_COMPOSITE_RE = re.compile(r"(\d+)\s*(萬|万)\s*(\d{1,4})(?![\d.,十百千萬万億亿])")


def _scaled(num: str, unit: Optional[str]) -> float:
    # Decimal 從原字串精確計算再轉 float (S18 fuzz：float 乘法「80.9億」= 8090000000.000001，
    # 中翻英送模型的原文變成「8,090,000,000.000001」，翻對的「8.09 billion」反而對不上)
    v = Decimal(re.sub(r"[,\u00a0\u202f ]", "", num))
    if unit:
        v *= _CN_SCALE.get(unit, _EN_SCALE.get(unit.lower(), 1))
    return round(float(v), 6)


_EN_NUM_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                            "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_EN_NUM_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90})
# 序數與分數詞 (譯文那邊)：11-22 full10 日文「手取りの3分の1」→「one-third」，3 對不上保留原文；「第3個」→「the third」也一樣
_EN_NUM_WORDS.update({w: i + 1 for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth "
    "sixteenth seventeenth eighteenth nineteenth twentieth".split())})
_EN_NUM_WORDS.update({"half": 2, "halves": 2, "thirds": 3, "quarter": 4, "quarters": 4, "fifths": 5})


def number_values(text: str, words: bool = False) -> List[float]:
    """文字裡的數值 (換算萬／億／million…，去掉千分位)；「9月」的月份不算 (翻成英文會變成 September)。
    words=True 另外收英文數字詞 (one…twenty、thirty…ninety)：只用在譯文那邊 (11-19 中翻英「1輪」→「one round」被當成數字遺漏)；
    原文那邊不收，「one of the」「no one」不該要求譯文出現 1。"""
    text = text or ""
    out = []
    for m in _NUM_RE.finditer(text):
        if not m.group(2) and text[m.end():m.end() + 1] == "月":
            continue
        out.append(_scaled(m.group(1), m.group(2)))
    if words:
        out += [float(_EN_NUM_WORDS[w]) for w in re.findall(r"[a-z]+", text.lower()) if w in _EN_NUM_WORDS]
        # 英文簡寫「80K」「2M」(11-21：「預算抓8萬元」譯成「80K yuan」被當成數值不符)
        out += [float(m.group(1).replace(",", "")) * (1000 if m.group(2) in "Kk" else 10 ** 6)
                for m in _EN_KM_RE.finditer(text)]
    return out


_EN_KM_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)([KkM])(?![A-Za-z])")


_DOT_THOUSANDS_RE = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{3})+(?![\d.])")


def numbers_ok(src: str, translation: str) -> bool:
    """原文出現過的每個數值，譯文裡至少出現一次 (重複次數不比：西文「un 74%…un 74%」譯文只寫一次也是對的)。
    句點後剛好 3 位數的「400.000」兩種讀法都可以：西／德文的千分位 (400000) 或小數 (400.0) (11-19 full2：西文「400.000 viviendas」)。"""
    have = set(number_values(translation, words=True))
    alt = {round(float(m.group(0)), 6): float(m.group(0).replace(".", "")) for m in _DOT_THOUSANDS_RE.finditer(src or "")}
    return all(v in have or (v in alt and alt[v] in have) for v in number_values(src))


# 千分位「1,500 million」要整個吃進來 (S18 fuzz：原本只換「500 million」→「1,5億」，應為 15億)；不從數字中間開始比對
_EN_SCALED_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(million|billion)\b", re.I)


# 即時稿 (SenseVoice ITN) 偶爾把阿拉伯數字和國字數字混寫：「加裝十0只警示燈」=10、「二十5」=25、「第1三個議題」=13、
# 「第一7二個」=172、「第1八十四個」=184 (11-21 W11 240 分即時翻譯 31 段保留原文有 12 段是這種，W15 剩「第1三個」：數值比對看不懂)
# 後面要接量詞或單位才換：日文「第3四半期」(第 3 季) 的「3四」不是 34
_MIXED_NUM_RE = re.compile("(?<![0-9零〇一二三四五六七八九十百千萬億兩])[0-9零〇一二三四五六七八九十]+(?![0-9零〇一二三四五六七八九十百千萬億兩])"
                           "(?=[個个位台臺人輪轮只隻件條条日號号月年天週周次場场名家款項项輛辆張张支組组萬万千百億亿元%％倍])")
_CN_ONE_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _mixed_value(run: str) -> "int | None":
    """混寫 (同時有阿拉伯數字與國字數字) 的一串換成數值；不是混寫或看不懂就 None (原樣保留)。"""
    if not (re.search("[0-9]", run) and re.search("[零〇一二三四五六七八九十]", run)) or run.count("十") > 1:
        return None
    digit = lambda c: int(c) if c.isdigit() else _CN_ONE_DIGIT[c]
    if "十" not in run:
        return int("".join(str(digit(c)) for c in run))
    left, right = run.split("十")
    if len(right) > 1:
        return None
    tens = digit(left[-1]) if left else 1
    hundreds = int("".join(str(digit(c)) for c in left[:-1])) if len(left) > 1 else 0
    return hundreds * 100 + tens * 10 + (digit(right) if right else 0)


def fix_mixed_numbers(text: str) -> str:
    def repl(m: "re.Match") -> str:
        v = _mixed_value(m.group(0))
        return m.group(0) if v is None else str(v)
    return _MIXED_NUM_RE.sub(repl, text)


# 阿拉伯數字和萬／千／百混寫的一串 (即時稿 ITN 半套轉換)：「2萬5千」「1千2百」「3百」「2百50」「3萬零5百」「5百萬」「3萬5」。
# N2（11-24）：原本「萬後接數字」把「2萬5千」讀成 2萬5＝20,005 再乘千 → 送模型的原文變成「20,005,000」(錯的數字，而且數值檢查照樣通過)；
# 「3萬5」(三萬五＝35,000) 也被讀成 30,005。看不懂的 (係數不是 1 位數、單位順序不對、尾數位數對不上) 原樣保留。
_UNIT_VAL = {"十": 10, "百": 100, "千": 1000, "萬": 10 ** 4, "万": 10 ** 4, "億": 10 ** 8, "亿": 10 ** 8}
_CN_COMPOSITE_RE = re.compile(r"(?<![\d.,])\d+\s*[十百千萬万億亿](?:零?\d+\s*[十百千萬万億亿]|[萬万億亿]){0,12}(?:零?\d+)?(?![\d.,])")
_COMPOSITE_TOKEN_RE = re.compile(r"零?(\d*)\s*([十百千萬万億亿])")


def _composite_value(run: str) -> Optional[int]:
    """「2萬5千3百」→ 25300、「3萬5」→ 35000、「1千200」→ 1200、「3萬零5百」→ 30500、「5百萬」→ 5000000、「1億2千萬」→ 120000000；
    看不懂 → None。
    只有一個萬／千／億、後面沒有尾數 (「15萬」「2千」) 也回 None，交給 _CN_SCALED_RE (可帶小數)；單獨的「8十」「3百」要換。"""
    run = run.replace(" ", "")
    tokens, pos = [], 0
    for m in _COMPOSITE_TOKEN_RE.finditer(run):
        if m.start() != pos:
            return None
        tokens.append((m.group(1), m.group(2)))
        pos = m.end()
    rest = run[pos:]
    if len(tokens) == 1 and not rest and tokens[0][1] not in "十百":
        return None
    total, section, last_small, last_big = 0, 0, 10 ** 5, 10 ** 13
    for n, u in tokens:
        unit = _UNIT_VAL[u]
        if not n:                                # 「5百萬」「1億2千萬」：萬／億前面沒有數字，乘前面的整節
            if unit < 10 ** 4 or not section or unit >= last_big:
                return None
            total += section * unit
            section, last_small, last_big = 0, 10 ** 5, unit
            continue
        v = int(n)
        if unit < 10 ** 4:                       # 十百千：係數 1 位數、同一節裡由大到小
            if v > 9 or unit >= last_small:
                return None
            section += v * unit
            last_small = unit
        else:                                    # 萬億：前面整節 (含這個數字) 乘上去
            if unit >= last_big or v > 9999 or (section and v > 9):
                return None
            total += (section + v) * unit
            section, last_small, last_big = 0, 10 ** 5, unit
    if rest:
        zero = rest.startswith("零")
        digits = rest.lstrip("零")
        last_unit = _UNIT_VAL[tokens[-1][1]]
        if last_unit >= 10 ** 4 and section:
            return None
        lower = last_small if section else last_big   # 尾數接在哪個單位後面
        width = len(str(lower)) - 1                   # 萬後面 4 位、千後面 3 位、百後面 2 位、十後面 1 位
        if zero or len(digits) == width:              # 「3萬零5」「5萬3135」「1千200」：照數字加
            if int(digits) >= lower:
                return None
            section += int(digits)
        elif len(digits) == 1 and lower >= 100:        # 「3萬5」「1千2」「2百5」：口語省略後面的單位 (三萬五＝35,000)
            section += int(digits) * lower // 10
        else:
            return None
    return total + section


def prepare_source(text: str, target: str) -> str:
    """送模型前的原文，數字先換成目標語言的寫法 (模型自己換算常錯)：
    中翻英「200萬」→「2,000,000」、「1.5億」→「150,000,000」；英翻中「11 billion」→「110億」、「200 million」→「2億」、
    「2.5 million」→「250萬」 (11-19 自測：法→中「11 billion」→「十億」、「200 million」→「二百萬」)。"""
    text = fix_mixed_numbers(text)
    if target == "en":
        text = _CN_COMPOSITE_RE.sub(lambda m: (lambda v: m.group(0) if v is None else str(v))(_composite_value(m.group(0))), text)
        text = _CN_WAN_COMPOSITE_RE.sub(lambda m: str(int(m.group(1)) * 10 ** 4 + int(m.group(3))), text)
        def repl(m: "re.Match") -> str:
            v = _scaled(m.group(1), m.group(2))
            return f"{int(v):,}" if v == int(v) else f"{v:,}"
        return _CN_SCALED_RE.sub(repl, text)

    def repl_zh(m: "re.Match") -> str:
        # 用 Decimal 從原字串算，不能用 :g (只留 6 位有效數字：「12.345678 million」會變「1234.57萬」，
        # 模型照抄這個錯的數字，numbers_ok 比的又是換過的文字，錯的數字就會通過檢查)
        v = Decimal(re.sub(r"[,   ]", "", m.group(1))) * _EN_SCALE[m.group(2).lower()]
        unit, div = ("億", 10 ** 8) if v >= 10 ** 8 else ("萬", 10 ** 4)
        return format((v / div).normalize(), "f") + unit
    return _EN_SCALED_RE.sub(repl_zh, text)


_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}
# 國字數字後面接量詞／日期才換 (「九月二日」「十輪」「二十二人」)；「一起」「一下」這種一般用詞不動
_CN_NUM_RE = re.compile(r"[零〇一二兩两三四五六七八九十百千]+(?=[月日號号輪轮人位名台臺個个天週周年次場场小分秒萬万億亿%％倍款件條条家點点組组項项輛辆張张支])")


def _cn_to_int(s: str) -> Optional[int]:
    total, num = 0, 0
    if all(c in _CN_DIGIT for c in s):          # 「二〇二六」這種逐字寫法
        return int("".join(str(_CN_DIGIT[c]) for c in s))
    for c in s:
        if c in _CN_DIGIT:
            num = _CN_DIGIT[c]
        elif c in _CN_UNIT:
            total += (num or 1) * _CN_UNIT[c]
            num = 0
        else:
            return None
    return total + num


_CN_PERCENT_RE = re.compile(r"百分之([零〇一二兩两三四五六七八九十百]+)")


def cn_numerals_to_digits(text: str) -> str:
    """「九月二日」→「9月2日」、「十輪」→「10輪」、「二十二人」→「22人」、「百分之六」→「6%」。"""
    def repl(m: "re.Match") -> str:
        v = _cn_to_int(m.group(0))
        return m.group(0) if v is None else str(v)

    def repl_pct(m: "re.Match") -> str:
        v = _cn_to_int(m.group(1))
        return m.group(0) if v is None else f"{v}%"
    return _CN_NUM_RE.sub(repl, _CN_PERCENT_RE.sub(repl_pct, text))


def fix_numerals(src: str, translation: Optional[str], target: str) -> Optional[str]:
    """翻成中文的譯文數值對不上時，先把國字數字換成阿拉伯數字再比 (11-19 自測：模型照指示外常寫「九月二日」「十輪」，
    數值比對失敗、整行被保留成英文)。換了才對得上才用換過的；本來就對得上的不動。"""
    if not translation or target != "zh":
        return translation
    prepared = prepare_source(src, target)
    if numbers_ok(prepared, translation):
        return translation
    fixed = cn_numerals_to_digits(translation)
    return fixed if numbers_ok(prepared, fixed) else translation


# 中文職稱的英文：小模型把「組長」翻成 Captain（船長／隊長的意思），會議裡是 Team Lead
# (11-21 抽查中文 30 分即時翻譯：每場 4–5 次「Captain Cai」)。原文沒有隊長／船長／機長時才換。
_CAPTAIN_RE = re.compile(r"(?<![A-Za-z])Captain(?![A-Za-z])")   # 後面直接接中文字也要換 (W12「Captain蔡」：\b 在中文字前不算邊界)


def fix_titles(src: str, translation: Optional[str], target: str) -> Optional[str]:
    if not translation or target != "en" or "組長" not in src or any(t in src for t in ("隊長", "船長", "機長")):
        return translation
    return _CAPTAIN_RE.sub("Team Lead", translation)


# 英文職稱後面直接接中文人名 (11-21 W17／W20：「Team Lead蔡」每場 1–3 次，模型重翻也一樣) → 姓名轉拼音「Team Lead Cai」。
# 只轉職稱後面 1–3 個中文字、而且原文裡有這幾個字的；地名、職稱等其他夾雜的中文不轉 (「新竹」轉成 Xin Zhu 不對)。
_TITLED_NAME_RE = re.compile(r"\b(Team Lead|Manager|Engineer|Director|Supervisor|Specialist|Assistant|Mr\.|Ms\.|Mrs\.)\s*"
                             r"([一-鿿]{1,3})(?![一-鿿])(?:\s*\(([A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)?)\))?")


# 當姓時讀音和常用讀音不同的字 (lazy_pinyin 取常用讀音：曾 ceng、覃 tan)。只列 _COMMON_SURNAMES 裡有的 (2026-11-23)
_SURNAME_READING = {"曾": "Zeng", "覃": "Qin"}


def _surname_pinyin(ch: str) -> str:
    """單字姓的拼音 (首字大寫)：先查姓氏讀音，沒有才用 lazy_pinyin。"""
    if ch in _SURNAME_READING:
        return _SURNAME_READING[ch]
    from pypinyin import lazy_pinyin
    return lazy_pinyin(ch)[0].capitalize()


def romanize_titled_names(src: str, translation: Optional[str], target: str) -> Optional[str]:
    if not translation or target != "en" or not _TITLED_NAME_RE.search(translation):
        return translation
    try:
        from pypinyin import lazy_pinyin
    except ImportError as e:
        print(f"[translate] 沒有 pypinyin，人名不轉拼音：{e}")
        return translation

    def repl(m: "re.Match") -> str:
        name = m.group(2)
        if name not in src:
            return m.group(0)
        if m.group(3):   # 模型自己在括號寫了拼音「Team Lead蔡 (Cai)」：用它，拿掉括號
            return f"{m.group(1)} {m.group(3)}"
        syl = [p.capitalize() for p in lazy_pinyin(name)]
        syl[0] = _surname_pinyin(name[0])   # 第一個字是姓：用姓氏讀音 (曾 Zeng 不是 Ceng)
        roman = syl[0] if len(syl) == 1 else syl[0] + " " + "".join(syl[1:]).capitalize()
        return f"{m.group(1)} {roman}"
    return _TITLED_NAME_RE.sub(repl, translation)


# 英文譯文裡留下的中文星期 (11-21 W20／W24：「on周二 last week」)
_ZH_WEEKDAY_RE = re.compile(r"\s*(?:週|周|星期|禮拜|礼拜)([一二三四五六日天])")
_EN_WEEKDAY = {"一": "Monday", "二": "Tuesday", "三": "Wednesday", "四": "Thursday", "五": "Friday", "六": "Saturday",
               "日": "Sunday", "天": "Sunday"}


def fix_weekdays(translation: Optional[str], target: str) -> Optional[str]:
    if not translation or target != "en" or not _ZH_WEEKDAY_RE.search(translation):
        return translation
    out = _ZH_WEEKDAY_RE.sub(lambda m: " " + _EN_WEEKDAY[m.group(1)], translation).lstrip()
    return re.sub(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?=[A-Za-z0-9])", r"\1 ", out)


# 英文姓名後面直接接 (沒有空白) 中文職稱 (11-22 W11–W34 英文譯文共 41 處：「Wang经理」15、「Lin主任」11、「Xu经理」7…) → 「Manager Wang」
_ZH_TITLE_EN = {"總經理": "General Manager", "总经理": "General Manager", "經理": "Manager", "经理": "Manager",
                "副理": "Deputy Manager", "協理": "Assistant Vice President", "协理": "Assistant Vice President",
                "副總": "Vice President", "副总": "Vice President", "主任": "Director", "課長": "Section Chief",
                "课长": "Section Chief", "組長": "Team Lead", "组长": "Team Lead", "部長": "Department Head",
                "部长": "Department Head", "處長": "Division Director", "处长": "Division Director",
                "工程師": "Engineer", "工程师": "Engineer", "專員": "Specialist", "专员": "Specialist",
                "先生": "Mr.", "小姐": "Ms.", "女士": "Ms."}
_NAME_ZH_TITLE_RE = re.compile(r"\b([A-Z][a-z]+)(" + "|".join(sorted(_ZH_TITLE_EN, key=len, reverse=True)) + r")")




# 常見單字姓 (繁簡)：判斷原文「X經理」的 X 是不是姓
_COMMON_SURNAMES = set(
    "王李張张劉刘陳陈楊杨黃黄趙赵吳吴周徐孫孙馬马朱胡郭何高林羅罗鄭郑梁謝谢宋唐許许韓韩馮冯鄧邓曹彭曾蕭萧肖田董袁潘"
    "于蔣蒋蔡余杜葉叶程蘇苏魏呂吕丁任沈姚盧卢姜崔鍾钟譚谭陸陆汪范金石廖賈贾夏韋韦付方白鄒邹孟熊秦邱江尹薛閻阎段雷侯龍龙"
    "史陶黎賀贺顧顾毛郝龔龚邵萬万錢钱嚴严覃武戴莫孔向湯汤柯洪游傅簡简翁")


def fix_name_zh_titles(src: str, translation: Optional[str], target: str) -> Optional[str]:
    """只換原文真的有「X經理」而且 X 的拼音就是譯文那個名字的：「Project经理」(專案經理) 不會變成「Manager Project」。"""
    if not translation or target != "en" or not _NAME_ZH_TITLE_RE.search(translation):
        return translation
    try:
        from pypinyin import lazy_pinyin  # noqa: F401  只檢查有沒有裝 (拼音由 _surname_pinyin 取)
    except ImportError as e:
        print(f"[translate] 沒有 pypinyin，姓名後的中文職稱不換：{e}")
        return translation
    # 原文的「姓＋職稱」：職稱 (英文) → 這個職稱前面出現過的姓的拼音 (只收常見姓：「專案經理」的「案」不是姓)
    by_title: Dict[str, set] = {}
    for m in re.finditer(r"([一-鿿])(" + "|".join(sorted(_ZH_TITLE_EN, key=len, reverse=True)) + ")", src or ""):
        if m.group(1) in _COMMON_SURNAMES:
            by_title.setdefault(_ZH_TITLE_EN[m.group(2)], set()).add(_surname_pinyin(m.group(1)))

    def repl(m: "re.Match") -> str:
        title = _ZH_TITLE_EN[m.group(2)]
        names = by_title.get(title, set())
        if m.group(1) in names:
            return f"{title} {m.group(1)}"
        if len(names) == 1:   # 模型把姓翻錯 (原文「許經理」、譯文「Xiang经理」)：用原文唯一的那個姓
            return f"{title} {next(iter(names))}"
        return m.group(0)
    return _NAME_ZH_TITLE_RE.sub(repl, translation)


# 姓和職稱都留中文 (11-22 重放：「蔡组长」4 處)：單字姓 (前面不是中文字，原文裡有) → 「Team Lead Cai」
_CJK_NAME_TITLE_RE = re.compile(r"(?<![一-鿿])([一-鿿])(" +
                                "|".join(sorted(_ZH_TITLE_EN, key=len, reverse=True)) + r")(?![一-鿿])")


def fix_cjk_name_titles(src: str, translation: Optional[str], target: str) -> Optional[str]:
    if not translation or target != "en" or not _CJK_NAME_TITLE_RE.search(translation):
        return translation
    try:
        from pypinyin import lazy_pinyin  # noqa: F401  只檢查有沒有裝 (拼音由 _surname_pinyin 取)
    except ImportError as e:
        print(f"[translate] 沒有 pypinyin，中文姓名不轉拼音：{e}")
        return translation

    def repl(m: "re.Match") -> str:
        if m.group(1) not in src:
            return m.group(0)
        out = f"{_ZH_TITLE_EN[m.group(2)]} {_surname_pinyin(m.group(1))}"
        s, e = m.start(), m.end()
        left = " " if s > 0 and translation[s - 1].isascii() and translation[s - 1].isalnum() else ""
        right = " " if e < len(translation) and translation[e].isascii() and translation[e].isalnum() else ""
        return left + out + right
    return _CJK_NAME_TITLE_RE.sub(repl, translation)


# 英文譯文裡最常留下的一般商用詞 (11-22 W11–W34 英文譯文：「报价」17、「全员」11、「出差」6；模型寫成簡體留在句中)。
# 只收一般詞彙，不放人名、地名、產品名 (那些來自會議詞彙)。
_ZH_COMMON_EN = {"報價": "quotation", "报价": "quotation", "全員": "all staff", "全员": "all staff",
                 "出差": "business trip", "培訓": "training", "培训": "training"}
_ZH_COMMON_RE = re.compile("|".join(_ZH_COMMON_EN))


def fix_common_zh_words(translation: Optional[str], target: str) -> Optional[str]:
    if not translation or target != "en" or not _ZH_COMMON_RE.search(translation):
        return translation

    # 先在換上去的詞左右做記號，再看記號外側是不是英文字母／數字決定補不補空白 (「全员培训」→「all staff training」)
    lm, rm = "\x01", "\x02"
    out = _ZH_COMMON_RE.sub(lambda m: lm + _ZH_COMMON_EN[m.group(0)] + rm, translation)
    out = re.sub(rm + r"\s*" + lm, " ", out)
    out = re.sub(r"(?<=[A-Za-z0-9])" + lm, " ", out).replace(lm, "")
    out = re.sub(rm + r"(?=[A-Za-z0-9])", " ", out).replace(rm, "")
    return out


def postfix(src: str, translation: Optional[str], target: str) -> Optional[str]:
    """模型輸出的固定修正：數字 (fix_numerals)、職稱 (fix_titles)、職稱後的中文人名轉拼音 (romanize_titled_names)、
    姓名後的中文職稱 (fix_name_zh_titles)、常見商用詞 (fix_common_zh_words)、中文星期 (fix_weekdays)。"""
    out = romanize_titled_names(src, fix_titles(src, fix_numerals(src, translation, target), target), target)
    out = fix_cjk_name_titles(src, fix_name_zh_titles(src, out, target), target)
    return fix_weekdays(fix_common_zh_words(out, target), target)


def unit_ok(src: str, translation: Optional[str], target: str) -> bool:
    """這個單位的譯文可用：有內容、翻英文時沒夾中文字、數值都在。"""
    return bool(translation) and not untranslated_left(translation, target) \
        and numbers_ok(prepare_source(src, target), translation)


def _in_number(s: str, i: int) -> bool:
    """s[i] 夾在數字中間 (千分位「12,345」、小數「3.75」、連續數字)：切在 i 之前或把 s[i] 當切點都會拆開數字。"""
    if i <= 0 or i >= len(s):
        return False
    a, b = s[i - 1], s[i]
    if b in ",. " and i + 1 < len(s):
        return a.isdigit() and s[i + 1].isdigit()
    return (a.isdigit() or a in ",.") and b.isdigit() and (a.isdigit() or (i >= 2 and s[i - 2].isdigit()))


def _split_long(sentence: str, limit: int) -> List[str]:
    """太長的句子切成 ≤ limit 字的翻譯單位：在後半段最後一個「，,、 」後切，沒有就硬切。
    不切在數字中間 (S13：「1500萬」硬切成「1」＋「500萬」兩個單位各自通過數值比對，組回去金額錯了)：
    夾在數字中間的「,」「 」不當切點，硬切落在數字裡就退到那串數字之前 (整串都是數字才照原樣硬切)。"""
    out = []
    while len(sentence) > limit:
        cut = max((i for i in range(limit) if sentence[i] in "，,、 " and not _in_number(sentence, i)), default=-1)
        if cut >= limit // 2:
            cut += 1
        else:
            cut = limit
            while cut > 0 and _in_number(sentence, cut):
                cut -= 1
            if cut == 0:
                cut = limit
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
    """要送模型的 (單位索引, 原文) 依序合成請求，每個請求原文 ≤ limit 字 (預設 CHUNK_CHARS)；
    第一個請求較小 (FIRST_CHUNK_CHARS)，網頁比較快看到第一段譯文 (11-19 實測 GS3 30 分中翻英第一段 80 s 才出現)。"""
    limit = CHUNK_CHARS if limit is None else limit
    first = min(FIRST_CHUNK_CHARS, limit)
    chunks: List[List[Tuple[int, str]]] = []
    buf: List[Tuple[int, str]] = []
    size = 0
    for idx, u in units:
        if buf and size + len(u) > (first if not chunks else limit):
            chunks.append(buf)
            buf, size = [], 0
        buf.append((idx, u))
        size += len(u)
    if buf:
        chunks.append(buf)
    return chunks


def build_prompt(chunk: Sequence[Tuple[int, str]], target: str) -> str:
    lines = "\n".join(f"{n}| {prepare_source(u, target)}" for n, (_i, u) in enumerate(chunk, 1))
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
    if not got:
        # 模型把格式裡的「N」照抄 (11-19 exp_first2：Hailo 第一段 19 行都寫成「N| …」，整段改成逐句重翻，多花約 4 分鐘)：
        # 行數剛好等於輸入行數時依序對應
        lit = [m.group(1).strip() for m in map(_LITERAL_N_RE.match, (out or "").splitlines()) if m]
        if len(lit) == n and all(lit):
            got = {k: t for k, t in enumerate(lit, 1)}
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
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=POLL_SEC)
            if not task.done() and should_stop():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                return None
    except asyncio.CancelledError:
        # 外層被取消 (即時翻譯停掉：取消錄音、尾端逾時)：內層串流也要取消並關掉，不然 Hailo 一直生成成孤兒 (S16)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):   # 內層剛好丟的錯不蓋掉取消
            await task
        raise
    return task.result()


def _num_predict(chunk: Sequence[Tuple[int, str]], target: str) -> int:
    chars = sum(len(u) for _i, u in chunk)
    # 中翻英：每個中文字約 1.2 token；英翻中：每個英文字元約 0.5 token；加上編號
    est = chars * (1.3 if target == "en" else 0.7) + 6 * len(chunk)
    return int(min(900, max(120, est)))


async def _translate_flat(flat: Sequence[str], target: str,
                          on_progress: Optional[Callable[[int, int, Dict[int, str], int], None]],
                          should_stop: Callable[[], bool], use_cpu: bool, one_chunk: bool = False) -> Dict[str, Any]:
    """one_chunk：要翻的單位合成一個請求 (即時翻譯：呼叫端已控制字數)。
    逐字稿與紀要共用：flat 是依序的翻譯單位；已是目標語言的照抄，其餘依序合成請求，Hailo 與 CPU 兩路同時翻。
    on_progress(已翻段數, 總段數, done, 從頭連續翻好的單位數)。回傳 {done, chunks, translated_chunks, kept_units, units,
    fallback_units, number_fallback_units, stopped}；done 沒有的單位由呼叫端保留原文。"""
    if target not in SYSTEM:
        raise ValueError("target 必須是 en 或 zh")
    done: Dict[int, str] = {}
    todo = []
    for i, u in enumerate(flat):
        if in_target_language(u, target):
            done[i] = u
        else:
            todo.append((i, u))
    chunks = [todo] if one_chunk and todo else group_chunks(todo)
    total = len(chunks)
    finished = [False] * total
    stats = {"fallback_units": 0, "number_fallback_units": 0, "stopped": False, "llm_calls": 0}
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

    def report() -> None:
        if on_progress:
            on_progress(sum(finished), total, done, prefix_upto())

    async def translate_chunk(c: int, *, hailo_only: bool, cpu_first: bool) -> bool:
        chunk = chunks[c]
        stats["llm_calls"] += 1
        out = await _complete(build_prompt(chunk, target), target, _num_predict(chunk, target),
                              hailo_only=hailo_only, cpu_first=cpu_first, should_stop=should_stop)
        if out is None:
            return False
        got = parse_output(out, len(chunk))
        for n, (idx, src) in enumerate(chunk, 1):
            if n in got:
                got[n] = postfix(src, got[n], target)
            if unit_ok(src, got.get(n), target):
                done[idx] = got[n]
                continue
            # 對不上的單位、翻英文還夾中文字 (11-19 GS3 30 分 246 行有 2 行留下「组长」)、或數值對不上：單獨重翻一次
            stats["llm_calls"] += 1
            one = await _complete(build_prompt([(idx, src)], target), target, _num_predict([(idx, src)], target),
                                  hailo_only=hailo_only, cpu_first=cpu_first, should_stop=should_stop)
            if one is None:
                return False
            single = postfix(src, parse_output(one, 1).get(1), target)
            if unit_ok(src, single, target):
                done[idx] = single
                continue
            other = None
            if (cpu_first or use_cpu) and not should_stop():
                # 同一個模型兩次都沒翻好：換另一個模型再試一次。Hailo 那路 (11-19 v4：「Complete全员 training」兩次都夾中文)
                # 換 CPU qwen2.5:3b，只在可以用 CPU 時 (沒在錄音、高精度逐字稿沒在跑)；CPU 那路換 Hailo qwen3:1.7b
                # (11-19 exp_first：CPU 那路把整段中文改寫成簡體中文、「第三個議題是…」單獨重翻仍回中文，GS3 1200 字 6 句沒翻)
                stats["llm_calls"] += 1
                alt = await _complete(build_prompt([(idx, src)], target), target, _num_predict([(idx, src)], target),
                                      hailo_only=cpu_first, cpu_first=not cpu_first, should_stop=should_stop)
                if alt is None:
                    return False
                other = postfix(src, parse_output(alt, 1).get(1), target)
                if unit_ok(src, other, target):
                    done[idx] = other
                    continue
            prepared = prepare_source(src, target)
            usable = [t for t in (got.get(n), single, other) if t and numbers_ok(prepared, t) and mostly_translated(t, target)]
            if usable:                          # 數值對、只是夾少數中文字：用夾最少的那個 (比原文好；11-21 W17「New竹」「报价」)
                done[idx] = min(usable, key=lambda t: len(_CJK_RE.findall(t)))
            elif any(t and not numbers_ok(prepared, t) for t in (got.get(n), single, other)) and not any(
                    t and numbers_ok(prepared, t) for t in (got.get(n), single, other)):
                stats["number_fallback_units"] += 1   # 數值都不對：保留原文，不讓錯的數字出現
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
    if queue and not stats["stopped"]:          # 兩路都失敗：最後再用預設順序試一次 (不能用 CPU 時只試 Hailo：錄音中禁止 CPU 推論)
        for c in list(queue):
            if should_stop():                   # 開始錄音：不再送請求 (S13：原本仍逐段送 Hailo 請求，且回報 stopped=False)
                stats["stopped"] = True
                break
            try:
                if await translate_chunk(c, hailo_only=not use_cpu, cpu_first=False):
                    finished[c] = True
                    queue.remove(c)
                else:
                    stats["stopped"] = True
                    break
            except LLMError as e:
                logger.warning("[Translate] 第 %d/%d 段保底也失敗，保留原文：%s", c + 1, total, e)
    return {"done": done, "chunks": total, "translated_chunks": sum(finished), "kept_units": len(flat) - len(todo),
            "units": len(flat), "fallback_units": stats["fallback_units"],
            "number_fallback_units": stats["number_fallback_units"], "stopped": stats["stopped"],
            "llm_calls": stats["llm_calls"]}   # 呼叫模型次數 (含單句重翻)；即時翻譯用來看 NPU 被翻譯占多少


def _localize(text: str, target: str) -> str:
    if target != "zh":
        return text
    from summary_utils import to_taiwan_traditional
    return to_taiwan_traditional(text)


async def translate_transcript(text: str, target: str,
                               on_progress: Optional[Callable[[int, int, str], None]] = None,
                               should_stop: Callable[[], bool] = lambda: False,
                               use_cpu: bool = True) -> Dict[str, Any]:
    """翻譯完整逐字稿。on_progress(已翻段數, 總段數, 目前連續翻好的部分)；回傳 {text, chunks, kept_units, fallback_units, stopped…}。"""
    rows = parse_lines(text)
    flat = [u for _spk, units in rows for u in units]

    def progress(d: int, t: int, done: Dict[int, str], upto: int) -> None:
        if on_progress:
            on_progress(d, t, _localize(assemble(rows, done, target, upto=upto), target))

    res = await _translate_flat(flat, target, progress, should_stop, use_cpu)
    out = _localize(assemble(rows, res.pop("done"), target), target)
    return {"text": out, **res}


_MIN_HEAD_RE = re.compile(r"^\s*【[^】\n]{1,20}】\s*$")
_MIN_BULLET_RE = re.compile(r"^(\s*[•\-*]\s*)(.*)$")
_EMPTY_ITEM = {"無", "无", "none", "無。", "-", "—", "n/a", "na"}


async def translate_minutes(text: str, target: str, should_stop: Callable[[], bool] = lambda: False,
                            use_cpu: bool = False) -> Dict[str, Any]:
    """網頁紀要翻譯 (「【摘要】\n• …」格式，段落標題網頁已給目標語言)：逐行翻，跟逐字稿同一套
    (已是目標語言的行照抄、對不上／夾中文字／數值不符的行重翻、數值仍不符就保留原文)。
    原本 /api/translate 整段送模型 (11-19 自測 11 份測資)：數字常翻錯、德文那份完全沒翻、英文會議裡夾的德文／西文行被網頁當成英文直接顯示。"""
    lines = (text or "").splitlines()
    units: List[str] = []
    slots: List[Tuple[int, str, int]] = []        # (行號, 項目符號, 單位索引)
    out_lines = list(lines)
    for i, line in enumerate(lines):
        if not line.strip() or _MIN_HEAD_RE.match(line):
            continue
        m = _MIN_BULLET_RE.match(line)
        bullet, body = (m.group(1), m.group(2)) if m else ("", line.strip())
        if body.strip().lower() in _EMPTY_ITEM:
            out_lines[i] = bullet + ("None" if target == "en" else "無")
            continue
        slots.append((i, bullet, len(units)))
        units.append(body.strip())
    res = await _translate_flat(units, target, None, should_stop, use_cpu)
    done = res.pop("done")
    for i, bullet, k in slots:
        out_lines[i] = bullet + done.get(k, units[k])
    return {"text": _localize("\n".join(out_lines), target).strip(), **res}


_MD_BULLET_RE = re.compile(r"^(\s*[-*]\s+)(.+)$")


def foreign_minutes_line(body: str) -> bool:
    """英文紀要的條目明顯是別的拉丁字母語言 (法／西／德／越…)：有英文沒有的帶符號字母，或西／法／德／印尼文功能詞 2 個以上。
    比 in_target_language 嚴：精簡的英文條目 (「7 people」) 不算，紀要後處理不為它多叫模型。"""
    if _CJK_RE.search(body) or in_target_language(body, "en"):
        return False
    words = re.findall(r"[A-Za-z]+", body.lower())
    return bool(_NON_EN_LATIN_RE.search(body)) or sum(w in _FOREIGN_FUNCTION_WORDS for w in words) >= 2


async def english_minutes_lines(md: str, should_stop: Callable[[], bool] = lambda: False,
                                use_cpu: bool = True) -> Tuple[str, int]:
    """英文紀要 (內部 Markdown) 裡夾著的外語條目翻成英文 (11-19 法文 6 分 e2e：英文紀要裡有
    「Pétrole et prix du pétrole : Prix du pétrole à 20…」等法文條目)。回傳 (新紀要, 翻了幾條)；沒有這種條目時不叫模型。"""
    lines = (md or "").splitlines()
    slots = []
    for i, line in enumerate(lines):
        m = _MD_BULLET_RE.match(line)
        if m and foreign_minutes_line(m.group(2)):
            slots.append((i, m.group(1), m.group(2).strip()))
    if not slots:
        return md, 0
    res = await _translate_flat([b for _i, _p, b in slots], "en", None, should_stop, use_cpu)
    done = res["done"]
    n = 0
    for k, (i, prefix, body) in enumerate(slots):
        if k in done and done[k] != body:
            lines[i] = prefix + done[k]
            n += 1
    return "\n".join(lines), n
