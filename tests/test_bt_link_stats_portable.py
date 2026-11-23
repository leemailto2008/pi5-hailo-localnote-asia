"""bt_link_stats 在沒有 fcntl 的平台（Windows）也要能 import：讀不到計數時回傳 None，跟沒有藍牙一樣。

2026-11-23（localnote@mac）：原本模組層 import fcntl，Windows 上 import 就失敗，PC 跑 pytest 必須
--ignore tests/test_bt_link_stats.py（CLAUDE.md「Windows pytest」），voice_pipeline 的到達率統計也不能用。
用子行程把 fcntl 擋掉（sys.modules["fcntl"] = None 會讓 import 拋 ImportError）模擬 Windows。
"""
import os
import subprocess
import sys

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "code_dispatcher")

SNIPPET = """
import sys
sys.modules["fcntl"] = None          # 模擬 Windows：import fcntl → ImportError
sys.path.insert(0, {code_dir!r})
import bt_link_stats as b
assert b.fcntl is None
assert b.sco_rx_packets() is None
m = b.ArrivalMeter(reader=b.sco_rx_packets)
m.tick()
assert m.live_pct() is None and m.total_pct() is None   # 讀不到計數 → 不回報（網頁不顯示掉包）
print("ok")
"""


def test_import_without_fcntl():
    res = subprocess.run([sys.executable, "-c", SNIPPET.format(code_dir=CODE_DIR)],
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "ok"


def test_sco_rx_packets_without_fcntl_returns_none(monkeypatch):
    import bt_link_stats as b

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(b.socket, "socket", lambda *a: FakeSock())   # 假設 socket 建得起來（例如 WSL）
    monkeypatch.setattr(b, "fcntl", None)
    assert b.sco_rx_packets() is None
