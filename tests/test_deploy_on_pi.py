"""tools/ci/deploy_on_pi.sh 的安全閘門（不打斷真人會議）、安裝、健康檢查與回滾（2026-11-23 localnote@mac，S8）。

curl／sudo／journalctl／sleep 換成 PATH 上的 stub，原始碼用暫存目錄裡的迷你 repo，部署目的地也在暫存目錄：
不碰真的 Pi、systemd 或網路。python3、cp、date 等用系統真的（macOS 的 bash 3.2 與 BSD 工具也驗）。

修正前會失敗的兩項：
- 會議結束（state=done）後高精度稿／潤稿／翻譯還在背景跑時照樣部署：重啟服務把它們中斷。
  15 分鐘閘門從錄音「開始」算，30 分鐘會議結束時早就過了。
- 健康檢查 curl 沒有 -f：/health 回 HTTP 500 也算「健康」，不回滾。
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tools", "ci", "deploy_on_pi.sh")
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="需要 POSIX bash（Windows 跳過）")

_STUB = r"""#!/bin/sh
name=$(basename "$0")
printf '%s' "$name" >> "$STUB_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$STUB_LOG"; done; echo >> "$STUB_LOG"
case "$name" in
  sleep) exit 0 ;;
  sudo) exit 0 ;;
  journalctl) cat "$STUB_DIR/journal.txt" 2>/dev/null; exit 0 ;;
  curl)
    fail=0; url=""
    for a in "$@"; do case "$a" in -f|-sf|-fs) fail=1 ;; http://*) url=$a ;; esac; done
    path=${url#http://127.0.0.1}
    case "$path" in
      /health)
        case "$(cat "$STUB_DIR/health")" in
          ok) echo '{"status":"ok"}'; exit 0 ;;
          500) echo 'Internal Server Error'; [ "$fail" = 1 ] && exit 22; exit 0 ;;
          *) exit 7 ;;
        esac ;;
      *)
        f="$STUB_DIR/api$(echo "$path" | tr '/' '_').json"
        if [ -f "$f" ]; then cat "$f"; exit 0; fi
        [ -f "$STUB_DIR/api_down" ] && exit 7
        echo '{"detail":"Not Found"}'; [ "$fail" = 1 ] && exit 22; exit 0 ;;
    esac ;;
esac
"""


@pytest.fixture
def env(tmp_path):
    stub = tmp_path / "stub"
    stub.mkdir()
    for n in ("curl", "sudo", "journalctl", "sleep"):
        (stub / n).write_text(_STUB, encoding="utf-8")
        (stub / n).chmod(0o755)
    (stub / "health").write_text("ok", encoding="utf-8")
    src = tmp_path / "src"                              # 迷你 repo
    for d in ("code_dispatcher/static", "hailo_whisper"):
        (src / d).mkdir(parents=True)
    (src / "code_dispatcher" / "app.py").write_text("X = 2\n", encoding="utf-8")
    (src / "code_dispatcher" / "ui.html").write_text("<html>new</html>", encoding="utf-8")
    (src / "code_dispatcher" / "static" / "a.css").write_text("new", encoding="utf-8")
    (src / "hailo_whisper" / "eng.py").write_text("Y = 2\n", encoding="utf-8")
    dst = tmp_path / "dst"                              # 部署目的地（舊版）
    (dst / "static").mkdir(parents=True)
    (dst / "hailo_whisper").mkdir()
    (dst / "app.py").write_text("X = 1\n", encoding="utf-8")
    (dst / "ui.html").write_text("<html>old</html>", encoding="utf-8")
    e = dict(os.environ)
    e.update({"PATH": f"{stub}{os.pathsep}{e.get('PATH', '')}", "STUB_LOG": str(stub / "calls.log"), "STUB_DIR": str(stub),
              "LN_APP_DIR": str(dst), "LN_E2E_JOBS_FILE": str(tmp_path / "e2e_jobs.txt"),
              "PYTHONPYCACHEPREFIX": str(tmp_path / "pycache")})
    e.pop("LN_DEPLOY_FORCE", None)
    return {"env": e, "stub": stub, "src": src, "dst": dst, "tmp": tmp_path}


def _api(env, path, obj):
    (env["stub"] / f"api{path.replace('/', '_')}.json").write_text(json.dumps(obj), encoding="utf-8")


def _deploy(env):
    return subprocess.run([BASH, SCRIPT, str(env["src"])], env=env["env"], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)


def _restarted(env):
    log = env["stub"] / "calls.log"
    return log.exists() and "[systemctl] [restart]" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("state", ["recording", "processing"])
def test_busy_meeting_blocks_deploy(env, state):
    _api(env, "/api/status", {"state": state, "job": "m_1"})
    r = _deploy(env)
    assert r.returncode == 75 and "忙碌" in r.stdout and not _restarted(env)
    assert (env["dst"] / "app.py").read_text(encoding="utf-8") == "X = 1\n"


def test_recent_human_job_blocks_unless_forced(env):
    _api(env, "/api/status", {"state": "done", "job": f"m_{int(time.time()) - 60}"})
    r = _deploy(env)
    assert r.returncode == 75 and "15 分鐘" in r.stdout and not _restarted(env)
    env["env"]["LN_DEPLOY_FORCE"] = "1"
    assert _deploy(env).returncode == 0 and _restarted(env)


def test_recent_e2e_job_does_not_block(env):
    job = f"m_{int(time.time()) - 60}"
    _api(env, "/api/status", {"state": "done", "job": job})
    (env["tmp"] / "e2e_jobs.txt").write_text(job + "\n", encoding="utf-8")
    assert _deploy(env).returncode == 0


@pytest.mark.parametrize("endpoint", ["/api/refine", "/api/polish", "/api/translate_transcript"])
def test_background_job_running_blocks_deploy(env, endpoint):
    """會議結束後的高精度稿／潤稿／翻譯還在跑：不能重啟服務。"""
    _api(env, "/api/status", {"state": "done", "job": f"m_{int(time.time()) - 3600}"})
    _api(env, endpoint, {"state": "running", "started": time.time() - 30})
    r = _deploy(env)
    assert r.returncode == 75 and not _restarted(env), r.stdout
    assert endpoint.split("/")[-1] in r.stdout
    env["env"]["LN_DEPLOY_FORCE"] = "1"
    assert _deploy(env).returncode == 0


def test_background_jobs_done_or_old_server_without_endpoints(env):
    _api(env, "/api/status", {"state": "done", "job": f"m_{int(time.time()) - 3600}"})
    _api(env, "/api/refine", {"state": "done"})
    # /api/polish、/api/translate_transcript 沒有 → stub 回 404（舊版服務）：不擋
    assert _deploy(env).returncode == 0


def test_successful_deploy_installs_and_keeps_10_backups(env):
    _api(env, "/api/status", {"state": "idle"})
    bk = env["dst"] / ".deploy_backup"
    for i in range(12):
        (bk / f"20260101_0000{i:02d}").mkdir(parents=True)
        os.utime(bk / f"20260101_0000{i:02d}", (1_700_000_000 + i, 1_700_000_000 + i))
    r = _deploy(env)
    assert r.returncode == 0, r.stdout + r.stderr
    dst = env["dst"]
    assert (dst / "app.py").read_text(encoding="utf-8") == "X = 2\n"
    assert (dst / "static" / "a.css").exists() and (dst / "hailo_whisper" / "eng.py").exists()
    for f in ("ui_client.html", "static/ui_client.html", "static/index.html"):
        assert (dst / f).read_text(encoding="utf-8") == "<html>new</html>"
    assert len(os.listdir(bk)) == 10                    # 新的一份＋最近 9 份
    assert not (env["src"] / "code_dispatcher" / "__pycache__").exists()   # py_compile 的 pyc 不寫進 repo


def test_api_down_still_deploys(env):
    (env["stub"] / "api_down").write_text("", encoding="utf-8")
    assert _deploy(env).returncode == 0                 # 服務本來就掛了：部署（修好它）不會打斷任何人


@pytest.mark.parametrize("health,journal", [("500", ""), ("down", ""), ("ok", "Traceback (most recent call last):\n")])
def test_failed_health_check_rolls_back(env, health, journal):
    _api(env, "/api/status", {"state": "idle"})
    (env["stub"] / "health").write_text(health, encoding="utf-8")
    (env["stub"] / "journal.txt").write_text(journal, encoding="utf-8")
    r = _deploy(env)
    assert r.returncode == 1 and "回滾" in r.stdout, r.stdout
    assert (env["dst"] / "app.py").read_text(encoding="utf-8") == "X = 1\n"    # 換回舊版
    assert (env["stub"] / "calls.log").read_text(encoding="utf-8").count("[systemctl] [restart]") == 2


def test_syntax_error_stops_before_install(env):
    _api(env, "/api/status", {"state": "idle"})
    (env["src"] / "code_dispatcher" / "app.py").write_text("def broken(:\n", encoding="utf-8")
    r = _deploy(env)
    assert r.returncode != 0 and not _restarted(env)
    assert (env["dst"] / "app.py").read_text(encoding="utf-8") == "X = 1\n"


def test_human_job_exactly_15_minutes_old_does_not_block(env):
    """S19 突變測試：15 分鐘閘門的邊界（900 s → 901 s 的突變原本沒被抓到）。剛好 900 s 前開始的 job 不擋
    （腳本裡是 < 900）；秒數在腳本執行時剛好跳到 901 也一樣不擋，所以這個測試不會因為時間誤判而失敗。"""
    _api(env, "/api/status", {"state": "done", "job": f"m_{int(time.time()) - 900}"})
    r = _deploy(env)
    assert r.returncode == 0 and _restarted(env), r.stdout
