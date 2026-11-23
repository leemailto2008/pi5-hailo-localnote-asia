"""quick_fix（MacBERT）路徑：等長換字遇到重複字時，字數不能變，整份快修不能被丟掉（W-verify-bac9cfd，localnote@mac）。
PC 的疑慮：MacBERT 只做等長換字，但 difflib 對齊重複字時，一次換字可能被拆成「insert＋equal＋delete」；
insert 1 個中文字會被收（補字規則不看同音）、delete 被拒 → 字數 +1 → restore_layout 判字數不同 → quick_fix 回
「修正後字數不同，保留原稿」，整份快修丟掉。實測：main 本來就有（重複字很密的字串），bac9cfd 之後變多，
e2e 句子做的 MacBERT 式換字 19,984 句裡 9 句（main 0 句）。修法：MacBERT 路徑（_run_fix_csc）逐字比對，不用 difflib。
"""
import asyncio
import sys
import types

import pytest

import transcript_polish as tp


def _quick_fix_with(monkeypatch, src, corrected):
    class FakeCorrector:
        label = "fake MacBERT"

        def __init__(self, **kw):
            pass

        def correct(self, text, should_stop=None):
            assert text == src.split("：", 1)[-1] or text == src or "說話人" in src
            return corrected if "說話人" not in src else src.split("：", 1)[0] + "：" + corrected.split("：", 1)[-1]

    mod = types.SimpleNamespace(CscCorrector=FakeCorrector, LABEL="fake", unavailable_reason=lambda *a: None)
    monkeypatch.setitem(sys.modules, "csc_corrector", mod)
    return asyncio.run(tp.quick_fix(src))


# (原文, 假 MacBERT 輸出, 預期的快修結果)
CASES = [
    ("好好的，我們開始", "號好的，我們開始", "號好的，我們開始"),          # 同音（hao）：收
    ("好好好的", "好號好的", "好號好的"),                                # 重複字中間換同音（hao）：收
    ("好的的會議", "好號的會議", "好的的會議"),                          # 不同音：不收，字數不變
    ("好好的好", "好的的好", "好好的好"),                                # main 原本就會 +1 字（delete＋insert）
    ("說話人1：好好好的", "說話人1：好號好的", "說話人1：好號好的"),      # 有標籤
    ("好的的會議", "好地的會議", "好的的會議"),                          # 「地」lazy_pinyin 讀 di：不算同音，不收
    ('請各部門在週五前把名單交給劉課長。', '請各部門在週五千前名單交給劉課長。', None),
    ('負責人是許經理。', '負題人許產經理。', None),
    ('楊工程師負責通知所有使用者。', '楊工程師確責通知有由使用者。', None),
    ('黃專員負責通知所有使用者。', '專轉員負責通知所有使用這。', None),
    ('希望在五月二十七日前完成報到。', '系在再五月二十七日前完成報到。', None),
    ('第十六個議題是出差安排。王經理下個月要去曼谷拜訪永豐光電，行程五天。', '第十六個議題是出差安排。王經理下個月要去曼拜百訪永豐光電，行程五天。', None),
    ('下週會再安排六場面試，由李協理主持。', '下週會再安排六場面試，李力協力主持。', None),
    ('第四百六十六個議題是供應商。永豐光電的天線模組交期延到二月十七日，比原本晚了十四天。', '第四樣六十六個議題是供應商。永豐光電的天線模組交期延到二月十七日，比原本萬晚十四天。', None),
    ('今天就到這裡，謝謝大家。', '今天就到這裡，謝接謝價。', None),
]


@pytest.mark.parametrize("src,corrected,want", CASES, ids=[f"c{i}" for i in range(len(CASES))])
def test_quick_fix_keeps_length_and_is_not_discarded(monkeypatch, src, corrected, want):
    res = _quick_fix_with(monkeypatch, src, corrected)
    assert res["status"] == "done", res                        # 不會走到「修正後字數不同，保留原稿」
    assert len(res["text"]) == len(src)
    if want is not None:
        assert res["text"] == want
    else:                                                      # e2e 句子：每個字要嘛是原字、要嘛是 MacBERT 給的字（不會插字）
        assert all(c in (a, b) for c, a, b in zip(res["text"], src, corrected))


def test_positional_accept_never_changes_length():
    import itertools
    alpha, sub = "好的在是", {"好": "號", "的": "地", "在": "再", "是": "事"}
    for n in range(3, 6):
        for s in itertools.product(alpha, repeat=n):
            s = "".join(s)
            for i in range(n):
                for new in (sub[s[i]], "號" if s[i] != "好" else "的"):
                    d = s[:i] + new + s[i + 1:]
                    out, _ = tp.accept_homophone_edits(s, d, positional=True)
                    assert len(out) == len(s), (s, d, out)
