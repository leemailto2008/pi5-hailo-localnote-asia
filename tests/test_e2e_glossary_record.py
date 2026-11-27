"""11-27：e2e 結果要記下跑的時候盒上的會議詞彙（會改逐字稿專名；重開機清掉後基準會變）。"""
import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "e2e"))
import e2e  # noqa: E402


def test_box_glossary(monkeypatch):
    monkeypatch.setattr(e2e, "api", lambda path, *a, **k: {"text": "台揚通訊", "terms": ["台揚通訊"]})
    assert e2e.box_glossary() == ["台揚通訊"]


def test_box_glossary_unreachable_or_old_app(monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.URLError("404")
    monkeypatch.setattr(e2e, "api", boom)
    assert e2e.box_glossary() is None
