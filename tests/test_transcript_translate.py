"""完整逐字稿翻譯 (transcript_translate)：切單位、保留說話人、已是目標語言照抄、對不上的單位重翻、錄音開始時停下。"""
import asyncio
import re
import sys
import types

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
    assert lines[2] == "• ok 好的12人" and res["number_fallback_units"] == 1
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
        return "\n".join(f"{k}| Complete全员 retraining" for k in n)
    monkeypatch.setattr(tt, "_complete", complete)
    res = asyncio.run(tt.translate_minutes("【Action Items】\n• 完成全員複訓", "en", use_cpu=True))
    assert res["text"].splitlines()[1] == "• Complete full staff retraining" and calls[-1] is True
    calls.clear()
    res = asyncio.run(tt.translate_minutes("【Action Items】\n• 完成全員複訓", "en", use_cpu=False))
    assert True not in calls and "Complete全员" in res["text"]     # 不能用 CPU 時不試
