"""完整逐字稿翻譯 (transcript_translate)：切單位、保留說話人、已是目標語言照抄、對不上的單位重翻、錄音開始時停下。"""
import asyncio
import re
import sys
import types

import pytest

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import transcript_translate as tt  # noqa: E402

REFINE = ("說話人1：好，我們開始今天的週會。第一個議題是教育訓練。\n"
          "說話人2：Okay, the training course is on September 2nd.\n"
          "說話人1：目前已經報名22人，還剩8個名額。")


UNITS = [u for _s, us in tt.parse_lines(REFINE) for u in us]   # 英文假翻譯用單位編號「EN<k>」(不能含中文字，否則算沒翻完)


def _fake(responses=None, drop=(), stop_after=None):
    """假的模型：把每行「N| 原文」翻成「N| EN<單位編號>」(翻中文則「中(原文)」)；drop 裡的原文故意不輸出 (測重翻)；stop_after 段後回 None (錄音開始)。"""
    calls = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        calls.append((prompt, hailo_only, cpu_first))
        if stop_after is not None and len(calls) > stop_after:
            return None
        await asyncio.sleep(0.001)
        out = []
        for m in re.finditer(r"^(\d+)\| (.*)$", prompt, re.M):
            if m.group(2) in drop and "\n" in prompt.split("\n", 1)[1]:   # 只在多行請求裡漏掉，單獨重翻時給
                continue
            src = m.group(2)
            digits = "".join(f" {d}" for d in re.findall(r"\d+", src))      # 真的翻譯會保留數字 (數值檢查)
            out.append(f"{m.group(1)}| EN<{UNITS.index(src)}>{digits}" if target == "en" else f"{m.group(1)}| 中({src})")
        return "\n".join(out)
    return complete, calls


def test_parse_lines_keeps_speakers_and_splits_sentences():
    rows = tt.parse_lines(REFINE)
    assert [s for s, _ in rows] == ["1", "2", "1"]
    assert rows[0][1] == ["好，我們開始今天的週會。", "第一個議題是教育訓練。"]
    assert tt.parse_lines("一段沒有標點" + "很長的逐字稿，" * 40)[0][1][0].endswith("，")   # 超過 UNIT_CHARS 在逗號切
    assert all(len(u) <= tt.UNIT_CHARS for u in tt.parse_lines("字" * 500)[0][1])


def test_target_language_units_are_copied_not_sent(monkeypatch):
    fake, calls = _fake()
    monkeypatch.setattr(tt, "_complete", fake)
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=False))
    lines = res["text"].splitlines()
    assert lines[0] == "Speaker 1: EN<0> EN<1>"
    assert lines[1] == "Speaker 2: Okay, the training course is on September 2nd."     # 英文句照抄
    assert lines[2] == "Speaker 1: EN<3> 22 8"
    assert res["kept_units"] == 1 and res["fallback_units"] == 0 and not res["stopped"]
    assert all("Okay, the training" not in p for p, _h, _c in calls)


def test_to_chinese_keeps_label_and_uses_taiwan_wording(monkeypatch):
    fake, _ = _fake()
    monkeypatch.setattr(tt, "_complete", fake)
    res = asyncio.run(tt.translate_transcript(REFINE, "zh", use_cpu=False))
    lines = res["text"].splitlines()
    assert lines[0] == "說話人1：好，我們開始今天的週會。第一個議題是教育訓練。"            # 已是中文照抄
    assert lines[1] == "說話人2：中(Okay, the training course is on September 2nd.)"


def test_missing_numbered_line_is_retranslated_alone(monkeypatch):
    fake, calls = _fake(drop=("第一個議題是教育訓練。",))
    monkeypatch.setattr(tt, "_complete", fake)
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=False))
    assert "EN<1>" in res["text"]
    assert any(p.count("\n") == 1 and "第一個議題" in p for p, _h, _c in calls)                # 單獨重翻那一句


def test_stops_between_chunks_when_recording_starts_and_keeps_rest(monkeypatch):
    fake, _ = _fake(stop_after=1)
    monkeypatch.setattr(tt, "_complete", fake)
    monkeypatch.setattr(tt, "CHUNK_CHARS", 20)                                                   # 每句一段
    progress = []
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=False,
                                              on_progress=lambda d, t, p: progress.append((d, t, p))))
    assert res["stopped"] and res["translated_chunks"] == 1
    assert "EN<0>" in res["text"] and "目前已經報名22人" in res["text"]                         # 沒翻到的保留原文
    assert progress[-1][0] == 1 and "第一個議題" not in progress[-1][2]                         # 逐段顯示只到連續翻好的前段


def test_two_workers_hailo_and_cpu_split_chunks_in_order(monkeypatch):
    fake, calls = _fake()
    monkeypatch.setattr(tt, "_complete", fake)
    monkeypatch.setattr(tt, "CHUNK_CHARS", 20)
    res = asyncio.run(tt.translate_transcript(REFINE, "en", use_cpu=True))
    assert {(h, c) for _p, h, c in calls} == {(True, False), (False, True)}                     # 兩路都有拿到段
    assert res["translated_chunks"] == res["chunks"] == 3
    t = res["text"]
    assert t.index("EN<0>") < t.index("EN<1>") < t.index("EN<3>")                                # 順序照原文


def test_english_output_with_chinese_left_is_retranslated(monkeypatch):
    # 11-19 GS3 30 分：246 行有 2 行翻成「Please have组长confirm…」；單獨重翻一次，重翻乾淨就用它
    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        if len(rows) > 1:
            return "\n".join(f"{n}| Ask 组长 to confirm" if "組長" in t else f"{n}| EN" for n, t in rows)
        return "1| Ask the team leader to confirm"
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt.translate_transcript("說話人1：好的。請組長跟對方確認。", "en", use_cpu=False))
    assert res["text"] == "Speaker 1: EN Ask the team leader to confirm"


def test_only_real_english_counts_as_english():
    # 11-19 德文會議按 Translate to English：只看「沒有中文字」時 134 句德文全被照抄
    assert tt.in_target_language("Okay, the training course is on September 2nd.", "en")
    assert not tt.in_target_language("So, ich lad die auf den Getränk ein.", "en")
    assert not tt.in_target_language("Kaffee mit Milch ohne Zucker wäre super!", "en")
    assert not tt.in_target_language("Le prix du pétrole est en baisse.", "en")
    assert not tt.in_target_language("好，我們開始今天的週會。", "en")
    assert tt.in_target_language("好，我們開始今天的週會。", "zh") and not tt.in_target_language("The budget is fine.", "zh")


def test_parse_output_tolerates_formats():
    got = tt.parse_output("1| Hello\n2. World\n 3：Third\nnoise\n4| ", 3)
    assert got == {1: "Hello", 2: "World", 3: "Third"}


def test_number_values_and_prepare_source():
    # 11-19 紀要自測：中翻英「200萬」→「200,000」；先換成阿拉伯數字再送模型，翻完比數值
    assert tt.prepare_source("預算200萬，一體40萬，1.5億", "en") == "預算2,000,000，一體400,000，150,000,000"
    assert tt.prepare_source("預算200萬", "zh") == "預算200萬"
    assert tt.numbers_ok("Budget: $800,000, hardware $500,000", "預算：80萬美元，硬體50萬美元")
    assert not tt.numbers_ok("Budget: $800,000", "預算八百萬美元")
    assert not tt.numbers_ok("11 billion profit", "獲利達十億") and tt.numbers_ok("11 billion profit", "獲利110億")
    assert tt.numbers_ok("9月2日 22人", "September 2, 22 people")          # 月份不比
    assert not tt.numbers_ok(tt.prepare_source("預算200萬", "en"), "Budget 200,000")


def test_wrong_number_is_retried_then_source_kept(monkeypatch):
    calls = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        calls.append(prompt)
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        return "\n".join(f"{n}| Budget 200,000" if "2,000,000" in t else f"{n}| ok {t}" for n, t in rows)
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt.translate_minutes("【Summary】\n• 預算200萬\n• 好的12人", "en"))
    lines = res["text"].splitlines()
    assert lines[1] == "• 預算200萬"                     # 兩次數值都錯：保留原文，不讓錯的數字出現
    assert lines[2] == "• 好的12人"                      # 「ok 好的12人」幾乎還是中文：保留原文
    assert res["number_fallback_units"] == 1 and res["fallback_units"] == 1
    assert any("2,000,000" in p for p in calls)          # 送模型的是換算好的阿拉伯數字


def test_minutes_translation_lines_headers_empty_items_and_foreign_lines(monkeypatch):
    seen = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        seen.extend(t for _n, t in rows)
        return "\n".join(f"{n}| Housing demand rose" for n, _t in rows)
    monkeypatch.setattr(tt, "_complete", complete)
    src = ("【Summary】\n• Government policies affect rental and sales prices\n• La demanda de vivienda sube\n\n"
           "【Decisions】\n• None")
    res = asyncio.run(tt.translate_minutes(src, "en"))
    assert res["text"].splitlines() == ["【Summary】", "• Government policies affect rental and sales prices",
                                        "• Housing demand rose", "", "【Decisions】", "• None"]
    assert seen == ["La demanda de vivienda sube"]       # 只有西文那行送模型；英文行照抄、「None」不送


def test_chinese_target_output_still_english_is_retranslated(monkeypatch):
    # 11-19 自測：en_short 翻中文有 3 行、德文那份 8 行模型原樣回英文，原本被當成翻好了
    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        if len(rows) > 1:
            return "\n".join(f"{n}| {t}" for n, t in rows)           # 多行請求：原樣回英文
        return "1| 9月2日舉辦簡報訓練"
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt.translate_minutes("【摘要】\n• Training presentation scheduled for September 2\n• Budget review", "zh"))
    assert res["text"].splitlines()[1] == "• 9月2日舉辦簡報訓練"
    assert tt.untranslated_left("Budget review", "zh") and not tt.untranslated_left("AfD", "zh")


def test_chinese_numerals_in_translation_are_normalized_when_numbers_mismatch():
    # 11-19 自測：模型寫「九月二日」「十輪」，數值比對失敗、整行保留英文
    assert tt.cn_numerals_to_digits("預定於九月二日舉行，十輪測試，二十二人，一千五百台，一起去") == "預定於9月2日舉行，10輪測試，22人，1500台，一起去"
    assert tt.fix_numerals("release on March 15 after 10 rounds", "於三月十五日發布，經過十輪", "zh") == "於3月15日發布，經過10輪"
    assert tt.fix_numerals("22 people", "二十二人，一起", "zh") == "22人，一起"
    assert tt.fix_numerals("no numbers here", "沒有數字，一起", "zh") == "沒有數字，一起"          # 本來就對得上不動
    assert tt.prepare_source("11 billion profit, 200 million target, $800,000", "zh") == "110億 profit, 2億 target, $800,000"


def test_english_number_words_in_translation_count():
    # 11-19 完整逐字稿自測：中翻英「至少要做1輪迴歸測試」→「at least one round…」被當成數字遺漏、整句保留中文
    assert tt.numbers_ok("至少要做1輪迴歸測試", "at least one round of regression tests")
    assert tt.numbers_ok("3位工程師", "three engineers") and not tt.numbers_ok("3位工程師", "two engineers")
    assert tt.numbers_ok("one of the issues", "其中一個問題")      # 原文的英文數字詞不要求譯文出現


def test_number_scales_in_other_languages_and_space_thousands():
    # 11-19 完整逐字稿自測：西文「6 millones」、法文「105 000 hectares」、重複的「un 74%」都被當成數值不符
    assert tt.number_values("casi 6 millones de personas") == [6000000.0]
    assert tt.number_values("105 000 hectards, 45 000") == [105000.0, 45000.0]
    assert tt.number_values("March 15th, 5 juta orang") == [15.0, 5000000.0]
    assert tt.numbers_ok("casi 6 millones de personas en 5 años", "almost 6 million people in 5 years")
    assert tt.numbers_ok("un 74% en 8 años, el alquiler un 40%, un 74% las ventas", "74% in 8 years, rent 40%, sales")
    assert tt.numbers_ok("105 000 hectards", "10.5萬公頃")


def test_cpu_model_tried_when_hailo_fails_twice(monkeypatch):
    # 11-19 v4：「Complete全员 training」Hailo 兩次都夾中文；可以用 CPU 時換 CPU 的模型再試一次
    calls = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        calls.append(cpu_first)
        n = re.findall(r"^(\d+)\| ", prompt, re.M)
        if cpu_first:
            return "1| Complete full staff retraining"
        return "\n".join(f"{k}| Complete全组 retraining" for k in n)
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt.translate_minutes("【Action Items】\n• 完成全員複訓", "en", use_cpu=True))
    assert res["text"].splitlines()[1] == "• Complete full staff retraining" and calls[-1] is True
    calls.clear()
    res = asyncio.run(tt.translate_minutes("【Action Items】\n• 完成全員複訓", "en", use_cpu=False))
    assert True not in calls and "Complete全组" in res["text"]     # 不能用 CPU 時不試


def test_percent_words_and_dot_thousands():
    # 11-19 full2：英→中「6% discount」譯成「百分之六的折扣」；西文「400.000 viviendas」(句點千分位) 譯成「400,000 homes」
    assert tt.fix_numerals("asked for a 6% discount", "要求給予百分之六的折扣", "zh") == "要求給予6%的折扣"
    assert tt.numbers_ok("se han construido 400.000 viviendas", "only 400,000 homes were built")
    assert tt.numbers_ok("pi is 3.141", "圓周率是3.141")


def test_first_chunk_is_smaller():
    units = [(i, "字" * 50) for i in range(12)]          # 每單位 50 字
    chunks = tt.group_chunks(units)
    assert sum(len(u) for _i, u in chunks[0]) <= tt.FIRST_CHUNK_CHARS < sum(len(u) for _i, u in chunks[1])
    assert [i for c in chunks for i, _u in c] == list(range(12))


def test_mostly_translated_rejects_chinese_rewrite():
    assert tt.mostly_translated("Complete全员 training before August 15", "en")
    assert not tt.mostly_translated("已经安装了8个警示灯，并在8月15日之前完成全员复训。", "en")
    assert tt.mostly_translated("anything", "zh")


def test_cpu_lane_retries_with_hailo(monkeypatch):
    # 11-19 exp_first：CPU 那路把中文改寫成簡體中文、單獨重翻仍是中文；第三次要換 Hailo 的模型
    calls = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        calls.append(cpu_first)
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        if cpu_first:
            return "\n".join(f"{k}| 第三个议题是预算" for k, _t in rows)
        await asyncio.sleep(0.05)                      # Hailo 較慢，讓 CPU 那路分到段落
        return "\n".join(f"{k}| The third topic is the budget" for k, _t in rows)
    monkeypatch.setattr(tt, "_complete", complete)
    text = "\n".join("說話人1：" + "第三個議題是預算，" * 30 + "。" for _ in range(4))
    res = asyncio.run(tt.translate_transcript(text, "en", use_cpu=True))
    assert True in calls and not re.search(r"[一-鿿]", res["text"].replace("說話人", ""))


def test_parse_output_literal_n_lines():
    assert tt.parse_output("N| Good, let's begin.\nN| How many topics?", 2) == {1: "Good, let's begin.", 2: "How many topics?"}
    assert tt.parse_output("N| only one line", 2) == {}
    assert tt.parse_output("1| a\nN| b", 2) == {1: "a"}


def test_english_minutes_lines_translates_only_foreign_bullets(monkeypatch):
    seen = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        seen.extend(t for _n, t in rows)
        return "\n".join(f"{n}| Oil prices are falling" for n, _t in rows)
    monkeypatch.setattr(tt, "_complete", complete)
    md = ("## 摘要\n- Transition to renewable energy is urgent\n- 7 people\n"
          "- **Pétrole et prix du pétrole** : le prix du pétrole est en baisse\n\n## 待辦\n| 事項 | 負責人 | 時間 |\n|---|---|---|\n| 無 | | |")
    out, n = asyncio.run(tt.english_minutes_lines(md))
    assert n == 1 and seen == ["**Pétrole et prix du pétrole** : le prix du pétrole est en baisse"]
    assert "- Oil prices are falling" in out and "- 7 people" in out and "| 事項 | 負責人 | 時間 |" in out
    seen.clear()
    assert asyncio.run(tt.english_minutes_lines("## 摘要\n- Budget is 800,000\n- 7 people")) == ("## 摘要\n- Budget is 800,000\n- 7 people", 0)
    assert seen == []


def test_zh_target_rejects_mostly_untranslated():
    assert tt.untranslated_left("前年45,000 l'an dernier, donc c'est bon l'ampleur est impressionnante", "zh")
    assert not tt.untranslated_left("David負責，8月15日前完成 AfD 的報告", "zh")
    assert not tt.untranslated_left("我認為它已經存在，這是Nino。HINO是一種長期被關注的現象", "zh")


def test_flat_counts_llm_calls_including_retries(monkeypatch):
    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        return "\n".join(f"{n}| 预算" if "預算" in t else f"{n}| Hello" for n, t in rows)   # 預算那句兩次都回中文
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt._translate_flat(["你好", "預算"], "en", None, lambda: False, use_cpu=False))
    assert res["llm_calls"] == 2 and res["done"] == {0: "Hello"}


def test_fix_titles_team_lead():
    assert tt.fix_titles("負責人是蔡組長。", "The person in charge is Captain Cai.", "en") == "The person in charge is Team Lead Cai."
    assert tt.fix_titles("隊長和組長都在", "Captain and team lead", "en") == "Captain and team lead"   # 原文真的有隊長
    assert tt.fix_titles("船長說", "Captain said", "en") == "Captain said"
    assert tt.fix_titles("負責人是蔡組長。", "The responsible person is Captain蔡.", "en") == "The responsible person is Team Lead蔡."
    assert tt.fix_titles("蔡組長", "Captains and Captaincy", "en") == "Captains and Captaincy"
    assert tt.fix_titles("蔡組長", "蔡組長", "zh") == "蔡組長"
    assert tt.postfix("負責人是蔡組長，預算八十萬", "Captain Cai, budget 800,000", "en") == "Team Lead Cai, budget 800,000"


def test_fix_mixed_tens():
    assert tt.fix_mixed_numbers("已經加裝十0只警示燈") == "已經加裝10只警示燈"
    assert tt.fix_mixed_numbers("至少要做十0輪迴歸測試") == "至少要做10輪迴歸測試"
    assert tt.fix_mixed_numbers("二十5人") == "25人"
    assert tt.fix_mixed_numbers("第十個議題、10月15日、三十") == "第十個議題、10月15日、三十"     # 正常寫法不動
    assert tt.numbers_ok(tt.prepare_source("已經加裝十0只警示燈", "en"), "10 warning lights have been installed")


def test_en_k_m_suffix_numbers():
    p = tt.prepare_source("預算抓8萬元，回來後在11月7日的週會上報告。", "en")
    assert tt.numbers_ok(p, "The budget is 80K yuan; report at the November 7 weekly meeting.")
    assert tt.numbers_ok(tt.prepare_source("預算200萬", "en"), "Budget 2M")
    assert 1000.0 not in tt.number_values("the 2km road and B2K", words=True)     # 小寫 m／k 接字母不算
    assert not tt.numbers_ok(p, "The budget is 8K yuan; report on November 7.")       # 數值錯仍要擋


def test_fix_mixed_numbers_digit_concat_and_hundreds():
    assert tt.fix_mixed_numbers("第1三個議題是教育訓練") == "第13個議題是教育訓練"
    assert tt.fix_mixed_numbers("第一7二個議題") == "第172個議題"
    assert tt.fix_mixed_numbers("第1八十四個議題") == "第184個議題"
    assert tt.fix_mixed_numbers("第一個、二十個、一百二十三、2025年、三十5人") == "第一個、二十個、一百二十三、2025年、35人"


def test_residual_chinese_picks_cleanest_usable(monkeypatch):
    # 11-21 W17：批次與單獨重翻都夾中文時，用夾最少的那個 (原本固定用批次那個)
    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        rows = re.findall(r"^(\d+)\| (.*)$", prompt, re.M)
        if len(rows) > 1:
            return "\n".join(f"{n}| There is an exhibition in New竹 with booth fee价格 today" for n, _t in rows)
        return "1| There is an exhibition in New竹 with a booth fee today"
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt._translate_flat(["新竹有一場展覽，攤位費報價。", "今天開會。"], "en", None, lambda: False, False))
    assert res["done"][0] == "There is an exhibition in New竹 with a booth fee today"


def test_romanize_titled_names():
    # 11-21 W17／W20：「Team Lead蔡」每場 1–3 次；只轉職稱後面、原文裡有的中文人名
    assert tt.postfix("負責人是蔡組長。", "The responsible person is Captain蔡.", "en") == "The responsible person is Team Lead Cai."
    assert tt.postfix("請焦文軒經理負責", "Please have Manager焦文軒 handle it", "en") == "Please have Manager Jiao Wenxuan handle it"
    assert tt.postfix("新竹展覽", "attend the new竹 exhibition", "en") == "attend the new竹 exhibition"   # 地名不轉
    assert tt.postfix("吳副理", "Ms.王 said", "en") == "Ms.王 said"                                   # 原文沒有的字不轉
    assert tt.postfix("蔡組長", "蔡組長", "zh") == "蔡組長"                                           # 翻中文不動
    assert tt.postfix("負責人是蔡組長。", "The responsible person is Team Lead蔡 (Cai). Next", "en") == "The responsible person is Team Lead Cai. Next"


def test_fix_weekdays_in_english_output():
    # 11-21 W20／W24：「on周二 last week」
    assert tt.postfix("上週二倉庫", "an accident at the warehouse on周二 last week", "en") == "an accident at the warehouse on Tuesday last week"
    assert tt.fix_weekdays("Reply by 週三.", "en") == "Reply by Wednesday."
    assert tt.fix_weekdays("星期天meeting", "en") == "Sunday meeting"
    assert tt.fix_weekdays("meet on Friday  ok", "en") == "meet on Friday  ok"        # 沒有中文星期不動
    assert tt.fix_weekdays("週三前回覆", "zh") == "週三前回覆"                          # 翻中文不動


def test_wan_composite_numbers():
    # 11-22 full8 日文翻英：「5萬3135円」被換成「50,0003135」，數值對不上保留原文
    assert tt.prepare_source("全國平均家賃は5萬3135円。", "en") == "全國平均家賃は53135円。"
    assert tt.prepare_source("預算1萬5000元", "en") == "預算15000元"
    assert tt.prepare_source("預算80萬元，3萬人", "en") == "預算800,000元，30,000人"   # 單純「N萬」照舊
    assert tt.numbers_ok(tt.prepare_source("家賃は5萬3135円。", "en"), "The rent is 53,135 yen.")


def test_mixed_numbers_need_classifier():
    # 日文「第3四半期」(第 3 季) 不是 34；後面接量詞／單位的才換
    assert tt.fix_mixed_numbers("第3四半期の売上") == "第3四半期の売上"
    assert tt.fix_mixed_numbers("第1三個議題、加裝十0只、在9月2五日") == "第13個議題、加裝10只、在9月25日"


def test_fix_name_zh_titles():
    # 11-22：「Wang经理」「Lin主任」「Cai组长」→ 職稱英文放姓名前
    assert tt.postfix("由向經理處理", "Agree that this matter shall be handled by Xiang经理 by Thursday.", "en") == \
        "Agree that this matter shall be handled by Manager Xiang by Thursday."
    assert tt.fix_name_zh_titles("請林主任和蔡組長", "Ask Lin主任 and Cai组长", "en") == "Ask Director Lin and Team Lead Cai"
    assert tt.fix_name_zh_titles("王經理", "the经理 said", "en") == "the经理 said"          # 前面不是姓名不動
    assert tt.fix_name_zh_titles("王經理", "王經理", "zh") == "王經理"
    assert tt.fix_name_zh_titles("請組長確認", "Ask 组长 to confirm", "en") == "Ask 组长 to confirm"   # 中間有空白不是「姓名＋職稱」


def test_fix_common_zh_words():
    # 11-22：英文譯文留下的「报价」「全员」「出差」「培训」
    assert tt.fix_common_zh_words("Complete全员培训 by the end", "en") == "Complete all staff training by the end"
    assert tt.fix_common_zh_words("arrangement for出差. Mr. Xu", "en") == "arrangement for business trip. Mr. Xu"
    assert tt.fix_common_zh_words("at the current报价 until", "en") == "at the current quotation until"
    assert tt.fix_common_zh_words("全員培訓", "zh") == "全員培訓"


def test_fix_cjk_name_titles():
    # 11-22 重放：「arranged by the蔡组长」4 處 → 「Team Lead Cai」；原文沒有那個姓不轉
    assert tt.postfix("測試由蔡組長安排", "The testing part will be arranged by the蔡组长, at least ten rounds.", "en") == \
        "The testing part will be arranged by the Team Lead Cai, at least ten rounds."
    assert tt.fix_cjk_name_titles("由王經理處理", "ask 蔡组长 now", "en") == "ask 蔡组长 now"
    assert tt.fix_cjk_name_titles("蔡組長", "蔡组长", "zh") == "蔡组长"


def test_ordinal_and_fraction_words_count_in_translation():
    # 11-22 full10 日文翻英：「手取りの3分の1以上」→「more than one-third of take-home pay」被當成 3 對不上
    p = tt.prepare_source("手取りの3分の1以上が家賃。", "en")
    assert tt.numbers_ok(p, "More than one-third of take-home pay goes to rent.")
    assert tt.numbers_ok("第3個議題", "The third topic")
    assert not tt.numbers_ok("第3個議題", "The fifth topic")


def test_fix_name_zh_titles_needs_matching_surname():
    # 「Project经理」(專案經理) 不是人名：原文沒有拼音是 project 的姓 → 不換
    assert tt.fix_name_zh_titles("請專案經理確認", "Ask the Project经理 to confirm", "en") == "Ask the Project经理 to confirm"
    assert tt.fix_name_zh_titles("請王經理調貨", "please request Wang经理 to dispatch", "en") == "please request Manager Wang to dispatch"
    # 模型把姓翻錯（原文許經理、譯文 Xiang经理）：原文只有一位經理 → 用原文的姓
    assert tt.fix_name_zh_titles("同意這件事由許經理負責", "handled by Xiang经理", "en") == "handled by Manager Xu"
    # 原文兩位經理、譯文的名字都對不上 → 不猜
    assert tt.fix_name_zh_titles("許經理和王經理", "handled by Xiang经理", "en") == "handled by Xiang经理"


def test_postfix_all_rules_together():
    # 週末加的英文譯文修正同時出現在一句裡：互不干擾
    src = "蔡組長請王經理週二前確認新報價，全員培訓第十0輪。"
    out = "Captain蔡 asked Wang经理 to confirm the new报价 by周二, and全员培训 round 10."
    assert tt.postfix(src, out, "en") == \
        "Team Lead Cai asked Manager Wang to confirm the new quotation by Tuesday, and all staff training round 10."


def test_courtesy_titles():
    # 「李先生」→「Mr. Li」（重放剩下的夾中文之一）
    assert tt.postfix("李先生下個月去曼谷", "Next month 李先生 will visit Bangkok.", "en") == "Next month Mr. Li will visit Bangkok."
    assert tt.postfix("請林小姐確認", "Ask Lin小姐 to confirm", "en") == "Ask Ms. Lin to confirm"


@pytest.mark.parametrize("src,want", [
    ("攤位費2萬5千元", "攤位費25000元"),        # 原本 20,005,000 (萬後接數字先吃掉 5 再乘千)
    ("預算3萬5", "預算35000"),                  # 口語「三萬五」；原本 30,005
    ("名額3百人", "名額300人"), ("2百5十人", "250人"), ("2百50人", "250人"), ("3百零5人", "305人"),
    ("庫存1千2百台", "庫存1200台"), ("1千200台", "1200台"), ("5千3百元", "5300元"), ("1千2", "1200"),
    ("3萬零5百", "30500"), ("3萬零5", "30005"), ("3萬5千2百", "35200"), ("12萬5千", "125000"),
    ("5百萬", "5000000"), ("3百5十萬元", "3500000元"), ("3千萬", "30000000"),
    ("1億2千萬", "120000000"), ("1億2千3百萬", "123000000"), ("2億5", "250000000"),
    # 原本就對的不變
    ("5萬3135円", "53135円"), ("1萬5000元", "15000元"), ("15萬", "150,000"), ("1.5萬", "15,000"), ("2千", "2,000"),
    ("第1三個", "第13個"), ("加裝十0只", "加裝10只"), ("第3季", "第3季"), ("300台", "300台"), ("12,500", "12,500"),
    # 看不懂的原樣 (之後數值對不上會保留原文，不會送錯的數字)
    ("15百台", "15百台"), ("5百5百", "5百5百"),
])
def test_prepare_source_composite_numbers(src, want):
    # N2（11-24）：即時稿 ITN 半套轉換的數字（阿拉伯數字＋萬千百）要換成正確的完整數字
    assert tt.prepare_source(src, "en") == want


def test_composite_numbers_pass_number_check():
    # 換對之後，正確的英文譯文通過數值檢查 (原本「3百人」→「300 people」被當成數值不符、保留原文)
    for src, tr in [("名額3百人", "300 people"), ("攤位費2萬5千元", "booth fee 25,000 yuan"), ("預算3萬5", "budget 35,000"),
                    ("庫存1千2百台", "1,200 units in stock"), ("5百萬", "5 million")]:
        assert tt.numbers_ok(tt.prepare_source(src, "en"), tr), src
    # 錯的數字仍擋下
    assert not tt.numbers_ok(tt.prepare_source("攤位費2萬5千元", "en"), "booth fee 20,005,000 yuan")


def test_wan_composite_not_followed_by_unit():
    # 「2萬3萬」原本變成 200,030,000；萬後接數字再接單位的交給 _CN_COMPOSITE_RE
    assert "200,030,000" not in tt.prepare_source("2萬3萬", "en")


def test_retry_prompt_asks_to_keep_numbers(monkeypatch):
    """11-24 .228：批次翻漏數字後，用同一個提示重翻會得到一字不差的輸出；重翻改用「數字照原樣保留」的提示，批次提示不變。"""
    prompts = []

    async def complete(prompt, target, num_predict, *, hailo_only, cpu_first, should_stop):
        prompts.append(prompt)
        if len(prompts) == 1:
            return "1| I suggest keeping the trial order price at the new price."          # 批次：漏了 50
        return "1| I suggest signing a trial order for 50 units first."                    # 重翻：補回來
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt._translate_flat(["我建議先簽50臺的試單。"], "en", None, lambda: False, False))
    assert res["done"][0] == "I suggest signing a trial order for 50 units first."
    assert prompts[0].startswith("Translate into English:\n")
    assert prompts[1].startswith("Translate into English. Keep every number exactly as written:\n")
    assert tt.build_prompt([(0, "預算80萬")], "zh", retry=True).startswith("翻成繁體中文，數字照原樣保留：")


@pytest.mark.parametrize("run,want", [
    # N3 突變測試找到的邊界
    ("3百10萬", 3100000), ("3百零9萬", 3090000), ("1億5000萬", 150000000), ("9999萬1234", 99991234), ("3萬零50", 30050),
    ("3百5萬", None),                         # 3,050,000 還是 3,500,000 有歧義
    ("1萬5百萬", None), ("2萬3萬", None), ("2萬萬", None),   # 萬億要由大到小、萬前面要有東西
    ("10000萬5", None), ("3萬零10000", None), ("15百", None), ("5百5百", None), ("3萬1百萬", None),
    ("8十", 80), ("3百", 300), ("2百5", 250), ("1千2", 1200), ("2億5", 250000000),
])
def test_composite_value_edges(run, want):
    assert tt._composite_value(run) == want


@pytest.mark.parametrize("run", ["15萬", "2千", "3萬52", "1萬200"])
def test_composite_value_defers(run):
    assert tt._composite_value(run) is tt._DEFER       # 交給原本的規則


@pytest.mark.parametrize("src,want", [
    ("3百5萬", "3百5萬"), ("1萬5百萬", "1萬5百萬"), ("2萬3萬", "2萬3萬"),   # 看不懂整串原樣，不只換其中一段
    ("3萬52", "30052"), ("1萬200元", "10200元"),                            # 萬後接 2–3 位數照舊照數字加
    ("預算12,000萬", "預算120,000,000"), ("1,500萬元", "15,000,000元"),       # 千分位 (原本「12,0」「1,5,000,000」)
    ("2,000千", "2,000,000"), ("1,234.5萬", "12,345,000"),
    ("1.5萬3千", "1.5萬3千"), ("兩萬5千", "兩萬5千"),                       # 單位前後緊接數字／單位：看不懂，原樣
    ("３萬５千元", "35000元"), ("１５萬", "150,000"), ("３百人", "300人"),     # 全形數字
    ("-3萬", "-30,000"), ("減少2萬5千", "減少25000"),                        # 負號、負的說法
])
def test_prepare_source_composite_edges(src, want):
    assert tt.prepare_source(src, "en") == want


def test_prepare_zh_scale_boundary():
    # 英翻中：剛好 1 億用「億」，以下用「萬」
    assert tt.prepare_source("100 million", "zh") == "1億"
    assert tt.prepare_source("50 million", "zh") == "5000萬"
    assert tt.prepare_source("99.99 million", "zh") == "9999萬"


@pytest.mark.parametrize("src,want", [
    # 簡體 万／亿
    ("2万5千元", "25000元"), ("1亿2千万", "120000000"), ("5万3135", "53135"), ("3万52", "30052"), ("15万", "150,000"),
    ("3亿", "300,000,000"), ("3百5十万", "3500000"), ("2万3万", "2万3万"), ("1万5百万", "1万5百万"),
    # 數字和單位之間的空白可以 (單位和下一個數字之間有空白時可能是兩個數量，不合併)
    ("2 萬5 千", "25000"),
    # 前後緊接數字、小數點、千分位、單位的不換 (不從一個數字的中間開始換，也不換到一半)
    ("上萬人參加", "上萬人參加"), ("15.萬", "15.萬"), ("1千2.5", "1千2.5"), ("2萬5,000", "2萬5,000"), ("3萬52.5", "3萬52.5"),
    ("3萬52,000", "3萬52,000"), ("10百", "10百"),
    ("1,500.萬", "1,500.萬"), ("約.5萬", "約.5萬"), ("1,5萬", "1,5萬"), ("上萬52人", "上萬52人"), ("1.5萬52", "1.5萬52"),
    ("1,5萬52", "1,5萬52"), ("3百十人", "3百十人"),           # 「三百十」(310) 原本換成「300十」
    ("3萬零", "3萬零"), ("5百億", "50000000000"), ("5百亿", "50000000000"),
    ("3百百", "3百百"), ("3百千", "3百千"), ("0百", "0"),
] + [(f"{c}2萬5千", f"{c}2萬5千") for c in "百千萬万億亿"]        # 「十2萬5千」＝十二萬五千：和 N5 的混寫修正一起時會換成 125000，不放這裡
  + [(f"{c}15萬", f"{c}15萬") for c in "十百千萬万億亿"]
  + [(f"{c}3萬52", f"{c}3萬52") for c in "百千萬万億亿"]
  + [(f"3萬52{c}", f"3萬52{c}") for c in "十百千萬万億亿"])
def test_prepare_source_composite_boundaries(src, want):
    assert tt.prepare_source(src, "en") == want
