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
_NON_EN_LATIN_RE = re.compile(r"[À-ɏḀ-ỿ]")     # 帶附加符號的拉丁字母：德、法、西、越…
_OTHER_SCRIPT_RE = re.compile(r"[฀-๿぀-ヿ가-힯Ѐ-ӿ]")   # 泰、假名、韓、俄
# 西、法、德、印尼文常見功能詞 (不收跟英文同形的 a、in、an、die、no…)
_FOREIGN_FUNCTION_WORDS = frozenset(
    "de la el los las que y del por para con una se lo su al es "            # 西
    "le les et des du est une pour dans avec sur au aux pas qui ce sont "     # 法
    "der das und ist nicht mit ein eine ich wir sie auf zu den dem von auch "  # 德
    "yang dan di ini itu dengan untuk tidak ada kami kita akan dari ke juga".split())   # 印尼
_NUM_LINE_RE = re.compile(r"^\s*(\d+)\s*[|｜.、:：)）]\s*(.*)$")

SYSTEM = {
    "en": ("You are a professional interpreter. Translate each numbered line of a meeting transcript into natural English. "
           "Keep the same numbers, one output line per input line, written as \"N| translation\". "
           "Keep names, company names and product names as they are. Copy every number with the same digits "
           "(write 12,500 as 12,500; never spell numbers out in words). Output only the numbered lines."),
    "zh": ("你是專業口譯員。把會議逐字稿每一行編號的句子翻成通順的台灣繁體中文。"
           "每一行輸入對應一行輸出，格式「N| 翻譯」，編號照原文。人名、公司名、產品名照原文。"
           "數字一律用阿拉伯數字、數值不可改變（12,500 可寫成 12,500 或 1.25萬，不可寫成國字）。只輸出編號的各行。"),
}


def in_target_language(text: str, target: str) -> bool:
    """這個單位已經是目標語言 (照抄，不送模型)。
    英文：沒有中文字、沒有英文以外的拉丁字母 (ä é ñ ß…)、英文功能詞比例夠 (summary_utils.english_share ≥ 0.5)。
    只看「沒有中文字」不夠：11-19 德文會議按 Translate to English，134 句德文全被當成英文照抄。太短的英文句 (「Yes.」) 會送模型，只是多花一點時間。
    中文：中文字不少於英文字母的一半。"""
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
    return cjk > 0 and cjk * 2 >= latin


def untranslated_left(translation: str, target: str) -> bool:
    """譯文沒翻乾淨：翻成英文還夾著中文字 (模型把職稱、人名留成中文)；翻成中文卻一個中文字都沒有
    (11-19 自測：en_short 3 行、德文那份 8 行模型原樣回英文，原本被當成翻好了)。"""
    if target == "en":
        return bool(_CJK_RE.search(translation))
    return not _CJK_RE.search(translation) and len(_LATIN_RE.findall(translation)) >= 4   # 「AfD」「IBM」這種縮寫翻中文本來就保留


# 數字保護 (2026-11-19 紀要翻譯自測：中翻英「200萬」→「200,000」、「40萬」→「40,000」；法→中「11 billion」→「十億」、
# 「200 million」→「二百萬」；英→中「$800,000」→「八百萬美元」)：中翻英前先把「N萬／N億／N千」換成完整阿拉伯數字，
# 不讓模型自己換算；翻完比對數值 (萬、億、thousand、million、billion 都換算成數值)，原文的數值譯文要都有，
# 不符就單獨重翻，仍不符就保留原文 (寧可不翻，也不能翻錯數字)。月份 (9月→September) 不比。
_CN_SCALE = {"千": 10 ** 3, "萬": 10 ** 4, "万": 10 ** 4, "億": 10 ** 8, "亿": 10 ** 8}
_EN_SCALE = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9}
_NUM_RE = re.compile(r"(\d+(?:,\d{3})+|\d+(?:\.\d+)?)\s*(千|萬|万|億|亿|thousand|million|billion)?(?!\d)(?!,\d{3})", re.I)
_CN_SCALED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(千|萬|万|億|亿)")


def _scaled(num: str, unit: Optional[str]) -> float:
    v = float(num.replace(",", ""))
    if unit:
        v *= _CN_SCALE.get(unit, _EN_SCALE.get(unit.lower(), 1))
    return round(v, 6)


_EN_NUM_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                            "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_EN_NUM_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90})


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
    return out


def numbers_ok(src: str, translation: str) -> bool:
    """原文的每個數值在譯文裡都出現 (次數也夠)。"""
    have = number_values(translation, words=True)
    for v in number_values(src):
        if v in have:
            have.remove(v)
        else:
            return False
    return True


_EN_SCALED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(million|billion)\b", re.I)


def prepare_source(text: str, target: str) -> str:
    """送模型前的原文，數字先換成目標語言的寫法 (模型自己換算常錯)：
    中翻英「200萬」→「2,000,000」、「1.5億」→「150,000,000」；英翻中「11 billion」→「110億」、「200 million」→「2億」、
    「2.5 million」→「250萬」 (11-19 自測：法→中「11 billion」→「十億」、「200 million」→「二百萬」)。"""
    if target == "en":
        def repl(m: "re.Match") -> str:
            v = _scaled(m.group(1), m.group(2))
            return f"{int(v):,}" if v == int(v) else f"{v:,}"
        return _CN_SCALED_RE.sub(repl, text)

    def repl_zh(m: "re.Match") -> str:
        v = _scaled(m.group(1), m.group(2))
        return f"{v / 10 ** 8:g}億" if v >= 10 ** 8 else f"{v / 10 ** 4:g}萬"
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


def cn_numerals_to_digits(text: str) -> str:
    """「九月二日」→「9月2日」、「十輪」→「10輪」、「二十二人」→「22人」。"""
    def repl(m: "re.Match") -> str:
        v = _cn_to_int(m.group(0))
        return m.group(0) if v is None else str(v)
    return _CN_NUM_RE.sub(repl, text)


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


def unit_ok(src: str, translation: Optional[str], target: str) -> bool:
    """這個單位的譯文可用：有內容、翻英文時沒夾中文字、數值都在。"""
    return bool(translation) and not untranslated_left(translation, target) \
        and numbers_ok(prepare_source(src, target), translation)


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


async def _translate_flat(flat: Sequence[str], target: str,
                          on_progress: Optional[Callable[[int, int, Dict[int, str], int], None]],
                          should_stop: Callable[[], bool], use_cpu: bool) -> Dict[str, Any]:
    """逐字稿與紀要共用：flat 是依序的翻譯單位；已是目標語言的照抄，其餘依序合成請求，Hailo 與 CPU 兩路同時翻。
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
    chunks = group_chunks(todo)
    total = len(chunks)
    finished = [False] * total
    stats = {"fallback_units": 0, "number_fallback_units": 0, "stopped": False}
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
        out = await _complete(build_prompt(chunk, target), target, _num_predict(chunk, target),
                              hailo_only=hailo_only, cpu_first=cpu_first, should_stop=should_stop)
        if out is None:
            return False
        got = parse_output(out, len(chunk))
        for n, (idx, src) in enumerate(chunk, 1):
            if n in got:
                got[n] = fix_numerals(src, got[n], target)
            if unit_ok(src, got.get(n), target):
                done[idx] = got[n]
                continue
            # 對不上的單位、翻英文還夾中文字 (11-19 GS3 30 分 246 行有 2 行留下「组长」)、或數值對不上：單獨重翻一次
            one = await _complete(build_prompt([(idx, src)], target), target, _num_predict([(idx, src)], target),
                                  hailo_only=hailo_only, cpu_first=cpu_first, should_stop=should_stop)
            if one is None:
                return False
            single = fix_numerals(src, parse_output(one, 1).get(1), target)
            if unit_ok(src, single, target):
                done[idx] = single
                continue
            prepared = prepare_source(src, target)
            usable = [t for t in (got.get(n), single) if t and numbers_ok(prepared, t)]
            if usable:                          # 數值對、只是夾中文字：用它 (比原文好)
                done[idx] = usable[0]
            elif got.get(n) or single:          # 數值兩次都不對：保留原文，不讓錯的數字出現
                stats["number_fallback_units"] += 1
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
    return {"done": done, "chunks": total, "translated_chunks": sum(finished), "kept_units": len(flat) - len(todo),
            "units": len(flat), "fallback_units": stats["fallback_units"],
            "number_fallback_units": stats["number_fallback_units"], "stopped": stats["stopped"]}


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
