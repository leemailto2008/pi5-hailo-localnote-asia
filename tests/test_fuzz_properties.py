"""Property-based 測試（hypothesis；2026-11-23 localnote@mac，S18 fuzz）。

- 沒裝 hypothesis 時整個檔案 skip（requirements-dev.txt 目前沒有它；找到的 bug 另外寫成一般回歸測試，CI 一定會跑）。
- 預設快速模式：每個性質 max_examples ≤ 50、deadline 300 ms、derandomize（例子固定，結果可重現）、不寫 .hypothesis/。
- PI5_FUZZ_SLOW=1：每個性質 2,000 例、不設 deadline，用來重新找 bug（PC 記憶體緊時不要開）。
"""
import os
import re
import tempfile
from decimal import Decimal

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402
from hypothesis.configuration import set_hypothesis_home_dir  # noqa: E402

# hypothesis 就算 database=None 也會在目前目錄建 .hypothesis/（常數與 unicode 快取）：改放系統暫存目錄，repo 不留檔
set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "pi5_localnote_hypothesis"))

import refine_transcript as rt  # noqa: E402
import summary_utils as su  # noqa: E402
import transcript_polish as tp  # noqa: E402
import transcript_translate as tt  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=2000 if SLOW else 40, deadline=None if SLOW else 300, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])

_D = "零一二三四五六七八九"


def cn(n: int) -> str:
    """1–9999 的標準讀法（一千零五、兩百、十五、二十）。"""
    out, zero = "", False
    for unit, v in (("千", 1000), ("百", 100), ("十", 10), ("", 1)):
        d = n // v % 10
        if d:
            if zero:
                out, zero = out + "零", False
            out += ("" if unit == "十" and d == 1 and n < 20 else ("兩" if d == 2 and unit in ("千", "百") else _D[d])) + unit
        elif out:
            zero = True
    return out


# ------------------------------------------------------------------ 數字與金額
@CFG
@given(st.integers(1, 9999), st.sampled_from(["人", "台", "天", "次", "%"]))
def test_cn_numerals_standard_readings(n, unit):
    assert tt.cn_numerals_to_digits(cn(n) + unit) == f"{n}{unit}"


@CFG
@given(st.integers(0, 99999), st.integers(0, 4), st.sampled_from(["萬", "億", "千"]))
def test_prepare_en_keeps_exact_value(i, nd, unit):
    num = f"{i / 10 ** nd:.{nd}f}" if nd else str(i)
    want = Decimal(num) * {"萬": 10 ** 4, "億": 10 ** 8, "千": 10 ** 3}[unit]
    assert tt.number_values(tt.prepare_source(f"預算{num}{unit}元", "en")) == [float(want)]


@CFG
@given(st.integers(1, 99999), st.sampled_from(["million", "billion"]))
def test_prepare_zh_thousands_scaled_keeps_value(k, word):
    # 上限 99,999：6 位有效數字以上（「1,234,567 million」丟精度、「100,000 billion」→「1e+06億」）是 :g 的問題，
    # 已由 S13 的 b2d7e15（prepare_source 改用 Decimal）修掉；這個分支從 gitlab/main 開，還沒有那個修正
    src = f"a budget of {k:,} {word}"
    assert tt.number_values(tt.prepare_source(src, "zh")) == tt.number_values(src)


@CFG
@given(st.integers(1000, 10 ** 9), st.integers(1, 99))
def test_number_values_thousands_with_decimal(whole, frac):
    text = f"{whole:,}.{frac:02d} units"
    assert tt.number_values(text) == [float(f"{whole}.{frac:02d}")]


@CFG
@given(st.text(alphabet="0123456789萬億千.,一二三十百月日人元 million", max_size=40))
def test_numbers_ok_reflexive(s):
    assert tt.numbers_ok(s, s)


# ------------------------------------------------------------------ 日期與期限
@CFG
@given(st.integers(1, 12), st.integers(1, 9), st.sampled_from(["萬", "億", "千", "%", "噸", "個", "人", "元", " million"]))
def test_decimal_amount_is_never_a_due_date(a, b, unit):
    assert su._TIME_RE.search(f"追加{a}.{b}{unit}") is None


@CFG
@given(st.integers(1, 12), st.integers(1, 31), st.sampled_from(["/", "."]))
def test_month_day_due_is_found(m, d, sep):
    found = su._TIME_RE.search(f"吳副理{m}{sep}{d}前寄送")
    assert found and found.group(1) == f"{m}{sep}{d}"


# ------------------------------------------------------------------ 紀要後處理
_WORD = st.sampled_from(["吳副理", "預算追加200萬元", "替代料持續驗證", "韌體10月11日上線", "無", "A 項", "B 項"])
_BULLETS = st.lists(st.tuples(st.sampled_from(["- ", "- ", "* "]), _WORD).map("".join), max_size=6)


@CFG
@given(_BULLETS, _BULLETS)
def test_drop_duplicate_bullets_idempotent_and_clean(summary, decisions):
    md = f"## 摘要\n" + "\n".join(summary) + "\n## 決議\n" + "\n".join(decisions) + "\n## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n"
    out = su.drop_duplicate_bullets(md)
    assert su.drop_duplicate_bullets(out) == out


# ------------------------------------------------------------------ 潤稿
_TXT = st.text(alphabet="說話人1：好的預算吳副理週五前1500萬元，。\n 　abc", max_size=300)


@CFG
@given(_TXT, st.integers(5, 80))
def test_split_chunks_bounded_and_restorable(text, mx):
    chunks = tp.split_chunks(text, mx)
    assert all(len(c) <= mx for c in chunks)
    assert re.sub(r"\s", "", "".join(chunks)) == re.sub(r"\s", "", text)
    assert tp.restore_layout(text, "\n\n".join(chunks)) == text


@CFG
@given(st.text(alphabet="說話人1：吳副理無副理五付利物負理許經理\n", max_size=150))
def test_apply_glossary_keeps_length_labels_and_is_idempotent(text):
    terms = ["吳副理", "許經理"]
    out, _n = tp.apply_glossary(text, terms, tp.protected_spans(text))
    assert len(out) == len(text)
    assert all(out[a:b] == text[a:b] for a, b in tp.protected_spans(text))
    assert tp.apply_glossary(out, terms, tp.protected_spans(out))[0] == out


# ------------------------------------------------------------------ 高精度稿的 token
_TOK = st.lists(st.sampled_from(["好", "的", "，", "。", " we", "1", "5", "萬", ".", "?"]), max_size=30)


@CFG
@given(_TOK, st.lists(st.floats(0, 10), max_size=5), st.floats(0.5, 10))
def test_token_pieces_cover_all_tokens(tokens, cuts, length):
    times = [length * i / max(1, len(tokens)) for i in range(len(tokens))]
    idx = [(a, b) for _s, _e, a, b in rt.token_pieces(0.0, length, tokens, times, cuts)]
    assert idx[0][0] == 0 and idx[-1][1] == len(tokens)
    assert all(x[1] == y[0] for x, y in zip(idx, idx[1:]))


@CFG
@given(_TOK, st.lists(st.tuples(st.floats(0, 10), st.floats(0, 3)), min_size=1, max_size=6))
def test_assign_tokens_keeps_every_word(tokens, regs):
    regions = sorted((a, a + d) for a, d in regs)
    times = [i * 0.3 for i in range(len(tokens))]
    got = [t for toks, _ in rt.assign_tokens(regions, tokens, times) for t in toks]
    words = lambda xs: [t for t in xs if not rt._is_punct_token(t)]
    assert words(got) == words(tokens)
