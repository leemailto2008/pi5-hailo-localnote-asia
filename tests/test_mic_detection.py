"""voice_pipeline.ensure_bluetooth_recording_ready() 的來源選擇：耳麥沒連線又沒有其他麥克風時要報錯，
不能默默錄 Dummy Output 的 monitor (2026-10-29 228 耳麥自動關機後錄了整段靜音)。用假的 pw-dump，不需要 PipeWire。"""
import asyncio
import json
import sys
import types

import pytest

sys.modules.setdefault("config", types.SimpleNamespace(WHISPER_MODEL_SIZE="small", WHISPER_DEVICE="cpu", WHISPER_COMPUTE_TYPE="int8",
                                                       DEFAULT_TTS_VOICE="zh-TW-HsiaoChenNeural", DATA_DIR="/tmp"))
import voice_pipeline as vp  # noqa: E402


def _node(nid, kind, **props):
    return {"id": nid, "type": kind, "info": {"props": props, "params": {}}}


DUMMY_SINK = _node(80, "PipeWire:Interface:Node", **{"media.class": "Audio/Sink", "node.name": "auto_null"})
USB_MIC = _node(81, "PipeWire:Interface:Node", **{"media.class": "Audio/Source", "node.name": "alsa_input.usb-mic"})
BT_DEV = {"id": 90, "type": "PipeWire:Interface:Device", "info": {"props": {"device.api": "bluez5"},
          "params": {"Profile": [{"name": "headset-head-unit"}], "EnumProfile": [{"name": "headset-head-unit", "index": 1}]}}}
BT_SRC = _node(91, "PipeWire:Interface:Node", **{"media.class": "Audio/Source", "node.name": "bluez_input_internal.A0_D1_2A_42_12_34.0",
                                                  "api.bluez5.codec": "msbc"})


class _Proc:
    def __init__(self, out=b""):
        self.out = out

    async def communicate(self):
        return self.out, b""


@pytest.fixture()
def pw(monkeypatch):
    monkeypatch.setattr(vp, "_ensure_process_affinities", lambda: None)

    async def no_wait(node):
        return None
    monkeypatch.setattr(vp, "_wait_for_live_audio", no_wait)

    def use(nodes):
        async def fake_exec(*args, **kw):
            return _Proc(json.dumps(nodes).encode() if args[0] == "pw-dump" else b"")
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return use


def test_no_headset_and_no_microphone_raises(pw):
    pw([DUMMY_SINK])
    with pytest.raises(vp.NoMicrophoneError):
        asyncio.run(vp.ensure_bluetooth_recording_ready())


def test_other_microphone_keeps_default(pw):
    pw([DUMMY_SINK, USB_MIC])
    assert asyncio.run(vp.ensure_bluetooth_recording_ready()) == "default"


def test_headset_connected_but_source_not_ready_keeps_default(pw):
    pw([DUMMY_SINK, BT_DEV])
    assert asyncio.run(vp.ensure_bluetooth_recording_ready()) == "default"


def test_native_bluetooth_source_is_selected(pw):
    pw([DUMMY_SINK, BT_DEV, BT_SRC])
    assert asyncio.run(vp.ensure_bluetooth_recording_ready()) == "bluez_input_internal.A0_D1_2A_42_12_34.0"


GS3_MIC = _node(82, "PipeWire:Interface:Node", **{"media.class": "Audio/Source", "device.api": "alsa", "device.bus": "usb",
                                                   "node.name": "alsa_input.usb-GS3_GS3_20180508-00.analog-stereo",
                                                   "node.description": "GS3 Analog Stereo"})
GS3_MONITOR = _node(83, "PipeWire:Interface:Node", **{"media.class": "Audio/Sink", "device.api": "alsa", "device.bus": "usb",
                                                       "node.name": "alsa_output.usb-GS3_GS3_20180508-00.analog-stereo"})


@pytest.fixture()
def pref_file(monkeypatch, tmp_path):
    path = tmp_path / "mic_preference.json"
    monkeypatch.setattr(vp, "MIC_PREF_PATH", str(path))
    return path


def test_usb_microphone_is_used_when_no_headset(pw, pref_file):
    # 11-11：沒有耳麥、只有 USB 音效卡時明確錄它，不再交給 pulse default。
    pw([DUMMY_SINK, GS3_MONITOR, GS3_MIC])
    assert asyncio.run(vp.ensure_bluetooth_recording_ready()) == "alsa_input.usb-GS3_GS3_20180508-00.analog-stereo"


def test_headset_wins_by_default_over_usb(pw, pref_file):
    pw([GS3_MIC, BT_DEV, BT_SRC])
    assert asyncio.run(vp.ensure_bluetooth_recording_ready()) == "bluez_input_internal.A0_D1_2A_42_12_34.0"


def test_usb_preference_wins_over_headset(pw, pref_file):
    vp.save_mic_preference("usb")
    pw([BT_DEV, BT_SRC, GS3_MIC])
    assert asyncio.run(vp.ensure_bluetooth_recording_ready()) == "alsa_input.usb-GS3_GS3_20180508-00.analog-stereo"


def test_usb_preference_falls_back_to_headset(pw, pref_file):
    vp.save_mic_preference("usb")
    pw([BT_DEV, BT_SRC])
    assert asyncio.run(vp.ensure_bluetooth_recording_ready()) == "bluez_input_internal.A0_D1_2A_42_12_34.0"


def test_mic_preference_persists_and_rejects_unknown(pref_file):
    assert vp.load_mic_preference() == "bluetooth"
    assert vp.save_mic_preference("usb") == "usb"
    assert json.loads(pref_file.read_text(encoding="utf-8")) == {"prefer": "usb"}
    assert vp.load_mic_preference() == "usb"
    with pytest.raises(ValueError):
        vp.save_mic_preference("hdmi")
    pref_file.write_text("not json", encoding="utf-8")
    assert vp.load_mic_preference() == "bluetooth"


def test_list_microphones_reports_headset_and_usb_only():
    nodes = [DUMMY_SINK, GS3_MONITOR, GS3_MIC, USB_MIC,
             _node(92, "PipeWire:Interface:Node", **{"media.class": "Audio/Source", "node.name": "bluez_input.A0:D1:2A:42:12:34",
                                                      "node.description": "RichChipAN"})]
    assert vp.list_microphones(nodes) == [
        {"kind": "usb", "node": "alsa_input.usb-GS3_GS3_20180508-00.analog-stereo", "name": "GS3 Analog Stereo"},
        {"kind": "bluetooth", "node": "bluez_input.A0:D1:2A:42:12:34", "name": "RichChipAN"},
    ]