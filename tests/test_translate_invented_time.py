"""11-27：中翻英憑空編出鐘點（原文只有「晚上」）與年份（原文只有月日）。真實例子取自已存譯文。"""
import pytest

import transcript_translate as tt


@pytest.mark.parametrize("src,tr,want", [
    ("正式切換定在6月15日晚上，預計停機2小時。", "The formal switch is scheduled for 15th June at 22:00, with an expected downtime of 2 hours.",
     "The formal switch is scheduled for 15th June in the evening, with an expected downtime of 2 hours."),
    ("正式切換定在12月13日晚上，預計停機3小時。",
     "The formal switch is scheduled for 12:13 PM on December 13th at 12:13 PM, 3 hours.",
     "The formal switch is scheduled for the evening on December 13th in the evening, 3 hours."),
    ("3月21日，在新竹有一場展覽，攤位費45萬元。", "March 21, 2023, there was an exhibition in Hsinchu with a booth fee of 450,000 yuan.",
     "March 21, there was an exhibition in Hsinchu with a booth fee of 450,000 yuan."),
])
def test_invented_time_removed(src, tr, want):
    assert tt.drop_invented_time(src, tr, "en") == want


@pytest.mark.parametrize("src,tr", [
    ("會議定在晚上8點開始。", "The meeting starts at 20:00."),                       # 原文有鐘點
    ("晚上十點半截止。", "Closes at 22:30."),
    ("切換定在6月15日晚上20:00。", "Switch on 15th June at 20:00."),
    ("上午的會議改到下午。", "The meeting moved to the afternoon at 15:00."),       # 沒有「晚上」不動
    ("2023年3月21日的展覽。", "The exhibition on March 21, 2023."),                  # 原文有年份
    ("3月21日要出貨2025台。", "On March 21 we ship 2025 units."),                    # 原文有四位數
    ("3月21日交貨。", "Deliver on March 21, 2,000 units."),                           # 千分位不是年份
])
def test_real_times_kept(src, tr):
    assert tt.drop_invented_time(src, tr, "en") == tr


def test_zh_target_untouched_and_postfix_applies():
    assert tt.drop_invented_time("x 晚上", "at 22:00", "zh") == "at 22:00"
    assert "in the evening" in tt.postfix("切換定在6月15日晚上。", "Switch on 15th June at 22:00.", "en")


def test_invented_for_clock_removed():
    assert tt.drop_invented_time("正式切換定在12月17日晚上，預計停機3小時。",
                                 "The formal switch is scheduled for 12:00 PM on December 17, with a 3-hour downtime.", "en") == \
        "The formal switch is scheduled for the evening on December 17, with a 3-hour downtime."
    assert tt.drop_invented_time("晚上檢查，抓兩小時。", "Check in the evening, booked for 2:00 hours.", "en") == \
        "Check in the evening, booked for 2:00 hours."


@pytest.mark.parametrize("src,tr", [
    ("3月21日要出貨兩千零二十五台。", "On March 21, 2025 units will ship."),     # 國字寫的數量剛好像年份
    ("3月21日要出貨二〇二五台。", "On March 21, 2025 units will ship."),
    ("3月21日要出貨兩千零二十四箱。", "Ship on March 21, 2024 boxes."),
])
def test_year_like_quantity_from_cn_numerals_kept(src, tr):
    # P18 審查 01afbbd：原文的國字數量（兩千零二十五台）在 prepare_source 後還是國字，numbers_ok 看不到，
    # 「March 21, 2025」的 2025 被當成編出來的年份拿掉，數量整個不見、而且還通過檢查
    assert tt.drop_invented_time(src, tr, "en") == tr


def test_postfix_stable_when_dropping_year_creates_loop():
    # P30（慢速 fuzz，main 上失敗）：拿掉編出的年份後才變成連續重複（「and March 21」×4），postfix 要一次收好
    src, tr = "6月15日", "June 15 and March 21, 2023 and March 21, 2023 and March 21, 2023 and March 21 2023"
    out = tt.postfix(src, tr, "en")
    assert tt.postfix(src, out, "en") == out
