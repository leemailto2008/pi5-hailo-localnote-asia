"""紀要的英文待辦與結尾總結不能把數字的千分位／小數點當成子句分隔（2026-11-23 localnote@mac，S10 深度審查）。

_todo_parts_en／_recap_timeless_todo_en 用 re.split(r"[,;.]") 取第一個子句：
「Mary will order 3,500 units」→ 動作「order 3」、「buy 1.5 tons」→「buy 1」、「the 2.5 million」→「the 2」。
recap_notes 用「，,。…」切子句：「追加3,500萬元」拆成「追加3」與「500萬元」兩行。
另外 40／50 字的截斷改成不切斷數字（同 _cut_item）。
"""
import pytest

import summary_utils as su


@pytest.mark.parametrize("line,action", [
    ("Mary will order 3,500 units by Friday.", "order 3,500 units"),
    ("Kevin will buy 1.5 tons of steel by Nov 5.", "buy 1.5 tons of steel"),
    ("Mary will confirm the budget, then email Tom by Friday.", "confirm the budget"),   # 一般逗號照舊切
])
def test_todo_parts_en_keeps_numbers(line, action):
    parts = su._todo_parts_en(line)
    assert parts is not None and parts[0] == action


@pytest.mark.parametrize("line,action", [
    ("Mary will order 3,500 units of the new sensor.", "order 3,500 units of the new sensor"),
    ("John will prepare the 2.5 million budget plan.", "prepare the 2.5 million budget plan"),
])
def test_recap_timeless_todo_en_keeps_numbers(line, action):
    parts = su._recap_timeless_todo_en(line)
    assert parts is not None and parts[0] == action


def test_recap_notes_does_not_split_thousands():
    r = su.recap_notes("最後總結一下，預算方面，第三季追加3,500萬元的人事費用，下週三前送簽", max_len=50)
    assert "3,500萬元" in r and "- 500萬元" not in r


def test_recap_notes_long_clause_cut_keeps_number():
    r = su.recap_notes("最後總結一下，第三季設備採購預算經過財務部和採購部共同確認後確定新台幣總額共計1500萬元整", max_len=40)
    nums = [n for n in __import__("re").findall(r"\d[\d,.]*", r)]
    assert all(n == "1500" for n in nums), r


def test_long_english_action_cut_keeps_number():
    line = "Mary will reconcile the supplier invoices totaling 12,500 dollars by Friday."
    action = su._todo_parts_en(line)[0]
    assert len(action) <= 40
    assert "12,5" not in action or "12,500" in action
    assert not action.rstrip().endswith(("12", "12,", "12,5"))
