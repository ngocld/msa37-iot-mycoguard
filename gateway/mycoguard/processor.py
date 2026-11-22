"""Xử lý biên: lưu số đo, vòng đời cảnh báo, gợi ý hành động, Grow Score, lệnh thiết bị."""
import logging
import threading
import time

from .db import now_str, parse_ts
from .profiles import ALERT_TEXT, DEFAULT_ACTION_FOR
from .protocol import FLAG_KEYS, METRIC_OF, has_flag, to_lcd_text

log = logging.getLogger("mycoguard.processor")

ONLINE_TIMEOUT_S = 8.0


def _band_score(value, lo, hi, margin_low, margin_high):
    """1.0 khi trong ngưỡng, giảm dần về 0 khi lệch tới 2 lần biên."""
    if value is None:
        return None
    if lo <= value <= hi:
        return 1.0
    if value < lo:
        return max(0.0, 1 - (lo - value) / (2 * margin_low))
    return max(0.0, 1 - (value - hi) / (2 * margin_high))


def lux_margins(profile):
    return max(20.0, 0.3 * profile["lux_min"]), max(20.0, 0.3 * profile["lux_max"])


class Processor:
    def __init__(self, cfg, db):
        self.cfg = cfg
        self.db = db
        self.links = None
        self.display = None
        self.request_push = lambda: None       # scheduler gán: đẩy ngưỡng xuống Arduino
        self.lock = threading.RLock()

        self.latest = None
        self.latest_rx = 0.0
        self.latest_link = None
        self._last_store = 0.0
        self._last_status = None
        self._on_since = {k: None for k in FLAG_KEYS}
        self._off_since = {k: None for k in FLAG_KEYS}
        self._last_mute = 0.0
        self.backlight = True

        self.active = {a["metric"]: a for a in db.active_alerts()}
        self.profile = db.active_profile()

    def attach(self, links, display=None):
        self.links = links
        self.display = display

    def _link_label(self, name):
        return f"SIM-{name}" if self.cfg.link == "sim" else name

    # ============================================================
    #  Nhận khung dữ liệu
    # ============================================================
    def on_frame(self, frame, link_name):
        now = time.time()
        with self.lock:
            self.latest = frame
            self.latest_rx = now
            self.latest_link = link_name
            st = frame.get("st")
            if now - self._last_store >= self.cfg.store_every_s or st != self._last_status:
                self.db.insert_reading(now_str(), frame, self._link_label(link_name))
                self._last_store, self._last_status = now, st
            self._update_alerts(frame, now)
            # Cảnh báo đã có người nhận thì không để còi kêu lại
            need_mute = bool(frame.get("bz")) and any(
                a["state"] in ("ACKED", "HANDLED") and a["metric"] != "vent" for a in self.active.values())
        if need_mute and now - self._last_mute > 5:
            self._last_mute = now
            self.links.send("MUTE", 1, wait=False)
        if self.display:
            self.display.update(frame)

    @staticmethod
    def _value_of(key, frame):
        group = METRIC_OF[key]
        return {"temp": frame.get("t"), "humidity": frame.get("h"), "light": frame.get("lux")}.get(group)

    def _update_alerts(self, frame, now):
        f, d = frame.get("f", 0), frame.get("d", 0)
        sensor_fault = has_flag(f, "sensor")
        debounce = self.cfg.alert_debounce_s
        for key in FLAG_KEYS:
            on = has_flag(f, key)
            if on:
                self._off_since[key] = None
                self._on_since[key] = self._on_since[key] or now
            else:
                self._on_since[key] = None
                self._off_since[key] = self._off_since[key] or now

            alert = self.active.get(key)
            level = 2 if has_flag(d, key) else 1
            if on and alert is None and now - self._on_since[key] >= debounce:
                self._open(key, level, self._value_of(key, frame))
            elif on and alert is not None and level > alert["level"]:
                self.active[key] = self.db.update_alert(alert["id"], level=level)
            elif not on and alert is not None and now - self._off_since[key] >= debounce:
                if sensor_fault and METRIC_OF[key] in ("temp", "humidity"):
                    continue          # đang lỗi cảm biến thì chưa biết đã về ngưỡng hay chưa
                self._resolve(alert)

    def _open(self, key, level, value):
        message, suggestion = ALERT_TEXT[key]
        alert = self.db.open_alert(key, level, value, message, suggestion)
        self.active[key] = alert
        log.warning("Cảnh báo #%s: %s (%s)", alert["id"], message, value)
        return alert

    def _resolve(self, alert):
        resolution = "HUMAN" if alert["handled_at"] else "AUTO"
        self.db.update_alert(alert["id"], state="RESOLVED", resolved_at=now_str(), resolution=resolution)
        self.active.pop(alert["metric"], None)
        log.info("Cảnh báo #%s đã khắc phục (%s)", alert["id"], resolution)

    def tick(self, now=None):
        """Gọi mỗi giây: đã xử lý mà quá thời gian theo dõi vẫn lệch thì chuyển 'Chưa hiệu quả'."""
        with self.lock:
            for key, alert in list(self.active.items()):
                if alert["state"] != "HANDLED" or key == "vent":
                    continue
                handled = parse_ts(alert["handled_at"])
                if handled and (time.time() - handled.timestamp()) >= self.cfg.verify_window_s:
                    self.active[key] = self.db.update_alert(alert["id"], state="REOPEN")
                    log.warning("Cảnh báo #%s chưa được khắc phục sau khi xử lý", alert["id"])

    def open_reminder(self):
        with self.lock:
            if "vent" in self.active:
                return None
            return self._open("vent", 1, None)

    # ============================================================
    #  Người vận hành
    # ============================================================
    def _find(self, aid):
        for alert in self.active.values():
            if alert["id"] == aid:
                return alert
        return None

    def ack(self, aid):
        with self.lock:
            alert = self._find(aid)
            if alert is None:
                raise ValueError("Cảnh báo này đã đóng hoặc không tồn tại")
            if alert["state"] in ("OPEN", "REOPEN"):
                alert = self.db.update_alert(aid, state="ACKED", acked_at=alert["acked_at"] or now_str())
                self.active[alert["metric"]] = alert
        result = self.links.send("MUTE", 1)
        return alert, result

    def handle(self, aid, action, operator, note):
        with self.lock:
            alert = self._find(aid)
            if alert is None:
                raise ValueError("Cảnh báo này đã đóng hoặc không tồn tại")
            if alert["state"] == "HANDLED":
                raise ValueError("Cảnh báo đã được xử lý, hệ thống đang theo dõi kết quả")
            ts = now_str()
            fields = {"state": "HANDLED", "handled_at": ts}
            if not alert["acked_at"]:
                fields["acked_at"] = ts
            alert = self.db.update_alert(aid, **fields)
            self.db.insert_action(aid, action, operator, note)
            if alert["metric"] == "vent":
                alert = self.db.update_alert(aid, state="RESOLVED", resolved_at=ts, resolution="HUMAN")
                self.active.pop("vent", None)
            else:
                self.active[alert["metric"]] = alert
        self.links.send("MUTE", 1, wait=False)
        log.info("Cảnh báo #%s: %s đã %s", aid, operator or "người vận hành", action)
        return alert

    def device_command(self, cmd, value, operator):
        """Lệnh thiết bị từ dashboard. Trả về (kết quả gửi lệnh, mô tả để ghi nhật ký)."""
        if cmd == "light":
            percent = int(max(0, min(100, int(value))))
            pwm = round(percent * 2.55)
            result = self.links.send("LIGHT", pwm)
            text = f"Bật đèn chiếu sáng {percent}%" if pwm else "Tắt đèn chiếu sáng"
        elif cmd == "mute":
            result, text = self.links.send("MUTE", 1), "Tắt còi"
        elif cmd == "test":
            result, text = self.links.send("TEST", 1), "Thử đèn báo và còi"
        elif cmd == "backlight":
            on = bool(value)
            result = self.links.send("BL", 1 if on else 0)
            if result["ok"]:
                self.backlight = on
            text = "Bật đèn nền LCD" if on else "Tắt đèn nền LCD"
        elif cmd == "msg":
            msg = to_lcd_text(value or "")
            result = self.links.send("MSG", msg)
            text = f"Nhắn lên LCD: {msg}" if msg else "Xóa lời nhắn trên LCD"
        else:
            raise ValueError("Lệnh không hợp lệ")
        if result.get("ok"):
            self.db.insert_action(None, text, operator, None)
        return result, text

    # ============================================================
    #  Hồ sơ
    # ============================================================
    def activate_profile(self, pid):
        profile = self.db.activate_profile(pid)
        if profile is None:
            raise ValueError("Không tìm thấy hồ sơ")
        with self.lock:
            self.profile = profile
        self.request_push()
        return profile

    def update_profile(self, pid, data):
        profile = self.db.update_profile(pid, data)
        if profile and profile["active"]:
            with self.lock:
                self.profile = profile
            self.request_push()
        return profile

    # ============================================================
    #  Ảnh chụp trạng thái cho dashboard
    # ============================================================
    def snapshot(self):
        now = time.time()
        with self.lock:
            frame = dict(self.latest) if self.latest else None
            age = now - self.latest_rx if frame else None
            profile = dict(self.profile)
            alerts = [self._alert_view(a, now) for a in self.active.values()]
            link_name = self.latest_link
        alerts.sort(key=lambda a: (-a["level"], a["id"]))
        online = frame is not None and age <= ONLINE_TIMEOUT_S
        reading = None
        if frame:
            reading = dict(frame, age_s=round(age, 1), link=link_name)
        return {
            "online": online,
            "status": frame.get("st", 0) if online else -1,
            "reading": reading,
            "metrics": self._metrics(frame, profile) if frame else None,
            "grow_score": self._grow_score(frame, profile) if online else None,
            "profile": profile,
            "alerts": alerts,
            "device": {
                "light_pct": round((frame or {}).get("light", 0) / 2.55) if frame else 0,
                "muted": bool((frame or {}).get("mu")),
                "buzzing": bool((frame or {}).get("bz")),
                "backlight": self.backlight,
            },
        }

    def _alert_view(self, alert, now):
        view = dict(alert)
        opened = parse_ts(alert["opened_at"])
        view["age_s"] = int(now - opened.timestamp()) if opened else 0
        view["group"] = METRIC_OF.get(alert["metric"], "vent")
        view["default_action"] = DEFAULT_ACTION_FOR.get(alert["metric"], "Khác")
        if alert["state"] == "HANDLED" and alert["handled_at"]:
            handled = parse_ts(alert["handled_at"]).timestamp()
            view["verify_left_s"] = max(0, int(self.cfg.verify_window_s - (now - handled)))
        return view

    @staticmethod
    def _metrics(frame, p):
        f, d = frame.get("f", 0), frame.get("d", 0)
        sensor = has_flag(f, "sensor")

        def level(low, high):
            if has_flag(d, low) or has_flag(d, high):
                return 2
            return 1 if has_flag(f, low) or has_flag(f, high) else 0

        def note(low, high):
            if has_flag(f, low):
                return "Thấp hơn ngưỡng"
            if has_flag(f, high):
                return "Cao hơn ngưỡng"
            return "Trong ngưỡng"

        lp = bool(frame.get("lp"))
        return {
            "temp": {"value": frame.get("t"), "min": p["t_min"], "max": p["t_max"], "unit": "°C",
                     "level": 2 if sensor else level("t_low", "t_high"),
                     "note": "Lỗi cảm biến DHT22" if sensor else note("t_low", "t_high")},
            "humidity": {"value": frame.get("h"), "min": p["h_min"], "max": p["h_max"], "unit": "%",
                         "level": 2 if sensor else level("h_low", "h_high"),
                         "note": "Lỗi cảm biến DHT22" if sensor else note("h_low", "h_high")},
            "light": {"value": frame.get("lux"), "min": p["lux_min"], "max": p["lux_max"], "unit": "lux",
                      "level": level("l_low", "l_high") if lp else 0, "active": lp,
                      "note": note("l_low", "l_high") if lp else "Ngoài giờ chiếu sáng"},
        }

    @staticmethod
    def _grow_score(frame, p):
        if frame.get("err") or frame.get("t") is None:
            return None
        parts = [
            _band_score(frame["t"], p["t_min"], p["t_max"], 2.0, 2.0),
            _band_score(frame["h"], p["h_min"], p["h_max"], 5.0, 5.0),
        ]
        if frame.get("lp"):
            low, high = lux_margins(p)
            parts.append(_band_score(frame.get("lux", 0), p["lux_min"], p["lux_max"], low, high))
        return round(100 * sum(parts) / len(parts))
