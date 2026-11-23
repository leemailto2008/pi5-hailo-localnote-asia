# code_dispatcher/bt_link_stats.py
"""
藍牙 SCO 封包到達率 (SCO Arrival Rate)：錄音中顯示「藍牙掉包 N%」用。

讀法：對 AF_BLUETOOTH 原始 HCI socket 做 ioctl(HCIGETDEVINFO)，取 Linux 核心裡 hci_dev 的統計計數
(與 `hciconfig hci0` 顯示的 `RX ... sco:N` 同一個數字)。這只是讀核心記憶體，**不會送任何 HCI 指令
給藍牙晶片**，不佔 UART，符合「錄音中禁止 HCI 指令」的規則 (CLAUDE.md〔重點一〕)。

為什麼不用 ZeroSplicer 剪掉的空白：PipeWire 1.6 會把壞幀與部分遺失補成假音訊，剪掉的空白只是下限。
2026-10-30 raspi678 喇叭自測 9 輪 (btmon 對照)：
- 到達率 ≥95%：CER 0.30–0.35
- 90–92%：CER 0.40 (此時剪掉的空白 < 1%，舊指標看不出來)
- ≤90%：CER 0.58–0.78
每 2 秒取樣算出的到達率與 btmon 差 0.1–1.6 個百分點。

mSBC 每 7.5 ms 一個 SCO 封包 (133.3 包/秒)。TX 計數由 PipeWire 依 RX 回送，兩者永遠相等，不能拿來當分母，
所以分母用 mSBC 標稱速率；量到的速率明顯高於標稱 (例如 CVSD) 時視為未知編碼，不回報。
"""
try:
    import fcntl
except ImportError:   # Windows 沒有 fcntl：讀不到計數，sco_rx_packets 回傳 None（同沒有藍牙）
    fcntl = None
import socket
import struct
import time
from collections import deque
from typing import Callable, Deque, Optional, Tuple

MSBC_PKTS_PER_SEC = 1000.0 / 7.5
_AF_BLUETOOTH = 31
_BTPROTO_HCI = 1
_HCIGETDEVINFO = 0x800448D3          # _IOR('H', 211, int)
# struct hci_dev_info (native 對齊)：dev_id, name[8], bdaddr, flags, type, features[8], pkt_type, link_policy,
# link_mode, acl_mtu, acl_pkts, sco_mtu, sco_pkts, 然後 hci_dev_stats 10 個 u32：
# err_rx, err_tx, cmd_tx, evt_rx, acl_tx, acl_rx, sco_tx, sco_rx, byte_rx, byte_tx
_DEV_INFO_FMT = "@H8s6sIB8sIIIHHHH10I"
_SCO_RX_INDEX = 13 + 7


def sco_rx_packets(dev_id: int = 0) -> Optional[int]:
    """hciN 自開機以來收到的 SCO 封包數；沒有藍牙或不支援時回傳 None。"""
    try:
        with socket.socket(_AF_BLUETOOTH, socket.SOCK_RAW, _BTPROTO_HCI) as s:
            buf = bytearray(struct.calcsize(_DEV_INFO_FMT))
            struct.pack_into("H", buf, 0, dev_id)
            fcntl.ioctl(s, _HCIGETDEVINFO, buf)
    except (OSError, AttributeError, ValueError):
        return None
    return struct.unpack(_DEV_INFO_FMT, buf)[_SCO_RX_INDEX]


class ArrivalMeter:
    """依 SCO 收包計數算到達率：最近 window_s 秒 (live) 與整段錄音 (total)，單位為百分比。"""

    def __init__(self, window_s: float = 10.0, interval_s: float = 1.0,
                 reader: Callable[[], Optional[int]] = sco_rx_packets,
                 clock: Callable[[], float] = time.monotonic):
        self.window_s = window_s
        self.interval_s = interval_s
        self._read = reader
        self._clock = clock
        self._samples: Deque[Tuple[float, int]] = deque()
        self._first: Optional[Tuple[float, int]] = None
        self._last_t = float("-inf")
        self.unknown_codec = False
        # 計數倒退 (控制器重新註冊、驅動重載時 hci_dev 統計歸零)：之前累計的數量接上，計數保持連續 (2026-11-23：原本算出負的到達率)
        self._last_raw: Optional[int] = None
        self._offset = 0

    def tick(self) -> None:
        """在錄音迴圈中頻繁呼叫；每 interval_s 秒才真的讀一次計數。"""
        now = self._clock()
        if now - self._last_t < self.interval_s:
            return
        self._last_t = now
        raw = self._read()
        if raw is None:
            return
        if self._last_raw is not None and raw < self._last_raw:
            self._offset += self._last_raw
        self._last_raw = raw
        n = raw + self._offset
        if self._first is None:
            self._first = (now, n)
        self._samples.append((now, n))
        while len(self._samples) > 2 and now - self._samples[1][0] >= self.window_s:
            self._samples.popleft()

    def _sco_seen(self) -> bool:
        return bool(self._first and self._samples and self._samples[-1][1] > self._first[1])

    def _pct(self, a: Optional[Tuple[float, int]], b: Optional[Tuple[float, int]]) -> Optional[float]:
        if not a or not b or b[0] - a[0] < 1.5:
            return None
        if b[1] == a[1] and not self._sco_seen():
            return None                 # 從頭到尾沒有 SCO 封包：不是藍牙收音，或 SCO 還沒建立
        pct = 100.0 * (b[1] - a[1]) / ((b[0] - a[0]) * MSBC_PKTS_PER_SEC)
        if pct > 110.0:                 # 不是 mSBC (例如 CVSD 封包較密)：標稱速率不適用
            self.unknown_codec = True
        return None if self.unknown_codec else round(min(100.0, pct), 1)

    def live_pct(self) -> Optional[float]:
        return self._pct(self._samples[0] if self._samples else None, self._samples[-1] if self._samples else None)

    def total_pct(self) -> Optional[float]:
        return self._pct(self._first, self._samples[-1] if self._samples else None)
