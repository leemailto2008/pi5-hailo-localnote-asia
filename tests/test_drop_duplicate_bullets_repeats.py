"""summary_utils.drop_duplicate_bullets：同一條重複兩次以上也要拿乾淨（2026-11-23 localnote@mac，S18 fuzz 找到）。
原本 removed 記的是「行的文字」：第一次遇到就刪（刪的是第一條，不是 docstring 說的後面那條），之後同樣文字的行全部保留。
hypothesis 最小化：決議三條「- 吳副理」→ 第一次留 2 條、第二次才剩 1 條（不冪等）。
"""
import summary_utils as su

HEAD = "# 會議紀要\n\n## 摘要\n{s}\n## 決議\n{d}\n## 待辦\n| 事項 | 負責人 | 期限 |\n|---|---|---|\n"


def _md(summary, decisions):
    return HEAD.format(s="\n".join(summary), d="\n".join(decisions))


def test_three_identical_decisions_keep_one():
    out = su.drop_duplicate_bullets(_md([], ["- 吳副理", "- 吳副理", "- 吳副理"]))
    assert out == _md([], ["- 吳副理"])
    assert su.drop_duplicate_bullets(out) == out


def test_summary_item_repeated_twice_in_decisions():
    out = su.drop_duplicate_bullets(_md(["- 預算追加200萬元"], ["- 預算追加 200萬元。", "- 預算追加200萬元", "- 替代料持續驗證"]))
    assert out == _md(["- 預算追加200萬元"], ["- 替代料持續驗證"])


def test_keeps_first_drops_later():
    out = su.drop_duplicate_bullets(_md(["- A 項", "- B 項", "- A 項"], []))
    assert out == _md(["- A 項", "- B 項"], [])


def test_section_not_emptied():
    md = _md(["- 預算追加200萬元"], ["- 預算追加200萬元", "- 預算追加200萬元"])
    out = su.drop_duplicate_bullets(md)
    assert out == md                                   # 決議全是摘要的重複：該段保留（docstring）


def test_placeholder_never_dropped():
    md = _md(["- 無"], ["- 無", "- 無"])
    assert su.drop_duplicate_bullets(md) == md
