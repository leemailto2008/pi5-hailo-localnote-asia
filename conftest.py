"""repo 根目錄的 pytest 設定：pytest tests、pytest test_api_endpoints.py 等都會載入（rootdir＝repo 根目錄）。

測試跑完清掉 import 時在 repo 裡建立的空資料夾（沒有 /dev/shm 的 macOS／Windows），見 tests/_repo_side_effects.py。
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    "_repo_side_effects", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "_repo_side_effects.py"))
_rse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rse)

# 收集（import 被測模組）之前記下哪些資料夾原本就在；結束時只清這次新建、仍是空的
_PREEXISTING = _rse.snapshot()


def pytest_sessionfinish(session, exitstatus):
    _rse.remove_new_empty_dirs(_PREEXISTING)
