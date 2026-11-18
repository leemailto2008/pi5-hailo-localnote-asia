# -*- coding: utf-8 -*-
"""SenseVoice 不支援語言量測（2026-11-18，sv_lang_guard）：同一份切片的 SenseVoice 與 Hailo Whisper 輸出，模擬改用 Whisper 的片數。

1. 在 Pi 上跑 SenseVoice（CPU，服務閒置時；切片沿用 whisper_lang_survey.py 的結果檔，兩邊是同一片）：
       python3 tools/sv_lang_survey.py run --repo <部署目錄> --out sv.jsonl --wav-dir wav16k --wav-dir base res_whisper.jsonl [...]
2. 模擬（PC 或 Pi 都可）：
       python3 tools/sv_lang_survey.py sim sv.jsonl res_whisper.jsonl [...]
   每個 wav 當一場會議，照 sv_lang_guard 的規則：即時稿（ForeignLangGuard）與高精度稿（refine_whisper_choices）各換幾片。
"""
import argparse
import collections
import json
import os
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "code_dispatcher"))


def _rows(paths):
    rows = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                rows[(r["file"], r["i"])] = r
    return rows


def run(args):
    sys.path.insert(0, args.repo)
    sys.path.insert(0, os.path.join(args.repo, "code_dispatcher"))
    import numpy as np
    import sherpa_onnx
    import refine_transcript as rt
    from summary_utils import to_taiwan_traditional
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(model=rt.model_path("asr"), tokens=rt.model_path("tokens"),
                                                         num_threads=4, language="auto", use_itn=True)
    done = set()
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            done = {(d["file"], d["i"]) for d in map(json.loads, f)}
    cache = {}

    def load(name):
        if name not in cache:
            cache.clear()
            path = next((os.path.join(d, name) for d in args.wav_dir if os.path.exists(os.path.join(d, name))), None)
            if path is None:
                raise SystemExit(f"找不到 {name}（--wav-dir {args.wav_dir}）")
            with wave.open(path) as w:
                cache[name] = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        return cache[name]

    t0 = time.time()
    rows = _rows(args.res)
    with open(args.out, "a", encoding="utf-8") as fo:
        for key, r in rows.items():
            if key in done:
                continue
            x = load(r["file"])[int(r["t0"] * 16000):int(r["t1"] * 16000)]
            st = rec.create_stream()
            st.accept_waveform(16000, x)
            rec.decode_stream(st)
            res = st.result
            fo.write(json.dumps({"file": r["file"], "i": r["i"], "t0": r["t0"], "t1": r["t1"], "sv_lang": res.lang,
                                 "sv_emo": getattr(res, "emotion", ""), "sv_raw": res.text,
                                 "sv_text": to_taiwan_traditional(res.text.strip())}, ensure_ascii=False) + "\n")
    print(f"done {len(rows)} slices, {time.time() - t0:.0f} s", flush=True)


def sim(args):
    import sv_lang_guard as g
    sv = _rows([args.sv])
    wh = _rows(args.res)
    files = collections.defaultdict(list)
    for key in sv:
        if key in wh:
            files[key[0]].append(key[1])
    agg = collections.defaultdict(collections.Counter)
    for name, idx in files.items():
        tag = wh[(name, idx[0])].get("tag") or name.split("__", 1)[0]
        guard = g.ForeignLangGuard(clock=lambda: 0.0)
        live = []
        for i in sorted(idx):
            s, w = sv[(name, i)], wh[(name, i)]
            c = agg[tag]
            c["slices"] += 1
            rec = {"src": "sv", "lang": s["sv_lang"], "text": s["sv_raw"]}
            if guard.should_probe(s["sv_lang"]):
                c["probed"] += 1
                rec["wtext"] = w["text"]
                if guard.decide(s["sv_lang"], s["sv_raw"], w["text"]) == "whisper":
                    c["live_whisper"] += 1
            live.append(rec)
        agg[tag]["refine_whisper"] += len(g.refine_whisper_choices(
            [{"sv_lang": r["lang"], "sv_text": r["text"], "wtext": r.get("wtext")} for r in live]))
    cols = ("slices", "probed", "live_whisper", "refine_whisper")
    print(f"{'tag':<10}" + "".join(f"{c:>15}" for c in cols))
    for tag in sorted(agg):
        print(f"{tag:<10}" + "".join(f"{agg[tag][c]:>15}" for c in cols))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("--repo", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--wav-dir", action="append", required=True)
    a.add_argument("res", nargs="+")
    b = sub.add_parser("sim")
    b.add_argument("sv")
    b.add_argument("res", nargs="+")
    ns = ap.parse_args()
    if ns.cmd == "run":
        run(ns)
        sys.stdout.flush()
        os._exit(0)   # sherpa-onnx 結束時的釋放偶爾很慢，結果已寫完就直接結束
    sim(ns)
