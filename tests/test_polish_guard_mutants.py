"""transcript_polish 改字守門的突變測試補強（2026-11-23 localnote@mac，S19）。
S19 對 main 的 accept_homophone_edits／edit_opcodes／_touches／_rewrite_length_ok／revert_byte_slips 做 158 個突變，
原本的 tests/test_transcript_polish.py 殺掉 121 個、存活 37 個；這裡每一類存活的突變補一個能殺死它的測試。
"""
import collections
import glob
import json
import os
import random

import pytest

import transcript_polish as tp

ROOT = os.path.join(os.path.dirname(__file__), "..")


# ------------------------------------------------------------------ _touches（說話人標籤）邊界：存活 8 個
@pytest.mark.parametrize("i1,i2,want", [
    (0, 2, True), (3, 6, True), (4, 5, True),        # 修改和標籤 [0, 5) 重疊
    (5, 7, False), (6, 8, False),                    # 緊接在標籤後面、或更後面
    (1, 1, True), (4, 4, True),                      # 插入點在標籤內部
    (0, 0, False), (5, 5, False),                    # 插入點在標籤前面或剛好在結尾 (標籤後面接字)
])
def test_touches_label_boundaries(i1, i2, want):
    assert tp._touches(i1, i2, [(0, 5)]) is want


def test_label_edits_are_rejected():
    src = "說話人1：在運動\n說話人2：好"
    out, st = tp.accept_homophone_edits(src, "說話人2：在運動\n說話人2：好")
    assert out == src and st["rejected"] >= 1


# ------------------------------------------------------------------ edit_opcodes 合併（同音字連續替換）：存活 19 個
def _homophone_cases(n=300, seed=19):
    """e2e 測資的句子，隨機把 2–4 個字換成同音的別字 → (錯字稿, 正確稿)。"""
    from pypinyin import Style, lazy_pinyin
    lines = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tools", "e2e", "fixtures", "meeting_*min.json"))):
        with open(f, encoding="utf-8") as fh:
            lines += [t for _, t in json.load(fh)["lines"]]
    py = lambda c: lazy_pinyin(c, style=Style.NORMAL)[0]
    by = collections.defaultdict(list)
    for c in sorted({c for l in lines for c in l if "一" <= c <= "鿿"}):
        by[py(c)].append(c)
    rng, out = random.Random(seed), []
    for line in rng.sample(lines, min(len(lines), 4 * n)):
        idx = [i for i, c in enumerate(line) if len(by.get(py(c), [])) > 1]
        if len(idx) < 2:
            continue
        err = list(line)
        for i in rng.sample(idx, min(len(idx), rng.randint(2, 4))):
            err[i] = rng.choice([x for x in by[py(line[i])] if x != line[i]])
        out.append(("".join(err), line))
        if len(out) >= n:
            break
    return out


def test_homophone_runs_from_e2e_fixtures_fully_accepted():
    """每一處都是等長的同音替換：校對稿要整句收下（合併算錯時會有幾處對成「替換＋刪除」而不收）。"""
    cases = _homophone_cases()
    assert len(cases) >= 200
    bad = [(e, c, tp.accept_homophone_edits(e, c)[0]) for e, c in cases if tp.accept_homophone_edits(e, c)[0] != c]
    assert not bad, bad[:3]


def test_docstring_example_merges():
    assert tp.accept_homophone_edits("清理協禮", "請李協理")[0] == "請李協理"
    ops = [op for op in tp.edit_opcodes("清理協禮", "請李協理") if op[0] != "equal"]
    assert all(i2 - i1 == j2 - j1 for _t, i1, i2, j1, j2 in ops)


def test_gap_of_two_equal_chars_or_whitespace_not_merged():
    for src, dst in (("清理的協禮", "請李的協理"), ("清理 協禮", "請李 協理"), ("清理\n協禮", "請李\n協理")):
        ops = tp.edit_opcodes(src, dst)
        assert "".join(dst[j1:j2] for t, i1, i2, j1, j2 in ops if t != "delete") == dst
        assert tp.accept_homophone_edits(src, dst)[0] == dst


# ------------------------------------------------------------------ accept_homophone_edits：存活 5 個
def test_whitespace_only_difference_keeps_original_and_is_not_counted():
    out, st = tp.accept_homophone_edits("好的 我們開始", "好的我們開始")
    assert out == "好的 我們開始" and st == {"accepted": 0, "rejected": 0}


def test_cjk_digit_not_replaced_by_non_cjk_lookalike():
    out, _ = tp.accept_homophone_edits("零件", "〇件")     # 「〇」不是 CJK 統一漢字區：不收
    assert out == "零件"


@pytest.mark.parametrize("src,dst,want", [
    ("畢竟是老師", "畢竟還是老師", "畢竟還是老師"),           # 行中間補 1 字：收
    ("竟還是老師", "畢竟還是老師", "竟還是老師"),             # 行首補字：不收
    ("畢竟還是老", "畢竟還是老師", "畢竟還是老"),             # 行尾補字：不收
    ("在運\n動激", "在運動\n動激", "在運\n動激"),             # 下一行開頭前（行尾）補字：不收
    ("我在說", "我在說了", "我在說"),
    ("我說了", "我在說了", "我在說了"),                       # 第 2 個字的位置（i1=1）也是行中間
])
def test_insert_position_rules(src, dst, want):
    assert tp.accept_homophone_edits(src, dst)[0] == want


# ------------------------------------------------------------------ _rewrite_length_ok 邊界：存活 5 個
@pytest.mark.parametrize("n_src,n_out,ok", [
    (100, 50, True), (100, 49, False),               # 下限 0.5 倍（含）
    (100, 170, True), (100, 171, False),             # 上限 1.5 倍 + 20（含）
    (10, 35, True), (10, 36, False),
])
def test_rewrite_length_bounds(n_src, n_out, ok):
    assert tp._rewrite_length_ok("字" * n_src, "字" * n_out) is ok


# ------------------------------------------------------------------ autojunk 關掉（edit_opcodes、revert_byte_slips）：存活 2 個
def _long_text(n=600):
    base = "我們今天的會議有幾個議題要討論，第一個是預算，第二個是人力，第三個是時程。"
    return (base * (n // len(base) + 1))[:n]


def test_long_text_homophone_still_accepted():
    """200 字以上時 difflib 的 autojunk 會把常用字當雜訊，對齊就錯了；要關掉。"""
    src = _long_text()
    k = src.index("時程", 400)
    err = src[:k] + "實程" + src[k + 2:]
    assert tp.accept_homophone_edits(err, src)[0] == src


def test_long_text_byte_slip_reverted():
    src = _long_text() + "外殼"
    out, n = tp.revert_byte_slips(src, src[:-1] + "殠")
    assert out == src and n == 1


# ------------------------------------------------------------------ 突變導向的差異搜尋找到的輸入（S19）
def test_homophone_fix_right_after_label_accepted():
    """_touches：緊接在標籤後面的修改不算碰到標籤（136 行 a < i2 的邊界）。"""
    assert tp.accept_homophone_edits("說話人1：地", "說話人1：第", tp.protected_spans("說話人1：地"))[0] == "說話人1：第"
    assert tp._touches(8, 10, [(10, 15)]) is False


def test_e2e_sentence_with_deletes_and_punct():
    """e2e 測資的一句：同音（覆→複）收、刪字與句尾標點不收（突變版在這裡丟 IndexError）。"""
    src = "已了的經加裝六支警示燈，是並在十二月八日前完成全員覆訓"
    dst = "已經加裝六支警示燈，並在十二月八日前完成全員複訓。"
    assert tp.accept_homophone_edits(src, dst)[0] == "已了的經加裝六支警示燈，是並在十二月八日前完成全員複訓"


@pytest.mark.parametrize("src,dst,want", [
    ("下週再安排三", "下週會再安排", "下週會再安排三"),          # 行中間補「會」收、刪「三」不收
    ("林主任負責通知所有使用者。\n文請許經理負責，週二前交初的稿。",
     "林主任負責通知所有使用者。\n文宣請許經理負責，週二前交初稿。",
     "林主任負責通知所有使用者。\n文宣請許經理負責，週二前交初的稿。"),   # 第二行的行中間補字
])
def test_insert_kept_delete_rejected(src, dst, want):
    assert tp.accept_homophone_edits(src, dst)[0] == want

