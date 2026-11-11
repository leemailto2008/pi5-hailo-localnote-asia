# -*- coding: utf-8 -*-
"""
csc_corrector.py — 中文拼寫糾錯 (Chinese Spelling Correction) 引擎，給潤稿「修同音字與漏字」用（2026-11-12）。

模型：shibing624/macbert4csc-base-chinese 的 ONNX 版（onnxruntime CPU；檔案由 tools/ci/setup_csc_model.sh 下載到
PI5_CSC_MODEL_DIR，預設 /home/pi/models/macbert4csc）。模型以簡體訓練：每行先 OpenCC t2s，模型只做同長度的單字替換，
只取「模型改到、且機率 ≥ MIN_PROB」的位置，該字再以 s2twp 轉回台灣繁體；最後仍由 transcript_polish.accept_homophone_edits
只收同音字。

2026-11-11 量測（.cc_scratch/pe/csc_eval.py、csc_stack.py；高精度稿；CER）：
  實錄 5 分 0.1802 → 0.1781（4 s）；第二次錄 0.1731 → 0.1690；10 分 0.1905 → 0.1875（8 s）；新錄 10 分 0.1845 → 0.1835；
  新錄 30 分 0.2007 → 0.1987（24.7 s），事實召回都不變；RSS 約 814 MB。
  同資料 CPU qwen2.5:3b 的 LLM fix：0.1771、0.1670、0.1845、0.1825、0.1968，但要 220–1587 s。
  MIN_PROB 在實錄 5 分調（0～0.7 並列，取 0.7）；第二次錄在 0.7 擋掉「協理→協利」(0.68)、「認→任」(0.52)。
預設不用（transcript_polish.FIX_ENGINE 預設 llm）；PI5_POLISH_FIX_ENGINE=csc 才用。
"""

import os
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

MODEL_DIR = os.environ.get("PI5_CSC_MODEL_DIR", "/home/pi/models/macbert4csc")
MIN_PROB = 0.7
WINDOW_CHARS = 120        # 每次送模型的字數（遠低於 BERT 的 512 token 上限）
THREADS = 4
LABEL = "MacBERT4CSC（ONNX，CPU 4 執行緒）"

_CJK_RE = re.compile(r"^[一-鿿]$")


def apply_predictions(trad: str, start: int, piece: str, offsets: Sequence[Tuple[int, int]],
                      preds: Sequence[Tuple[str, float]], to_trad: Callable[[str], str],
                      out: List[str], min_prob: float = MIN_PROB) -> int:
    """把一個視窗的模型預測套到 out（trad 的字元串列）。piece 是 trad[start:...] 的簡體；offsets／preds 一個 token 一筆
    （preds 是 (預測字, 機率)）。只換「單一中文字 token、預測是另一個中文字、機率 ≥ min_prob、轉回繁體後仍是一個字且與原字不同」。
    回傳改了幾個字。"""
    changed = 0
    for (s, e), (new, prob) in zip(offsets, preds):
        if e - s != 1 or not _CJK_RE.match(piece[s]):
            continue
        if len(new) != 1 or not _CJK_RE.match(new) or new == piece[s] or prob < min_prob:
            continue
        t = to_trad(new)
        if len(t) == 1 and t != trad[start + s]:
            out[start + s] = t
            changed += 1
    return changed


class CscCorrector:
    """載入要約 4 s、RSS 約 814 MB：每次潤稿建立一個，用完就丟（不常駐在 API 行程裡）。"""

    def __init__(self, model_dir: str = MODEL_DIR, threads: int = THREADS) -> None:
        import numpy as np
        import onnxruntime as ort
        from opencc import OpenCC
        from tokenizers import Tokenizer

        model = os.path.join(model_dir, "model.onnx")
        if not os.path.isfile(model):
            raise RuntimeError(f"缺少中文糾錯模型 {model}（bash tools/ci/setup_csc_model.sh）")
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self._np = np
        self._sess = ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._sess.get_inputs()}
        self._tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self._inv = {v: k for k, v in self._tok.get_vocab().items()}
        self._t2s = OpenCC("t2s.json")
        self._s2t = OpenCC("s2twp.json")

    def _predict(self, piece: str) -> Tuple[List[Tuple[int, int]], List[Tuple[str, float]]]:
        np = self._np
        enc = self._tok.encode(piece)
        feeds: Dict[str, Any] = {
            "input_ids": np.array([enc.ids], dtype=np.int64),
            "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
            "token_type_ids": np.array([enc.type_ids], dtype=np.int64),
        }
        logits = self._sess.run(None, {k: v for k, v in feeds.items() if k in self._inputs})[0][0]
        z = np.exp(logits - logits.max(-1, keepdims=True))
        prob = z / z.sum(-1, keepdims=True)
        best = logits.argmax(-1)
        preds = [(self._inv.get(int(j), ""), float(prob[k, int(j)])) for k, j in enumerate(best)]
        return list(enc.offsets), preds

    def correct_line(self, trad: str) -> str:
        if not trad.strip():
            return trad
        simp = self._t2s.convert(trad)
        if len(simp) != len(trad):          # 簡繁轉換長度不同（極少見）就不動這一行，避免位置對錯
            return trad
        out = list(trad)
        for start in range(0, len(simp), WINDOW_CHARS):
            piece = simp[start:start + WINDOW_CHARS]
            offsets, preds = self._predict(piece)
            apply_predictions(trad, start, piece, offsets, preds, self._s2t.convert, out)
        return "".join(out)

    def correct(self, text: str, should_stop: Optional[Callable[[], bool]] = None) -> Optional[str]:
        """逐行糾錯；should_stop() 成立就回傳 None（錄音一開始就停，見 CLAUDE.md 重點一）。"""
        lines: List[str] = []
        for line in text.split("\n"):
            if should_stop is not None and should_stop():
                return None
            lines.append(self.correct_line(line))
        return "\n".join(lines)
