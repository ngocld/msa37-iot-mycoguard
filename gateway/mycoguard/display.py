"""LED 7 đoạn 4 số TM1637 nối GPIO của Raspberry Pi (tùy chọn).

Cài thư viện: pip install raspberrypi-tm1637
Hiện luân phiên mỗi 3 giây: nhiệt độ (26*C), độ ẩm (H 81), ánh sáng (số lux).
Không có thư viện hoặc không chạy trên Pi thì lớp này tự tắt, không làm dừng gateway.
"""
import logging
import time

log = logging.getLogger("mycoguard.tm1637")


class Tm1637Display:
    PAGE_S = 3.0

    def __init__(self, enabled, clk=23, dio=24):
        self.tm = None
        self.frame = None
        self.page = 0
        self._last = 0.0
        if not enabled:
            return
        try:
            import tm1637                      # gói raspberrypi-tm1637
            self.tm = tm1637.TM1637(clk=clk, dio=dio)
            self.tm.brightness(4)
            self.tm.show("----")
            log.info("TM1637 sẵn sàng (CLK GPIO%d, DIO GPIO%d)", clk, dio)
        except Exception as exc:              # noqa: BLE001 - phần cứng tùy chọn
            log.warning("Không dùng được TM1637: %s", exc)
            self.tm = None

    @property
    def enabled(self):
        return self.tm is not None

    def update(self, frame):
        self.frame = frame

    def tick(self):
        if not self.tm or time.time() - self._last < self.PAGE_S:
            return
        self._last = time.time()
        f = self.frame
        try:
            if not f or f.get("t") is None:
                self.tm.show("Err " if f else "----")
                return
            if self.page == 0:
                self.tm.temperature(int(round(f["t"])))
            elif self.page == 1:
                self.tm.show(f"H{int(round(f['h'])):3d}")
            else:
                self.tm.number(min(int(f.get("lux", 0)), 9999))
            self.page = (self.page + 1) % 3
        except Exception as exc:              # noqa: BLE001
            log.warning("TM1637 lỗi: %s", exc)
