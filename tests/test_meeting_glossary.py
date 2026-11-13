"""會議詞彙存在盒子上 (meeting_glossary)：讀寫、套到逐字稿 (紀要前用)。"""
import meeting_glossary as mg


def test_read_write_and_apply(monkeypatch, tmp_path):
    monkeypatch.setattr(mg, "GLOSSARY_PATH", str(tmp_path / "state" / "glossary.txt"))
    assert mg.read_text() == "" and mg.terms() == []
    assert mg.apply_to_text("請任體組確認") == ("請任體組確認", 0)       # 沒有詞彙：原樣
    mg.write_text("韌體、劉課長\nERP")
    assert mg.read_text() == "韌體、劉課長\nERP"
    assert mg.terms() == ["韌體", "劉課長"]                              # 夾英文的詞不收
    text, n = mg.apply_to_text("請任體組確認，劉科長負責")
    assert text == "請韌體組確認，劉課長負責" and n == 2
    assert len(text) == len("請任體組確認，劉科長負責")                   # 字數不變：錄音中預先整理的位置照舊


def test_apply_by_segments_matches_whole_text(monkeypatch, tmp_path):
    """錄音中預先整理只套每一段 (切在標點)，接起來要跟錄音後整份套用一樣，否則紀要不能沿用預先整理的筆記。"""
    monkeypatch.setattr(mg, "GLOSSARY_PATH", str(tmp_path / "glossary.txt"))
    mg.write_text("韌體、宏遠科技、李協理")
    whole = "第一個議題是任體更新，請立協理確認。宏源科技希望提前，任體組回覆。"
    cut = whole.index("。") + 1
    parts = mg.apply_to_text(whole[:cut])[0] + mg.apply_to_text(whole[cut:])[0]
    assert parts == mg.apply_to_text(whole)[0]
    assert "韌體更新" in parts and "李協理" in parts and "宏遠科技" in parts
