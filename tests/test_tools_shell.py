"""tools/*.sh（Mac／Linux 用的 ssh／scp 包裝，2026-11-21）語法檢查，且必須是 LF 換行。沒有 bash 時跳過語法檢查。

2026-11-23（localnote@mac）：加上離線行為測試。ssh／scp／ping／curl 等外部指令換成 PATH 最前面的 stub，
uname 由 FAKE_UNAME 決定，所以同一份測試在 macOS（BSD 工具、bash 3.2）和 Linux（GNU 工具）上都驗得到兩邊的分支；
date／find／wc／tr／mkdir 用系統真的指令（BSD 與 GNU 的差異就在這些）。不連網路、不碰 Pi。
Windows 上 shutil.which("bash") 可能是 WSL 的 bash，路徑對不上，行為測試在 Windows 跳過（語法檢查照跑）。
"""
import glob
import os
import shutil
import stat
import subprocess
import sys
import zipfile

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
SCRIPTS = sorted(glob.glob(os.path.join(TOOLS, "*.sh")))
# 直接執行的入口腳本（要有執行權限）；pi_common.sh 是 source 用、pi_hello.sh／pi_probe_remote.sh 是送到 Pi 用 bash -s 跑
ENTRY_SCRIPTS = ("net_probe.sh", "pi_probe.sh", "pi_pull.sh", "pi_push.sh", "pi_run.sh", "pull_feedback.sh")

BASH = shutil.which("bash")
needs_posix_bash = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="需要 POSIX bash（Windows 跳過）")


def test_shell_tools_exist():
    names = {os.path.basename(p) for p in SCRIPTS}
    assert {"pi_common.sh", "pi_run.sh", "pi_push.sh", "pi_pull.sh", "pi_probe.sh", "net_probe.sh", "pull_feedback.sh"} <= names


@pytest.mark.parametrize("path", SCRIPTS, ids=os.path.basename)
def test_shell_tool_syntax_and_lf(path):
    with open(path, "rb") as f:
        assert b"\r" not in f.read(), "shell 腳本必須是 LF（.gitattributes *.sh eol=lf）"
    if BASH is None:
        pytest.skip("沒有 bash")
    res = subprocess.run([BASH, "-n", path], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr


def test_cmd_tools_use_configurable_key():
    for name in ("pi_run.cmd", "pi_push.cmd", "pi_pull.cmd", "pi_probe.cmd"):
        with open(os.path.join(TOOLS, name), encoding="ascii") as f:
            text = f.read()
        assert "PI5_SSH_KEY" in text and r"C:\Users\Andrew" not in text, name


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 沒有 POSIX 執行權限")
@pytest.mark.parametrize("name", ENTRY_SCRIPTS)
def test_entry_scripts_are_executable(name):
    """Mac／Linux 可以直接 ./tools/xxx.sh 執行（git 檔案模式 100755）。"""
    mode = os.stat(os.path.join(TOOLS, name)).st_mode
    assert mode & stat.S_IXUSR, f"{name} 沒有執行權限（git update-index --chmod=+x）"


# ---------------------------------------------------------------- 離線行為測試（stub）

_STUB = r"""#!/bin/sh
# 共用 stub：記下呼叫（指令名＋參數）到 $STUB_LOG，ssh 另外把 stdin 存起來
name=$(basename "$0")
printf '%s' "$name" >> "$STUB_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$STUB_LOG"; done; echo >> "$STUB_LOG"
case "$name" in
  uname) echo "${FAKE_UNAME:-Linux}" ;;
  ssh) cat > "$STUB_DIR/ssh_stdin.txt"; echo "fake-ssh-out"; exit "${STUB_SSH_RC:-0}" ;;
  scp) exit "${STUB_SCP_RC:-0}" ;;
  ping) for a in "$@"; do last=$a; done; [ "$last" = "192.168.50.229" ] ;;
  arp) echo "? (192.168.50.229) at aa:bb:cc:dd:ee:ff on en0"; echo "? (10.0.0.1) at 11:22:33:44:55:66 on en0" ;;
  ifconfig) [ -n "$STUB_NO_IFCONFIG" ] && exit 127; echo "${STUB_IFCONFIG_LINE:-	inet 192.168.50.10 netmask 0xffffff00 broadcast 192.168.50.255}" ;;
  ip) echo "    inet 192.168.50.11/24 brd 192.168.50.255 scope global wlan0" ;;
  curl) while [ $# -gt 0 ]; do [ "$1" = "-o" ] && { shift; cp "$STUB_DIR/feedback.zip" "$1"; }; shift; done; exit "${STUB_CURL_RC:-0}" ;;
esac
"""


@pytest.fixture
def stub_env(tmp_path):
    """PATH 最前面放 stub；回傳 (env, stub_dir, out_dir)。"""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    for name in ("ssh", "scp", "ping", "uname", "arp", "ifconfig", "ip", "curl"):
        p = stub_dir / name
        p.write_text(_STUB)
        p.chmod(0o755)
    out_dir = tmp_path / "out"
    env = dict(os.environ)
    env.update({
        "PATH": f"{stub_dir}{os.pathsep}{env.get('PATH', '')}",
        "STUB_LOG": str(stub_dir / "calls.log"),
        "STUB_DIR": str(stub_dir),
        "PI5_PROBE_OUT": str(out_dir),
        "PI5_SSH_KEY": "/nonexistent/test_key",
    })
    return env, stub_dir, out_dir


def _run(name, args, env, cwd=None):
    return subprocess.run([BASH, os.path.join(TOOLS, name), *args], env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=30)


def _calls(stub_dir, cmd):
    log = stub_dir / "calls.log"
    lines = log.read_text().splitlines() if log.exists() else []
    return [ln for ln in lines if ln.split(" ", 1)[0] == cmd]


@needs_posix_bash
@pytest.mark.parametrize("uname,expect", [
    ("Darwin", ["-c", "1", "-t", "2"]),        # macOS／BSD：-W 是毫秒，要用 -t 秒數
    ("FreeBSD", ["-c", "1", "-t", "2"]),
    ("Linux", ["-c", "1", "-W", "2"]),         # GNU iputils：-W 是秒
    ("MINGW64_NT-10.0", ["-n", "1", "-w", "2000"]),  # Git Bash 用 Windows 的 ping
])
def test_net_probe_ping_timeout_per_os(stub_env, uname, expect):
    env, stub_dir, out_dir = stub_env
    env["FAKE_UNAME"] = uname
    res = _run("net_probe.sh", [], env)
    assert res.returncode == 0, res.stderr
    pings = _calls(stub_dir, "ping")
    assert len(pings) == 2
    for call in pings:
        assert call.split(" ")[1:1 + len(expect)] == [f"[{a}]" for a in expect], call
    text = (out_dir / "net_probe.txt").read_text()
    assert "192.168.50.229 reachable" in text and "192.168.50.228 unreachable" in text
    assert (out_dir / "DONE.flag").exists()


@needs_posix_bash
def test_net_probe_arp_is_numeric_and_filters_subnet(stub_env):
    """arp 要加 -n（不做反查 DNS，離線時 arp -a 會卡住）；只留 192.168.50.x。"""
    env, stub_dir, out_dir = stub_env
    env["FAKE_UNAME"] = "Darwin"
    assert _run("net_probe.sh", [], env).returncode == 0
    arps = _calls(stub_dir, "arp")
    assert arps and ("[-n]" in arps[0] or "[-an]" in arps[0]), arps
    text = (out_dir / "net_probe.txt").read_text()
    assert "192.168.50.229" in text and "10.0.0.1" not in text


@needs_posix_bash
@pytest.mark.parametrize("line,no_ifconfig,expect", [
    ("\tinet 192.168.50.10 netmask 0xffffff00 broadcast 192.168.50.255", "", "192.168.50.10"),   # macOS ifconfig
    ("          inet addr:192.168.50.12  Bcast:192.168.50.255  Mask:255.255.255.0", "", "192.168.50.12"),  # 舊 net-tools
    ("", "1", "192.168.50.11"),                                                                    # 沒 ifconfig → ip
])
def test_net_probe_my_ip_formats(stub_env, line, no_ifconfig, expect):
    env, stub_dir, out_dir = stub_env
    env.update({"FAKE_UNAME": "Linux", "STUB_IFCONFIG_LINE": line, "STUB_NO_IFCONFIG": no_ifconfig})
    assert _run("net_probe.sh", [], env).returncode == 0
    assert expect in (out_dir / "net_probe.txt").read_text()


@needs_posix_bash
def test_pi_run_builds_ssh_command_and_propagates_exit(stub_env):
    env, stub_dir, out_dir = stub_env
    env["STUB_SSH_RC"] = "3"
    res = _run("pi_run.sh", ["10.9.9.9", "pi_hello.sh"], env)
    assert res.returncode == 3, "ssh 失敗要反映在 exit code"
    (call,) = _calls(stub_dir, "ssh")
    for part in ("[-i] [/nonexistent/test_key]", "[BatchMode=yes]", "[ConnectTimeout=6]", "[pi@10.9.9.9] [bash] [-s]"):
        assert part in call, call
    with open(os.path.join(TOOLS, "pi_hello.sh")) as f:
        assert (stub_dir / "ssh_stdin.txt").read_text() == f.read()
    log = (out_dir / "10.9.9.9_pi_hello.txt").read_text()
    assert "fake-ssh-out" in log and log.rstrip().endswith("exit=3")
    assert (out_dir / "DONE.flag").exists()


@needs_posix_bash
@pytest.mark.parametrize("name,args", [
    ("pi_run.sh", []), ("pi_run.sh", ["10.9.9.9"]),
    ("pi_push.sh", ["10.9.9.9", "a"]), ("pi_pull.sh", ["10.9.9.9"]),
])
def test_missing_args_print_usage_and_skip_ssh(stub_env, name, args):
    env, stub_dir, _ = stub_env
    res = _run(name, args, env)
    assert res.returncode == 2
    assert "usage" in res.stderr.lower()
    assert not _calls(stub_dir, "ssh") and not _calls(stub_dir, "scp")


@needs_posix_bash
def test_pi_run_missing_script_file(stub_env):
    env, stub_dir, _ = stub_env
    res = _run("pi_run.sh", ["10.9.9.9", "no_such_script.sh"], env)
    assert res.returncode == 2 and "no_such_script.sh" in res.stderr
    assert not _calls(stub_dir, "ssh")


@needs_posix_bash
def test_pi_push_then_script(stub_env, tmp_path):
    env, stub_dir, out_dir = stub_env
    local = tmp_path / "payload.txt"
    local.write_text("x")
    res = _run("pi_push.sh", ["10.9.9.9", str(local), "/tmp/payload.txt", "pi_hello.sh"], env)
    assert res.returncode == 0, res.stderr
    (scp,) = _calls(stub_dir, "scp")
    assert f"[{local}] [pi@10.9.9.9:/tmp/payload.txt]" in scp
    assert len(_calls(stub_dir, "ssh")) == 1
    assert (out_dir / "10.9.9.9_push.txt").read_text().rstrip().endswith("exit=0")


@needs_posix_bash
def test_pi_push_scp_failure_skips_script_and_fails(stub_env, tmp_path):
    env, stub_dir, out_dir = stub_env
    env["STUB_SCP_RC"] = "1"
    res = _run("pi_push.sh", ["10.9.9.9", str(tmp_path / "x"), "/tmp/x", "pi_hello.sh"], env)
    assert res.returncode == 1
    assert not _calls(stub_dir, "ssh"), "檔案沒傳上去就不要跑後續腳本"
    assert (out_dir / "DONE.flag").exists()


@needs_posix_bash
def test_pi_pull_script_then_scp(stub_env, tmp_path):
    env, stub_dir, out_dir = stub_env
    res = _run("pi_pull.sh", ["10.9.9.9", "/tmp/r.txt", str(tmp_path / "r.txt"), "pi_hello.sh"], env)
    assert res.returncode == 0, res.stderr
    log = (stub_dir / "calls.log").read_text().splitlines()
    assert [ln.split(" ", 1)[0] for ln in log if ln.split(" ", 1)[0] in ("ssh", "scp")] == ["ssh", "scp"]
    assert (out_dir / "10.9.9.9_pull.txt").exists()


@needs_posix_bash
def test_pi_probe_default_and_explicit_hosts(stub_env):
    env, stub_dir, out_dir = stub_env
    env["STUB_SSH_RC"] = "0"
    assert _run("pi_probe.sh", [], env).returncode == 0
    hosts = [c.split("[pi@")[1].split("]")[0] for c in _calls(stub_dir, "ssh")]
    assert hosts == ["192.168.50.228", "192.168.50.229"]
    assert (out_dir / "192.168.50.228.txt").read_text().rstrip().endswith("exit=0")
    assert _run("pi_probe.sh", ["10.1.1.1"], env).returncode == 0
    assert _calls(stub_dir, "ssh")[-1].count("[pi@10.1.1.1]") == 1


@needs_posix_bash
@pytest.mark.parametrize("with_unzip", [True, False])
def test_pull_feedback_offline(stub_env, tmp_path, with_unzip):
    """date／find／wc／tr 用系統真的（BSD 或 GNU）；沒有 unzip 時（Git Bash、python:slim）改用 python3 -m zipfile。"""
    env, stub_dir, _ = stub_env
    with zipfile.ZipFile(stub_dir / "feedback.zip", "w") as z:
        z.writestr("issue_001/report.json", "{}")
        z.writestr("issue_002/report.json", "{}")
    fb_root = tmp_path / "fb"
    env["PI5_FEEDBACK_DIR"] = str(fb_root)
    if not with_unzip:
        # unzip 通常和 date／find 同在 /usr/bin，不能整個目錄拿掉：另建只有必要指令的 PATH（沒有 unzip）
        sysbin = tmp_path / "sysbin"
        sysbin.mkdir()
        for tool in ("dirname", "date", "mkdir", "find", "wc", "tr", "cp", "basename", "cat"):
            os.symlink(shutil.which(tool), sysbin / tool)
        os.symlink(sys.executable, sysbin / "python3")
        env["PATH"] = f"{stub_dir}{os.pathsep}{sysbin}"
    elif shutil.which("unzip") is None:
        pytest.skip("這台沒有 unzip")
    res = _run("pull_feedback.sh", ["10.9.9.9", "8123"], env)
    assert res.returncode == 0, res.stderr
    (curl,) = _calls(stub_dir, "curl")
    assert "[http://10.9.9.9:8123/api/feedback/export.zip]" in curl
    (outdir,) = list(fb_root.iterdir())
    assert outdir.name.startswith("10.9.9.9_") and len(outdir.name) == len("10.9.9.9_20261123_182400")
    assert (outdir / "issue_001" / "report.json").exists()
    assert "拉回 2 筆回報" in res.stdout


@needs_posix_bash
def test_pull_feedback_download_failure(stub_env, tmp_path):
    env, stub_dir, _ = stub_env
    env["STUB_CURL_RC"] = "7"
    env["PI5_FEEDBACK_DIR"] = str(tmp_path / "fb")
    (stub_dir / "feedback.zip").write_bytes(b"")
    res = _run("pull_feedback.sh", ["10.9.9.9"], env)
    assert res.returncode == 1 and "下載失敗" in res.stderr
