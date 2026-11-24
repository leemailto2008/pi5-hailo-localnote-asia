"""N10（2026-11-24 localnote@mac）：紀要後處理（summary_utils）的 hypothesis fuzz。
性質：不憑空生出數字／日期／金額；同一段做兩次結果一樣；去重不丟唯一內容；中英混寫、全形、ASR 亂碼不當掉。
- 快速模式：每個性質 40 例、deadline 500 ms、derandomize、不寫 .hypothesis/。PI5_FUZZ_SLOW=1：2,000 例、不設 deadline。
- 沒裝 hypothesis 時整檔 skip。
"""
import os
import re
import tempfile

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402
from hypothesis.configuration import set_hypothesis_home_dir  # noqa: E402

set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "pi5_localnote_hypothesis"))

import summary_utils as su  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=2000 if SLOW else 40, deadline=None if SLOW else 500, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large])

NAMES = ["吳副理", "許經理", "李協理", "蔡組長", "王經理", "Ms. Lin", "Peter"]
TOPICS = ["教育訓練", "工安", "韌體更新", "客戶訂單", "預算", "庫存", "展覽", "Budget", "Release"]
NUM = st.one_of(st.integers(1, 99).map(str), st.integers(100, 99999).map(lambda n: f"{n:,}"), st.integers(1, 99).map(lambda n: f"{n}.5"),
                st.integers(1, 12).flatmap(lambda m: st.integers(1, 28).map(lambda d: st.sampled_from([f"{m}月{d}日", f"{m}/{d}", f"{m}.{d}"]))).flatmap(lambda s: s),
                st.sampled_from(["三十人", "八月十五日", "１２月", "２０萬", "50%", "3-5人", "第3.5版", "Q3"]))
UNIT = st.sampled_from(["", "人", "台", "萬元", "元", "%", "支", "天", "前", "之前"])
# 表格格子裡不放 ASCII「|」（模型寫進格子會讓欄位錯開，那是輸入本身壞掉；「|」只放在 GARBAGE 的不當掉測試）
JUNK = st.text(alphabet="，。、！？…~～　 ①②・·─*#-:：()（）[]0123456789０１２３abcXYZ的了是嗯呃", max_size=8)


@st.composite
def phrase(draw):
    parts = [draw(st.sampled_from(TOPICS)), "：", draw(st.sampled_from(["", "預計", "目前", "決議", "請"])),
             draw(st.sampled_from(NAMES + [""])), draw(NUM), draw(UNIT), draw(st.sampled_from(["", "完成", "上線", "報名", "交付"])),
             draw(JUNK)]
    return "".join(parts)


@st.composite
def minutes(draw):
    summ = draw(st.lists(phrase(), min_size=0, max_size=6))
    dec = draw(st.lists(phrase(), min_size=0, max_size=4))
    rows = draw(st.lists(st.tuples(phrase(), st.sampled_from(NAMES + ["-", ""]), st.one_of(NUM, st.just("-"), st.just(""))),
                         min_size=0, max_size=4))
    filler = draw(st.sampled_from(["", "- 無", "- None", "- - None"]))
    dup = draw(st.booleans())
    if dup and summ:
        summ = summ + [summ[0]]
    md = "## 摘要\n" + "\n".join(f"- {s}" for s in summ) + (f"\n{filler}" if filler else "")
    md += "\n\n## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n" + "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    md += "\n\n## 決議\n" + "\n".join(f"- {d}" for d in dec)
    if draw(st.booleans()):
        md = md[:draw(st.integers(0, len(md)))]                       # num_predict 截斷
    return md


TRANSCRIPT = st.lists(phrase(), min_size=0, max_size=8).map(lambda ps: "。".join(ps))
_NUMS = re.compile(r"\d+")


def _nums(s):
    return set(_NUMS.findall(re.sub(r"[０-９]", lambda m: str(ord(m.group(0)) - 0xFF10), s or "")))


def _check_no_new_numbers(out, *sources):
    extra = _nums(out) - set().union(*(_nums(s) for s in sources))
    assert not extra, (extra, out)


def _check_stable(f, md, out):
    """待辦表對照逐字稿的步驟：模型寫了但沒講過的負責人／期限改成「-」，這一格不從事項欄補 (S19 規則：只補模型留空的)；
    再做一次時它已經是空的，會從事項欄、英文逐字稿補 (補上的若沒講過又改成「-」…)。所以只要求最多再 3 次就不再變
    (不會一直改下去、也不會來回跳)；其他步驟 (SINGLE) 要求做兩次一樣。設計上的取捨寫在 N10 報告「給 PC」。"""
    seq = [out]
    for _ in range(4):
        seq.append(f(seq[-1]))
    assert seq[-1] == seq[-2], (md, seq)


SINGLE = [su.tidy_dates, su.drop_placeholder_items, su.cut_glued_topic_numbers, su.drop_listed_todos_from_summary,
          su.drop_recap_echo_bullets, su.drop_duplicate_bullets, su.drop_meeting_meta_bullets, su.ensure_sections,
          su.clean_summary_markdown]


@CFG
@given(minutes(), st.sampled_from(SINGLE))
def test_single_md_steps_no_new_numbers_and_idempotent(md, fn):
    out = fn(md)
    _check_no_new_numbers(out, md)
    assert fn(out) == out, (fn.__name__, md, out)


WITH_TR = [su.ground_todo_table, su.drop_unspoken_years]


@CFG
@given(minutes(), TRANSCRIPT, st.sampled_from(WITH_TR))
def test_transcript_steps_no_new_numbers_and_idempotent(md, tr, fn):
    out = fn(md, tr)
    # 數字只能來自紀要或逐字稿 (英文待辦的期限會從逐字稿補，_fill_en_due_from_transcript；補的一定是逐字稿講過的)
    _check_no_new_numbers(out, md, tr)
    _check_stable(lambda m: fn(m, tr), md, out)


@CFG
@given(st.lists(phrase(), min_size=1, max_size=6, unique=True))
def test_dedup_keeps_unique_bullets(items):
    items = [re.sub(r"\s+", " ", i).strip(" -") for i in items]
    items = [i for i in items if i and su.drop_duplicate_bullets(f"## 摘要\n- {i}") == f"## 摘要\n- {i}"]
    md = "## 摘要\n" + "\n".join(f"- {i}" for i in items)
    out = su.drop_duplicate_bullets(md)
    norm = lambda s: re.sub(r"\W", "", s)
    if len({norm(i) for i in items}) == len(items):                   # 寫法真的不同的條目，一條都不能少
        for i in items:
            assert i in out, (i, out)


GARBAGE = st.text(alphabet="## -|：:，。0123456789０１２３一二三萬元月日前週五待辦摘要決議負責人期限\n abcXYZ的了是*~（）()", max_size=120)


@CFG
@given(GARBAGE, GARBAGE)
def test_garbage_never_crashes(md, tr):
    for fn in SINGLE:
        fn(md)
    for fn in WITH_TR:
        fn(md, tr)
    su.tidy_live_transcript(md)
    su.clean_live_segment(md)
    su.split_transcript(md, 50)
    su.transcript_todo_rows(tr)


FROM_TR = [su.fill_decisions_from_transcript, su.merge_recap_into_minutes, su.fill_missing_topics, su.merge_body_todos]


@st.composite
def recap_transcript(draw):
    # 帶結尾總結的逐字稿：「今天的結論是…決議…待辦事項是…」
    ps = draw(st.lists(phrase(), min_size=0, max_size=6))
    recap = draw(st.lists(st.tuples(st.sampled_from(["決議", "待辦事項是", "請", "今天的結論是"]), phrase()), max_size=4))
    return "。".join(ps) + "。" + "。".join(a + b for a, b in recap)


@CFG
@given(minutes(), recap_transcript(), st.sampled_from(FROM_TR))
def test_transcript_fillers_only_use_spoken_numbers(md, tr, fn):
    # 從逐字稿補決議／待辦／議題：數字只能來自紀要或逐字稿（不憑空生出），做兩次結果一樣
    out = fn(md, tr)
    _check_no_new_numbers(out, md, tr)
    _check_stable(lambda m: fn(m, tr), md, out)


@CFG
@given(recap_transcript())
def test_transcript_todo_rows_only_spoken_numbers(tr):
    for row in su.transcript_todo_rows(tr):
        _check_no_new_numbers(row, tr)


def _chain(md, tr):
    # 會議紀要後處理的主要步驟（順序參考 meeting_minutes，只讀）
    md = su.ensure_sections(su.clean_summary_markdown(md))
    md = su.ground_todo_table(md, tr)
    md = su.drop_unspoken_years(md, tr)
    for fn in (su.drop_placeholder_items, su.cut_glued_topic_numbers, su.drop_listed_todos_from_summary, su.drop_recap_echo_bullets,
               su.drop_duplicate_bullets, su.drop_meeting_meta_bullets):
        md = fn(md)
    return md


@CFG
@given(minutes(), recap_transcript())
def test_whole_chain_idempotent_and_no_new_numbers(md, tr):
    out = _chain(md, tr)
    _check_no_new_numbers(out, md, tr)
    _check_stable(lambda m: _chain(m, tr), md, out)


EN_PHRASE = st.builds(lambda a, b, c, d: f"{a}: {b} {c} by {d}", st.sampled_from(["Budget", "Release", "Training", "Orders"]),
                      st.sampled_from(["John", "Kevin", "Ms. Lin", "the team"]),
                      st.sampled_from(["will send 3,000 units", "approved $1.5 million", "ship v3.5", "hire 3-5 people", "cut 20%"]),
                      st.sampled_from(["Friday", "March 15", "3/15", "next week", "Q3", "2026-12-01"]))


@CFG
@given(st.lists(EN_PHRASE, max_size=5), st.lists(st.tuples(EN_PHRASE, st.sampled_from(["John", "-"]), st.sampled_from(["Friday", "-"])),
                                                   max_size=3), st.lists(EN_PHRASE, max_size=5))
def test_english_minutes(summ, rows, tr):
    # 英文紀要內部也用中文段名 (summary_utils.to_internal_sections)，輸出前才換成英文
    md = ("## 摘要\n" + "\n".join(f"- {s}" for s in summ) + "\n\n## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n"
          + "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows) + "\n\n## 決議\n- None")
    t = ". ".join(tr)
    out = _chain(md, t)
    _check_no_new_numbers(out, md, t)
    _check_stable(lambda m: _chain(m, t), md, out)
