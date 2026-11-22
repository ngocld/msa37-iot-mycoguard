"""Vòng lặp nền mỗi giây: chọn kênh, đẩy cấu hình, khung giờ chiếu sáng, ping, nhắc thông gió."""
import logging
import threading
import time
from datetime import datetime, timedelta

log = logging.getLogger("mycoguard.scheduler")

VENT_DAY_START, VENT_DAY_END = 6, 20     # chỉ nhắc thông gió ban ngày


def light_period(profile, now=None):
    """1 nếu đang trong khung giờ chiếu sáng. Hồ sơ không đặt giờ thì luôn đánh giá ánh sáng."""
    on, off = profile.get("light_on"), profile.get("light_off")
    if not on or not off:
        return 1
    now = now or datetime.now()
    t = now.strftime("%H:%M")
    if on <= off:
        return 1 if on <= t < off else 0
    return 1 if t >= on or t < off else 0      # khung giờ qua nửa đêm


class Scheduler(threading.Thread):
    def __init__(self, cfg, db, links, processor, display=None):
        super().__init__(name="scheduler", daemon=True)
        self.cfg = cfg
        self.db = db
        self.links = links
        self.processor = processor
        self.display = display
        self._push = True
        self._last_push = 0.0
        self._last_ping = 0.0
        self._last_lp = None
        last = db.last_alert_time("vent")
        self._last_vent = last.timestamp() if last else time.time()
        processor.request_push = self.request_push

    def request_push(self):
        self._push = True

    def vent_interval_s(self):
        hours = self.processor.profile.get("vent_remind_hours") or 0
        return hours * 3600 / self.cfg.time_scale if hours else None

    def next_vent(self):
        interval = self.vent_interval_s()
        if not interval:
            return None
        return (datetime.fromtimestamp(self._last_vent) + timedelta(seconds=interval)).strftime("%H:%M")

    def run(self):
        while True:
            try:
                self._step()
            except Exception:                  # noqa: BLE001 - vòng lặp nền không được chết
                log.exception("Lỗi trong vòng lặp nền")
            time.sleep(1)

    def _step(self):
        now = time.time()
        self.links.tick()
        profile = self.processor.profile

        if self.links.active:
            if self._push or now - self._last_push >= self.cfg.resend_config_every_s:
                self._push = False
                self._last_push = now
                th = f"{profile['t_min']:g},{profile['t_max']:g},{profile['h_min']:g},{profile['h_max']:g}," \
                     f"{profile['lux_min']},{profile['lux_max']}"
                self.links.send("TH", th, wait=False)
                self._last_lp = light_period(profile)
                self.links.send("LP", self._last_lp, wait=False)
                log.info("Đã gửi ngưỡng hồ sơ '%s' xuống Arduino", profile["name"])

            lp = light_period(profile)
            if lp != self._last_lp:
                self._last_lp = lp
                self.links.send("LP", lp, wait=False)

            if now - self._last_ping >= self.cfg.ping_every_s:
                self._last_ping = now
                self.links.send("PING", wait=False, record=False)

        self.processor.tick(now)

        interval = self.vent_interval_s()
        hour = datetime.now().hour
        if interval and VENT_DAY_START <= hour < VENT_DAY_END and now - self._last_vent >= interval:
            self._last_vent = now
            if self.processor.open_reminder():
                log.info("Nhắc thông gió theo lịch")

        if self.display:
            self.display.tick()
