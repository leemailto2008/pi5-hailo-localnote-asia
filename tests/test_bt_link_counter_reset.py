"""bt_link_stats.ArrivalMeter：SCO 收包計數歸零（藍牙控制器重新註冊、驅動重載）時不能算出負的到達率。
2026-11-23 localnote@mac（S12 深度審查）：原本 (b - a) 直接相除 → 計數從 13,000 掉到 0 後 live／total 變成負數，
整段到達率之後一直是錯的。偵測到計數倒退就把之前累計的數量接上（位移），計數保持連續。
"""
import bt_link_stats as b
from bt_link_stats import MSBC_PKTS_PER_SEC, ArrivalMeter


class Link:
    def __init__(self):
        self.t, self.n = 0.0, 5000.0

    def run(self, meter, secs, rate=MSBC_PKTS_PER_SEC, step=0.5):
        for _ in range(int(secs / step)):
            self.t += step
            self.n += rate * step
            meter.tick()


def _meter(link):
    return ArrivalMeter(window_s=10.0, interval_s=1.0, reader=lambda: int(link.n), clock=lambda: link.t)


def test_counter_reset_does_not_go_negative():
    link = Link()
    m = _meter(link)
    link.run(m, 30)
    assert m.live_pct() == 100.0 and m.total_pct() == 100.0
    link.n = 0.0                              # 控制器重新註冊：計數歸零
    link.run(m, 3)
    assert m.live_pct() is None or 0.0 <= m.live_pct() <= 100.0
    assert m.total_pct() is None or 0.0 <= m.total_pct() <= 100.0
    link.run(m, 20)
    assert m.live_pct() == 100.0               # 視窗過了：照常
    assert 95.0 <= m.total_pct() <= 100.0     # 整段：只少了歸零那一秒內沒數到的封包


def test_counter_reset_with_real_loss_is_still_reported():
    link = Link()
    m = _meter(link)
    link.run(m, 20)
    link.n = 0.0
    link.run(m, 20, rate=MSBC_PKTS_PER_SEC * 0.8)
    assert 78.0 <= m.live_pct() <= 82.0


def test_normal_behaviour_unchanged():
    link = Link()
    m = _meter(link)
    assert m.live_pct() is None                # 還沒有樣本
    link.run(m, 12, rate=MSBC_PKTS_PER_SEC * 0.9)
    assert 89.0 <= m.live_pct() <= 91.0
    link.run(m, 12, rate=0)                    # SCO 中斷：0%
    assert m.live_pct() == 0.0
