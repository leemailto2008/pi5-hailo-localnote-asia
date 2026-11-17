# -*- coding: utf-8 -*-
"""Whisper（Hailo-10H）語言判錯量測：非英語音檔被輸出成英文的比例。

在 Pi 上跑（需要 Hailo-10H 與 hailo_whisper）：
    python3 tools/whisper_lang_survey.py --repo <部署目錄> --out <結果.jsonl> <wav...>
    python3 tools/whisper_lang_survey.py --summary <結果.jsonl> [<結果2.jsonl>]   # 只印統計（可在 PC 上跑）

- wav 檔名開頭到「__」為止是語言標籤（ja__xxx.wav、zh_en__xxx.wav）；標籤 en* 的檔案「輸出英文」不算錯。
- 切片跟即時逐字稿一樣：audio_splice.pause_cut_index 在 4–9.5 s 的停頓處切。
- 每片呼叫 HailoWhisperEngine.transcribe(language=None)（即時稿選 Whisper 時的路徑），
  另外記錄引擎內每一次 generate_all_text 的語言參數與原始輸出（看得出自動偵測的結果與重解）。
- --force LANG|native：改用指定語言（native = 依標籤）解，看「正確語言」會輸出什麼（text 就是指定語言的結果）。
"""
import argparse
import json
import os
import re
import sys
import time
import wave
from collections import defaultdict

SR = 16000

# 英文判斷：只用不會和西／法／德／印尼／越南文撞字的英文功能詞（去掉 a、in、an、was、will、so 等）
EN_WORDS = frozenset(
    "the and is are were you we they that this with have has it of to for what which not but there be would can "
    "do does did about just my your our their he she them these those been from because if when how why okay "
    "yeah yes thank thanks hello bye please i'm it's that's don't i".split())
_LATIN = re.compile(r"[A-Za-z]")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def is_english(text: str) -> bool:
    """輸出是不是英文句子：字母幾乎都是拉丁字母，而且英文功能詞佔兩成以上。"""
    letters = _LETTER.findall(text or "")
    if not letters:
        return False
    latin = sum(1 for c in letters if _LATIN.match(c))
    if latin < 0.8 * len(letters):
        return False
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return False
    hits = sum(1 for w in words if w in EN_WORDS)
    if len(words) == 1:
        return hits == 1
    return hits >= 0.2 * len(words)


def script_of(text: str) -> str:
    """輸出用的文字系統（看自動偵測大概判成哪一種）。"""
    t = text or ""
    if re.search(r"[぀-ヿ]", t):
        return "kana"
    if re.search(r"[가-힯]", t):
        return "hangul"
    if re.search(r"[฀-๿]", t):
        return "thai"
    if re.search(r"[一-鿿]", t):
        return "cjk"
    if is_english(t):
        return "en"
    if _LATIN.search(t):
        return "latin"
    return "none" if not t.strip() else "other"


# --force native：標籤 → Whisper 語言碼（Whisper-Small 沒有粵語／台語，用 zh）
NATIVE = {"ja": "ja", "ko": "ko", "yue": "zh", "nan": "zh", "vi": "vi", "th": "th", "id": "id", "es": "es", "fr": "fr",
          "de": "de", "zh_en": "zh", "zh_accent": "zh", "zh": "zh", "en": "en"}


def lang_tag(path: str) -> str:
    return os.path.basename(path).split("__", 1)[0]


def load_wav(path: str):
    import numpy as np
    with wave.open(path, "rb") as wf:
        assert wf.getframerate() == SR and wf.getnchannels() == 1 and wf.getsampwidth() == 2, path
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def slices(x, pause_cut_index):
    pos, n = 0, len(x)
    while n - pos > SR // 2:
        if n - pos <= int(9.5 * SR):
            yield pos, n
            return
        cut = pause_cut_index(x[pos:pos + int(9.5 * SR)], SR, 4.0, 9.5)
        yield pos, pos + cut
        pos += cut


class _Recorder:
    """包住 Speech2Text，記錄每次 generate_all_text 的語言與原始輸出。"""

    def __init__(self, s2t):
        self._s2t = s2t
        self.calls = []

    def generate_all_text(self, **kw):
        out = self._s2t.generate_all_text(**kw)
        self.calls.append([kw.get("language"), out])
        return out

    def __getattr__(self, name):
        return getattr(self._s2t, name)


def run(args):
    sys.path.insert(0, args.repo)
    sys.path.insert(0, os.path.join(args.repo, "code_dispatcher"))
    from audio_splice import pause_cut_index
    from hailo_whisper.engine import HailoWhisperEngine
    from npu_share import shared_group
    state = {}

    def open_engine():
        for _ in range(10):
            eng = HailoWhisperEngine(group_id=shared_group(force_refresh=True))
            if eng.is_hardware_accelerated():
                state["rec"] = _Recorder(eng._s2t)
                eng._s2t = state["rec"]
                state["eng"] = eng
                return
            time.sleep(30)
        raise SystemExit("Hailo Whisper 無法初始化")

    def transcribe(audio, language):
        """NPU 被別的行程重設 (HailoCommunicationClosedException) 時重開引擎再試。"""
        for attempt in range(5):
            try:
                return state["eng"].transcribe(audio, language=language)
            except Exception as e:   # HailoRT 例外型別依版本不同
                print(f"transcribe failed ({type(e).__name__}: {e}); reopen engine", flush=True)
                time.sleep(20)
                open_engine()
        raise SystemExit("重試 5 次仍失敗")

    open_engine()
    done = set()
    if os.path.exists(args.out):   # 中斷後接著跑：已完成的檔案跳過
        rows = [json.loads(line) for line in open(args.out, encoding="utf-8")]
        done = {r["file"] for r in rows if r.get("last")}
    with open(args.out, "a", encoding="utf-8") as fo:
        for path in args.wavs:
            if os.path.basename(path) in done:
                continue
            x = load_wav(path)
            tag = lang_tag(path)
            cuts = list(slices(x, pause_cut_index))
            for i, (a, b) in enumerate(cuts):
                rec = state["rec"]
                rec.calls = []
                t0 = time.perf_counter()
                forced = (NATIVE.get(tag, "zh") if args.force == "native" else args.force) if args.force else None
                res = transcribe(x[a:b], forced)
                rec = state["rec"]
                row = {"file": os.path.basename(path), "tag": tag, "i": i, "t0": round(a / SR, 2), "t1": round(b / SR, 2),
                       "text": res.get("text", ""), "calls": rec.calls, "ms": round((time.perf_counter() - t0) * 1000), "last": i == len(cuts) - 1}
                if forced:
                    row["forced_lang"] = forced
                fo.write(json.dumps(row, ensure_ascii=False) + "\n")
                fo.flush()
            print(f"done {os.path.basename(path)}", flush=True)


def summary(paths):
    for p in paths:
        rows = list({(r["file"], r["i"]): r for r in map(json.loads, open(p, encoding="utf-8"))}.values())
        agg = defaultdict(lambda: defaultdict(float))
        for r in rows:
            g = agg[r["tag"]]
            dur = r["t1"] - r["t0"]
            spoken = bool(r["text"].strip())
            g["n"] += 1
            g["sec"] += dur
            g["spoken"] += spoken
            if spoken and not r["tag"].startswith("en") and is_english(r["text"]):
                g["en_n"] += 1
                g["en_sec"] += dur
            if len(r.get("calls", [])) > 1:
                g["retry"] += 1
        print(f"== {p}")
        print(f"{'tag':<10}{'slices':>7}{'spoken':>7}{'en_out':>7}{'en%':>7}{'en_sec':>8}{'en_sec%':>8}{'retry':>6}")
        tot = defaultdict(float)
        for tag in sorted(agg):
            g = agg[tag]
            for k, v in g.items():
                tot[k] += v
            print(f"{tag:<10}{int(g['n']):>7}{int(g['spoken']):>7}{int(g['en_n']):>7}{100 * g['en_n'] / max(1, g['spoken']):>6.1f}%"
                  f"{g['en_sec']:>8.0f}{100 * g['en_sec'] / max(1, g['sec']):>7.1f}%{int(g['retry']):>6}")
        print(f"{'ALL':<10}{int(tot['n']):>7}{int(tot['spoken']):>7}{int(tot['en_n']):>7}{100 * tot['en_n'] / max(1, tot['spoken']):>6.1f}%"
              f"{tot['en_sec']:>8.0f}{100 * tot['en_sec'] / max(1, tot['sec']):>7.1f}%{int(tot['retry']):>6}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--out")
    ap.add_argument("--force")
    ap.add_argument("--summary", nargs="+")
    ap.add_argument("wavs", nargs="*")
    a = ap.parse_args()
    if a.summary:
        summary(a.summary)
    else:
        run(a)
        sys.stdout.flush()
        os._exit(0)   # HailoRT 共用 VDevice 在結束時的釋放偶爾卡住 (11-17 實測)，量測已寫完就直接結束
