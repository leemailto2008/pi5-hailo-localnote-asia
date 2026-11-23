"""csc_corrector 的模型那一層：建構（onnxruntime／tokenizers／opencc 換成假的模組）、_predict 的 softmax 與 offsets、
correct_line 的邊界情況、unavailable_reason。不需要 MacBERT 模型檔。correct()／apply_predictions 已在 test_transcript_polish。"""
import sys
import types

import numpy as np
import pytest

import csc_corrector as cc


class _Enc:
    def __init__(self, text):
        # 假的 BERT 分詞：[CLS] + 每個字一個 token + [SEP]；offsets 對應原字串位置
        self.ids = [101] + [1000 + ord(c) % 1000 for c in text] + [102]
        self.attention_mask = [1] * len(self.ids)
        self.type_ids = [0] * len(self.ids)
        self.offsets = [(0, 0)] + [(i, i + 1) for i in range(len(text))] + [(0, 0)]


@pytest.fixture
def fake_libs(monkeypatch, tmp_path):
    state = {"feeds": None, "threads": None, "logits": None}

    class SessionOptions:
        intra_op_num_threads = 0

    class Input:
        def __init__(self, name):
            self.name = name

    class InferenceSession:
        def __init__(self, path, so, providers):
            state["threads"], state["providers"] = so.intra_op_num_threads, providers

        def get_inputs(self):
            return [Input("input_ids"), Input("attention_mask")]       # 這個模型沒有 token_type_ids

        def run(self, _out, feeds):
            state["feeds"] = feeds
            return [state["logits"](feeds["input_ids"])]

    ort = types.ModuleType("onnxruntime")
    ort.SessionOptions, ort.InferenceSession = SessionOptions, InferenceSession

    class Tokenizer:
        @staticmethod
        def from_file(path):
            return Tokenizer()

        def encode(self, text):
            return _Enc(text)

        def get_vocab(self):
            return {"[CLS]": 101, "[SEP]": 102, "程": 7, "行": 8}

    tok = types.ModuleType("tokenizers")
    tok.Tokenizer = Tokenizer

    class OpenCC:
        def __init__(self, cfg):
            self.cfg = cfg

        def convert(self, s):
            return s

    occ = types.ModuleType("opencc")
    occ.OpenCC = OpenCC
    for name, mod in (("onnxruntime", ort), ("tokenizers", tok), ("opencc", occ)):
        monkeypatch.setitem(sys.modules, name, mod)
    (tmp_path / "model.onnx").write_bytes(b"x")
    (tmp_path / "tokenizer.json").write_text("{}")
    state["dir"] = str(tmp_path)
    return state


def test_init_requires_model_file(fake_libs, tmp_path):
    with pytest.raises(RuntimeError, match="缺少中文糾錯模型"):
        cc.CscCorrector(model_dir=str(tmp_path / "nope"))


def test_init_and_predict_softmax(fake_libs):
    c = cc.CscCorrector(model_dir=fake_libs["dir"], threads=2)
    assert fake_libs["threads"] == 2 and fake_libs["providers"] == ["CPUExecutionProvider"]
    assert c.label == cc.engine_label(2)

    def logits(ids):
        n = ids.shape[1]
        z = np.zeros((1, n, 10), np.float32)
        z[0, :, 8] = 2.0            # 預設每個位置猜「行」
        z[0, 2, 7] = 5.0            # 第 2 個字（原字串 index 1）猜「程」，機率最高
        return z
    fake_libs["logits"] = logits
    offsets, preds = c._predict("行成")
    assert set(fake_libs["feeds"]) == {"input_ids", "attention_mask"}      # 只送模型要的輸入
    assert fake_libs["feeds"]["input_ids"].dtype == np.int64
    assert offsets == [(0, 0), (0, 1), (1, 2), (0, 0)]
    assert [p[0] for p in preds] == ["行", "行", "程", "行"]
    expected = np.exp(5.0) / (np.exp(5.0) + np.exp(2.0) + 8 * np.exp(0.0))
    assert preds[2][1] == pytest.approx(expected, rel=1e-5)
    assert all(0.0 < p < 1.0 for _, p in preds)


def test_correct_line_end_to_end_with_fake_model(fake_libs):
    c = cc.CscCorrector(model_dir=fake_libs["dir"])

    def logits(ids):
        n = ids.shape[1]
        z = np.full((1, n, 10), -10.0, np.float32)
        for k in range(n):
            z[0, k, 8] = 0.0
        z[0, 2, 7] = 10.0           # 「成」→「程」
        return z
    fake_libs["logits"] = logits
    assert c.correct_line("行成") == "行程"


def test_correct_line_edge_cases(monkeypatch):
    c = object.__new__(cc.CscCorrector)

    class Grow:
        def convert(self, s):
            return s + "x"
    c._t2s = Grow()
    c._predict = lambda piece: pytest.fail("長度不同不該送模型")
    assert c.correct_line("   ") == "   "
    assert c.correct_line("行成") == "行成"                  # 簡繁轉換長度不同：原樣回傳


def test_correct_line_windows(monkeypatch):
    monkeypatch.setattr(cc, "WINDOW_CHARS", 3)
    c = object.__new__(cc.CscCorrector)

    class Same:
        def convert(self, s):
            return s
    c._t2s = c._s2t = Same()
    seen = []
    c._predict = lambda piece: seen.append(piece) or ([(i, i + 1) for i in range(len(piece))], [(ch, 0.9) for ch in piece])
    assert c.correct_line("一二三四五六七") == "一二三四五六七"
    assert seen == ["一二三", "四五六", "七"]


def test_unavailable_reason(monkeypatch, tmp_path):
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda m: object() if m in ("numpy", "onnxruntime", "tokenizers", "opencc") else real(m))
    assert "model.onnx" in cc.unavailable_reason(str(tmp_path))
    (tmp_path / "model.onnx").write_bytes(b"x")
    assert "tokenizer.json" in cc.unavailable_reason(str(tmp_path))
    (tmp_path / "tokenizer.json").write_text("{}")
    assert cc.unavailable_reason(str(tmp_path)) is None
    monkeypatch.setattr(importlib.util, "find_spec", lambda m: None if m == "onnxruntime" else object())
    assert cc.unavailable_reason(str(tmp_path)) == "缺少套件：onnxruntime"
