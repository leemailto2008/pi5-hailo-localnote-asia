"""transcript_polish 的錯誤與邊界分支：引擎名稱錯、MacBERT 缺套件或載入失敗、快修的各種跳過／失敗、
沒有 glibc 時不 malloc_trim。csc_corrector 換成假的，不載入模型、不呼叫 LLM。"""
import asyncio

import pytest

import csc_corrector as cc
import transcript_polish as tp


def _run(coro):
    return asyncio.run(coro)


def test_split_chunks_rejects_non_positive():
    with pytest.raises(ValueError):
        tp.split_chunks("abc", max_chars=0)


def test_find_cut_prefers_punctuation_in_second_half():
    assert tp._find_cut("一二三四五，六七八九十", 10) == 6          # 「，」在後半段：切在它後面
    assert tp._find_cut("一，二三四五六七八九十", 10) == 10         # 標點太前面：硬切


def test_unknown_fix_engine():
    with pytest.raises(ValueError, match="unknown fix engine"):
        _run(tp.polish_transcript("行成4天", "fix", engine="gpt"))


def test_csc_engine_missing_packages(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise ImportError("No module named 'onnxruntime'")
    monkeypatch.setattr(cc, "CscCorrector", Boom)
    with pytest.raises(RuntimeError, match="中文糾錯引擎缺少套件"):
        _run(tp.polish_transcript("行成4天", "fix", engine="csc"))


def test_load_pre_csc_unavailable_or_failing(monkeypatch):
    monkeypatch.setattr(cc, "unavailable_reason", lambda: "缺少模型檔 model.onnx")
    assert _run(tp._load_pre_csc()) is None

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("bad model")
    monkeypatch.setattr(cc, "unavailable_reason", lambda: None)
    monkeypatch.setattr(cc, "CscCorrector", Boom)
    assert _run(tp._load_pre_csc()) is None


def test_quick_fix_skips(monkeypatch):
    monkeypatch.setattr(tp, "QUICK_FIX", False)
    assert _run(tp.quick_fix("x"))["status"] == "skipped"
    monkeypatch.setattr(tp, "QUICK_FIX", True)
    monkeypatch.setattr(cc, "unavailable_reason", lambda: "缺少套件：onnxruntime")
    assert _run(tp.quick_fix("x")) == {"status": "skipped", "reason": "缺少套件：onnxruntime"}
    monkeypatch.setattr(cc, "unavailable_reason", lambda: None)
    assert _run(tp.quick_fix("   "))["reason"] == "沒有逐字稿"


def test_quick_fix_error_and_layout_mismatch(monkeypatch):
    monkeypatch.setattr(tp, "QUICK_FIX", True)
    monkeypatch.setattr(cc, "unavailable_reason", lambda: None)

    async def boom(*a, **k):
        raise RuntimeError("")
    monkeypatch.setattr(tp, "polish_transcript", boom)
    assert _run(tp.quick_fix("行成")) == {"status": "error", "reason": "RuntimeError"}   # 空訊息時用類型名稱

    async def stopped(*a, **k):
        return {"stopped": True}
    monkeypatch.setattr(tp, "polish_transcript", stopped)
    assert _run(tp.quick_fix("行成")) == {"status": "stopped"}

    async def grew(*a, **k):
        return {"stopped": False, "polished": "行程多一字", "backend": "x", "accepted_edits": 1, "glossary_terms": 0}
    monkeypatch.setattr(tp, "polish_transcript", grew)
    assert _run(tp.quick_fix("行成"))["reason"] == "修正後字數不同，保留原稿"


def test_restore_layout():
    assert tp.restore_layout("說話人1：行成\n\n好", "說話人1：行程好") == "說話人1：行程\n\n好"
    assert tp.restore_layout("ab", "abc") is None


def test_release_freed_memory_without_glibc(monkeypatch, capsys):
    import ctypes

    def no_libc(name):
        raise OSError(f"{name}: cannot open shared object file")
    monkeypatch.setattr(ctypes, "CDLL", no_libc)
    tp.release_freed_memory("test")                    # macOS／Windows：只記 debug，不印、不拋
    assert "[mem]" not in capsys.readouterr().out


def test_release_freed_memory_with_fake_glibc(monkeypatch, capsys):
    import ctypes

    class Libc:
        def malloc_trim(self, n):
            return 1
    monkeypatch.setattr(ctypes, "CDLL", lambda name: Libc())
    monkeypatch.setattr(tp, "_vm_rss_mb", lambda: 512)
    tp.release_freed_memory("csc")
    assert "[mem] csc: malloc_trim(1) RSS 512 → 512 MB" in capsys.readouterr().out


def test_vm_rss_mb_without_proc(monkeypatch):
    import builtins
    real_open = builtins.open

    def fake_open(path, *a, **k):
        if path == "/proc/self/status":
            raise FileNotFoundError(path)
        return real_open(path, *a, **k)
    monkeypatch.setattr(builtins, "open", fake_open)
    assert tp._vm_rss_mb() is None
