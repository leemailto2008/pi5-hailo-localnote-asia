# -*- coding: utf-8 -*-
"""
issue_feedback.py — 網頁「🐞 Issue 回報」（2026-11-20 使用者要求）：測試時遇到問題，按一下把當下狀況、log 與使用者描述存起來，事後拿出來重現、除錯。

存放：DATA_DIR/feedback/<YYYYMMDD_HHMMSS>_<主機>_<4 碼>/（一般磁碟，部署只換程式資料夾、重開也不會清掉）
  feedback.json    使用者描述、時間、版本、設定、會議狀態、/health、藍牙快取、瀏覽器端資訊
  service.log      服務 log（按下前 LOG_MINUTES 分鐘，最多 LOG_MAX_LINES 行）
  transcript.txt   可選：本場即時稿、高精度稿、紀要
  audio.ogg        可選：本場錄音最後 N 分鐘（錄音結束後才有母帶；錄音中按下時不附）
保留：KEEP_DAYS 天、最多 KEEP_MAX 筆、總量 KEEP_BYTES；超過刪最舊的。
錄音中按下也可以：只寫檔、讀 journal，不下藍牙 HCI 指令、不跑推論（CLAUDE.md 重點一）。
"""

import json
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
from typing import Any, Dict, List, Optional

from config import DATA_DIR

logger = logging.getLogger(__name__)

FEEDBACK_DIR = os.environ.get("PI5_FEEDBACK_DIR", os.path.join(DATA_DIR, "feedback"))
KEEP_DAYS = 90
KEEP_MAX = 200
KEEP_BYTES = 300 * 1024 * 1024
LOG_MINUTES = 15
LOG_MAX_LINES = 3000
AUDIO_MAX_MIN = 10
SERVICE = "pi5-dispatcher-api.service"
_ID_RE = re.compile(r"^\d{8}_\d{6}_[A-Za-z0-9-]{1,40}_[0-9a-f]{4}$")


def valid_id(report_id: str) -> bool:
    # fullmatch：re.match＋「$」會讓結尾多一個換行的 id 也算合法 (N8)
    return bool(_ID_RE.fullmatch(report_id or ""))


def new_id(now: Optional[float] = None) -> str:
    host = re.sub(r"[^A-Za-z0-9-]", "-", socket.gethostname())[:40] or "pi"
    return f"{time.strftime('%Y%m%d_%H%M%S', time.localtime(now or time.time()))}_{host}_{secrets.token_hex(2)}"


def service_log(minutes: int = LOG_MINUTES, max_lines: int = LOG_MAX_LINES) -> str:
    """服務 log 前 minutes 分鐘 (journalctl；不能讀時回傳原因，不讓回報失敗)。"""
    try:
        res = subprocess.run(["journalctl", "-u", SERVICE, "--since", f"-{int(minutes)}min", "--no-pager", "-o", "short-iso"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(讀不到服務 log：{e})"
    lines = (res.stdout or res.stderr or "").splitlines()
    if len(lines) > max_lines:
        lines = [f"(前面省略 {len(lines) - max_lines} 行)"] + lines[-max_lines:]
    return "\n".join(lines)


def cut_audio(src: str, dst: str, minutes: int) -> Optional[str]:
    """母帶最後 minutes 分鐘 (ffmpeg -c copy，不重新編碼)；失敗回傳原因字串，成功回 None。"""
    minutes = max(1, min(AUDIO_MAX_MIN, int(minutes)))
    if not os.path.isfile(src):
        return "沒有這場的錄音檔（錄音中、或已被環形緩衝清掉）"
    try:
        res = subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-sseof", f"-{minutes * 60}", "-i", src,
                              "-c", "copy", dst], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"擷取錄音失敗：{e}"
    if res.returncode != 0 or not os.path.isfile(dst):
        return f"擷取錄音失敗：{(res.stderr or '').strip()[:200]}"
    return None


def save(report: Dict[str, Any], log_text: str, transcript: Optional[str] = None,
         audio_src: Optional[str] = None, audio_minutes: int = 5) -> str:
    """寫一筆回報，回傳 id。report 會補上 id、附件結果。"""
    # 同一秒、同一個 4 碼亂數 (1／65536) 時不能寫進已經存在的資料夾、蓋掉別筆回報 (N8)：換一個 id 再試
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    for attempt in range(5):
        rid = new_id()
        folder = os.path.join(FEEDBACK_DIR, rid)
        try:
            os.mkdir(folder)
            break
        except FileExistsError:
            if attempt == 4:
                raise
    try:
        attachments: Dict[str, Any] = {}
        with open(os.path.join(folder, "service.log"), "w", encoding="utf-8") as f:
            f.write(log_text or "")
        if transcript is not None:
            with open(os.path.join(folder, "transcript.txt"), "w", encoding="utf-8") as f:
                f.write(transcript)
            attachments["transcript"] = "transcript.txt"
        if audio_src is not None:
            err = cut_audio(audio_src, os.path.join(folder, "audio.ogg"), audio_minutes)
            job = os.path.splitext(os.path.basename(audio_src))[0]
            attachments["audio"] = err or f"audio.ogg（{job} 最後 {max(1, min(AUDIO_MAX_MIN, int(audio_minutes)))} 分鐘）"
        report = {**report, "id": rid, "attachments": attachments}
        tmp = os.path.join(folder, "feedback.json.part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, os.path.join(folder, "feedback.json"))
    except BaseException:
        # 寫到一半失敗 (磁碟滿…)：整個資料夾拿掉，不留沒有 feedback.json 的半成品 (list_reports 會一直列成「讀不到」) (2026-11-23)
        shutil.rmtree(folder, ignore_errors=True)
        raise
    try:
        prune()
    except OSError as e:
        logger.warning("[IssueFeedback] 清舊回報失敗：%s", e)
    return rid


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for n in files:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError as e:   # 算大小時檔案剛被刪掉：不算這個檔
                print(f"[IssueFeedback] 算資料夾大小時略過 {n}：{e}")
    return total


def _all_ids() -> List[str]:
    if not os.path.isdir(FEEDBACK_DIR):
        return []
    return sorted(n for n in os.listdir(FEEDBACK_DIR) if valid_id(n))   # 名稱開頭是時間，排序即新舊


def prune(now: Optional[float] = None) -> List[str]:
    """超過 KEEP_DAYS 天、KEEP_MAX 筆或 KEEP_BYTES 的最舊回報刪掉；回傳刪掉的 id。"""
    now = now or time.time()
    ids = _all_ids()
    removed = []
    cutoff = time.strftime("%Y%m%d_%H%M%S", time.localtime(now - KEEP_DAYS * 86400))
    sizes = {i: _dir_size(os.path.join(FEEDBACK_DIR, i)) for i in ids}
    total = sum(sizes.values())
    for i in list(ids):
        if i[:15] < cutoff or len(ids) > KEEP_MAX or total > KEEP_BYTES:
            shutil.rmtree(os.path.join(FEEDBACK_DIR, i), ignore_errors=True)
            ids.remove(i)
            total -= sizes[i]
            removed.append(i)
        else:
            break
    return removed


def list_reports() -> List[Dict[str, Any]]:
    out = []
    for i in reversed(_all_ids()):
        path = os.path.join(FEEDBACK_DIR, i, "feedback.json")
        try:
            with open(path, encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError) as e:
            out.append({"id": i, "error": f"讀不到：{e}"})
            continue
        # 一筆格式不對不能拖垮整個列表 (2026-11-23：原本 AttributeError，/api/feedback 整個 500)
        if not isinstance(r, dict):
            out.append({"id": i, "error": f"讀不到：feedback.json 不是物件（{type(r).__name__}）"})
            continue
        status = r.get("status")
        out.append({"id": i, "time": r.get("time"), "name": r.get("name") or "", "description": str(r.get("description") or "")[:120],
                    "version": r.get("version"), "job": status.get("job") if isinstance(status, dict) else None,
                    "attachments": r.get("attachments") or {}, "size": _dir_size(os.path.join(FEEDBACK_DIR, i))})
    return out


def load(report_id: str) -> Dict[str, Any]:
    if not valid_id(report_id):
        raise ValueError("回報 id 格式不對")
    with open(os.path.join(FEEDBACK_DIR, report_id, "feedback.json"), encoding="utf-8") as f:
        return json.load(f)


def make_zip(report_ids: Optional[List[str]] = None) -> str:
    """把指定回報 (預設全部) 打包成暫存 zip，回傳路徑 (呼叫端送出後刪掉)。"""
    ids = _all_ids() if report_ids is None else [i for i in report_ids if valid_id(i)]
    fd, path = tempfile.mkstemp(prefix="localnote_feedback_", suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for i in ids:
            folder = os.path.join(FEEDBACK_DIR, i)
            if not os.path.isdir(folder):
                continue
            for n in sorted(os.listdir(folder)):
                z.write(os.path.join(folder, n), f"{i}/{n}")
    return path
