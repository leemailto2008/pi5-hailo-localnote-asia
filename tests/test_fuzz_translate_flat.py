"""P15（2026-11-27 localnote@mac）：整條翻譯流程 _translate_flat 的 hypothesis fuzz（假的 _complete，不叫真的模型）。
模型亂回（沒編號、編號錯、日文照抄、抄出提示詞、數字錯、空字串、重複迴圈）時：
- 採用的譯文一定通過檢查（數值都在、翻英文沒夾中文、翻中文不是日文、沒抄提示詞），否則那一段不給譯文、由呼叫端保留原文；
- 已經是目標語言的段落原樣照抄；不當掉。"""
import asyncio
import os
import re
import tempfile

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402

hypothesis.configuration.set_hypothesis_home_dir(os.path.join(tempfile.gettempdir(), "hyp_p15"))
import transcript_translate as tt  # noqa: E402

SLOW = os.environ.get("PI5_FUZZ_SLOW", "").strip() == "1"
CFG = settings(max_examples=1000 if SLOW else 30, deadline=None, derandomize=not SLOW, database=None,
               suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])

ZH_SRC = st.sampled_from(["預算三百萬元", "請吳副理在週五前完成", "第三個議題是庫存", "新竹廠 12 月 10 日交 1,200 台", "好的",
                          "蔡組長負責教育訓練", "成長百分之十", "Q1 目標 30%", "這種情況，這種情況，這種情況，這種情況"])
EN_SRC = st.sampled_from(["The budget is 3 million.", "Please finish by Friday.", "Q1 target 30%", "We ship 1,200 units on Dec 10.",
                          "OK", "2024年の全國平均家賃は 5萬3135円。", "なんで？すねなんでロシアに"])
REPLY = st.sampled_from(["{n}| {good}", "{n}| {bad_num}", "{n}| {zh_left}", "{n}| {ja}", "{n}| {leak}", "{good}", "",
                         "N| {good}", "{n}| " + "the plan, " * 6, "{n}| {good}\n{n}| {bad_num}", "99| {good}", "{n}|"])


def _fill(tpl, n, src, target):
    # 數值照原文的「完美」譯文：內容不重要，數值要對、語言要對（只留原文送模型那版的數字串）
    nums = " ".join(re.findall(r"\d[\d,.]*%?", tt.prepare_source(src, target)))
    good = (f"Translated text {nums}".strip()) if target == "en" else (f"翻譯好的內容 {nums}".strip())
    return tpl.format(n=n, good=good, bad_num=good.replace("3", "8").replace("1", "7"), zh_left="這是中文沒翻",
                      ja="なんで？すねなんでロシアに金油金置いてんの", leak="翻成繁體中文，數字照原樣保留：")


@CFG
@given(st.data(), st.sampled_from(["en", "zh"]))
def test_translate_flat_only_accepts_checked_units(monkeypatch, data, target):
    srcs = data.draw(st.lists(ZH_SRC if target == "en" else EN_SRC, min_size=1, max_size=5))

    async def fake(prompt, tgt, num_predict, **kw):
        body = [ln.split("| ", 1) for ln in prompt.splitlines()[1:] if "| " in ln]
        out = []
        for k, src in body:
            orig = next((s for s in srcs if tt.prepare_source(s, tgt) == src), src)
            out.append(_fill(data.draw(REPLY), k, orig, tgt))
        return "\n".join(out)
    monkeypatch.setattr(tt, "_complete", fake)
    res = asyncio.run(tt._translate_flat(srcs, target, None, lambda: False, use_cpu=True))
    for i, s in enumerate(srcs):
        t = res["done"].get(i)
        if t is None:
            continue                                      # 呼叫端保留原文
        if tt.in_target_language(s, target):
            assert t == s
            continue
        assert tt.numbers_ok(tt.prepare_source(s, target), t), (s, t)
        assert tt.mostly_translated(t, target), (s, t)
        assert not tt.prompt_leaked(t), (s, t)
        if target == "zh":
            assert not tt.japanese_left(t), (s, t)
