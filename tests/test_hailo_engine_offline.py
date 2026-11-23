"""AI_HAT_plus/hailo_engine 的純邏輯部分：PCIe／hailortcli 探測解析（subprocess 換成假的）、音訊前處理。
不需要 Hailo 硬體、lspci、hailortcli、ffmpeg。

2026-11-23（localnote@mac）找到的 bug（device_manager）：
  1. lspci 比對用 "Hailo" in line.capitalize()：capitalize() 會把第一個字以外全變小寫，真實輸出
     「Co-processor [0b40]: Hailo Technologies Ltd. Hailo-10H AI Processor」永遠比不到；
     "1e60:" 只有 lspci -n／-nn 才印。→ pcie_detected 永遠 False、device_type 永遠 "None"。
  2. Hailo-10 寫到 "device_info" 而不是 "device_type"（打錯鍵）。
  3. voice_pipeline 用 dev_info["arch"] 判斷 Hailo-10H（不載 Hailo-8 Whisper HEF），但從來沒設 arch。
"""
import os
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AI_HAT_plus"))

from hailo_engine import audio_preprocessor as ap  # noqa: E402
from hailo_engine import device_manager as dm  # noqa: E402

LSPCI_10H = "0000:01:00.0 Co-processor [0b40]: Hailo Technologies Ltd. Hailo-10H AI Processor [1e60:2864]"
LSPCI_10H_PLAIN = "0001:01:00.0 Co-processor: Hailo Technologies Ltd. Hailo-10H AI Processor (rev 01)"
LSPCI_8 = "0000:01:00.0 Co-processor: Hailo Technologies Ltd. Hailo-8 AI Processor (rev 01)"
LSPCI_OTHER = "0000:00:00.0 PCI bridge: Broadcom Inc. and subsidiaries BCM2712 PCIe Bridge (rev 21)"


class _R:
    def __init__(self, out="", rc=0):
        self.stdout, self.returncode = out, rc


@pytest.fixture
def probe(monkeypatch):
    """回傳 run(lspci_lines, scan_out, scan_rc) → 新探測的 HailoDeviceManager。"""
    def run(lspci, scan_out="", scan_rc=0, lspci_error=None):
        def fake(cmd, **kw):
            if cmd[0] == "lspci":
                if lspci_error:
                    raise lspci_error
                return _R("\n".join(lspci))
            if cmd[:2] == ["hailortcli", "scan"]:
                return _R(scan_out, scan_rc)
            raise AssertionError(cmd)
        monkeypatch.setattr(dm.subprocess, "run", fake)
        monkeypatch.setattr(dm.HailoDeviceManager, "_instance", None)
        return dm.HailoDeviceManager()
    yield run
    dm.HailoDeviceManager._instance = None


@pytest.mark.parametrize("line", [LSPCI_10H, LSPCI_10H_PLAIN])
def test_detects_hailo10h_from_lspci(probe, line):
    m = probe([LSPCI_OTHER, line], "Hailo Devices:\n[-] Device: 0000:01:00.0\n")
    info = m.get_info()
    assert info["pcie_detected"] is True
    assert info["device_type"] == "Hailo-10H"
    assert info["arch"] == "HAILO10H"          # voice_pipeline 用這個判斷不載 Hailo-8 HEF
    assert info["driver_loaded"] is True and m.is_available()


def test_detects_hailo8(probe):
    info = probe([LSPCI_8], "Hailo Devices:\n[-] Device: 0000:01:00.0").get_info()
    assert (info["device_type"], info["arch"], info["pcie_detected"]) == ("Hailo-8", "HAILO8", True)


def test_unknown_hailo_pcie_device_by_vendor_id(probe):
    info = probe(["0000:01:00.0 0b40: 1e60:ffff"]).get_info()
    assert info["pcie_detected"] is True and info["device_type"] == "Hailo-PCIe"


def test_no_hailo(probe):
    m = probe([LSPCI_OTHER], "", scan_rc=1)
    info = m.get_info()
    assert info["pcie_detected"] is False and info["device_type"] == "None"
    assert not m.is_available() and not info["driver_loaded"]


def test_tools_missing(probe):
    """lspci 和 hailortcli 都不存在（Mac、CI）：不拋例外、回報不可用。"""
    m = probe([], lspci_error=FileNotFoundError("lspci"))
    assert not m.is_available()
    assert m.get_info()["python_binding"] in (True, False)


def test_scan_without_hailo_text_is_not_available(probe):
    assert not probe([LSPCI_10H], "No devices found", scan_rc=0).is_available()


def test_singleton_probes_once(monkeypatch):
    n = {"calls": 0}

    def fake(cmd, **kw):
        n["calls"] += 1
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(dm.subprocess, "run", fake)
    monkeypatch.setattr(dm.HailoDeviceManager, "_instance", None)
    try:
        assert dm.HailoDeviceManager() is dm.HailoDeviceManager()
        assert dm.is_hailo_available() is False
        assert n["calls"] == 2                    # lspci + hailortcli 各一次
    finally:
        dm.HailoDeviceManager._instance = None


# ---------------------------------------------------------------- audio_preprocessor

def test_pad_or_trim():
    assert len(ap.pad_or_trim(np.ones(10, np.float32))) == ap.N_SAMPLES
    assert len(ap.pad_or_trim(np.ones(ap.N_SAMPLES + 5, np.float32))) == ap.N_SAMPLES
    x = np.arange(20, dtype=np.float32)
    np.testing.assert_array_equal(ap.pad_or_trim(x, 5), x[:5])
    np.testing.assert_array_equal(ap.pad_or_trim(x, 20), x)


def test_load_audio_from_array_downmixes_stereo():
    stereo = np.array([[1.0, 0.0], [0.5, 0.5]], dtype=np.float64)
    out = ap.load_audio_pcm(stereo)
    assert out.dtype == np.float32 and out.tolist() == [0.5, 0.5]


def test_load_audio_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        ap.load_audio_pcm(str(tmp_path / "none.wav"))
    with pytest.raises(ValueError):
        ap.load_audio_pcm(12345)


def test_load_audio_via_ffmpeg(monkeypatch, tmp_path):
    src = tmp_path / "a.ogg"
    src.write_bytes(b"x")
    pcm = (np.ones(400, dtype=np.int16) * 16384).tobytes()
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _R(pcm, 0) if cmd[0] == "ffmpeg" else None)
    out = ap.load_audio_pcm(str(src))
    assert len(out) == 400 and np.allclose(out, 0.5)


def test_log_mel_shape_and_range():
    t = np.arange(ap.SAMPLE_RATE * 2) / ap.SAMPLE_RATE
    audio = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    mel = ap.log_mel_spectrogram(audio)
    assert mel.shape == (1, ap.N_MELS, ap.N_FRAMES) and mel.dtype == np.float32
    assert mel.min() >= -1.0 and mel.max() <= 1.0
    assert np.isfinite(mel).all()
