"""telegram_agent 獨立執行時 (sys.path 只有 telegram_agent)，text_to_speech_async 不給輸出路徑也要能合成。

2026-11-23 S6 審查：cd5e8e6 改成 `from voice_memory import ...`，但 telegram_agent 底下沒有 voice_memory
→ 把 NameError 換成 ImportError。改用 /dev/shm/audio_cache (沒有就系統暫存)。
用子行程跑，免得和 code_dispatcher 的 config／voice_pipeline 同名模組互相干擾；gTTS 與 ffmpeg 換成假的。
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TG_DIR = os.path.join(ROOT, "telegram_agent")

SNIPPET = r"""
import asyncio, os, subprocess, sys, types
sys.path = [p for p in sys.path if "code_dispatcher" not in p]
sys.path.insert(0, {tg_dir!r})

class FakeTTS:
    def __init__(self, text, lang):
        self.lang = lang
    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"mp3")
sys.modules["gtts"] = types.SimpleNamespace(gTTS=FakeTTS)

def fake_run(cmd, **kw):
    with open(cmd[-1], "wb") as f:      # ffmpeg 最後一個參數是輸出檔
        f.write(b"ogg")
    return subprocess.CompletedProcess(cmd, 0)
subprocess.run = fake_run

import voice_pipeline as vp
assert "voice_memory" not in sys.modules
ok = asyncio.run(vp.text_to_speech_async("hello world"))
assert ok is True
print("ok")
"""


def test_tts_without_output_path_standalone():
    res = subprocess.run([sys.executable, "-c", SNIPPET.format(tg_dir=TG_DIR)], cwd=TG_DIR,
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert res.returncode == 0, res.stdout[-800:] + res.stderr[-1500:]
    assert res.stdout.strip().splitlines()[-1] == "ok"
