"""tools/*.sh（Mac／Linux 用的 ssh／scp 包裝，2026-11-21）語法檢查，且必須是 LF 換行。沒有 bash 時跳過語法檢查。"""
import glob
import os
import shutil
import subprocess

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
SCRIPTS = sorted(glob.glob(os.path.join(TOOLS, "*.sh")))


def test_shell_tools_exist():
    names = {os.path.basename(p) for p in SCRIPTS}
    assert {"pi_common.sh", "pi_run.sh", "pi_push.sh", "pi_pull.sh", "pi_probe.sh", "net_probe.sh", "pull_feedback.sh"} <= names


@pytest.mark.parametrize("path", SCRIPTS, ids=os.path.basename)
def test_shell_tool_syntax_and_lf(path):
    with open(path, "rb") as f:
        assert b"\r" not in f.read(), "shell 腳本必須是 LF（.gitattributes *.sh eol=lf）"
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("沒有 bash")
    res = subprocess.run([bash, "-n", path], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr


def test_cmd_tools_use_configurable_key():
    for name in ("pi_run.cmd", "pi_push.cmd", "pi_pull.cmd", "pi_probe.cmd"):
        with open(os.path.join(TOOLS, name), encoding="ascii") as f:
            text = f.read()
        assert "PI5_SSH_KEY" in text and r"C:\Users\Andrew" not in text, name
