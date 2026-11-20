# -*- coding: utf-8 -*-
"""部署版本：git archive 時自動填入 (.gitattributes export-subst)；直接從工作目錄跑時是 dev。Issue 回報與 /health 用。"""

COMMIT = "$Format:%h$"
COMMIT_DATE = "$Format:%ci$"


def version() -> str:
    if COMMIT.startswith("$"):
        return "dev"
    return f"{COMMIT} ({COMMIT_DATE})"
