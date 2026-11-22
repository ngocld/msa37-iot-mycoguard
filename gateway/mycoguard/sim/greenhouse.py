"""Mô hình nhà nấm + Arduino ảo.

Arduino ảo chạy cùng logic với firmware (status.h, mycoguard_node.ino): cùng ngưỡng, biên,
vùng trễ, cùng khung JSON và lệnh. Nhờ vậy gateway và dashboard chạy y hệt khi có phần cứng.
"""
import math
import queue
import random
import threading
import time
from datetime import datetime, timedelta

from ..protocol import FLAG_BIT, FLAG_KEYS

# Hằng số giống config.h
MARGIN_T, MARGIN_H = 2.0, 5.0
MARGIN_LUX_RATIO, MARGIN_LUX_MIN = 0.30, 20.0
HYST_T, HYST_H, HYST_LUX = 0.5, 2.0, 20.0
LAMP_LUX_FULL = 350.0           # đèn chiếu sáng 100% đặt sát quang trở cộng thêm ~350 lux

# Việc người vận hành làm tại nhà nấm (chỉ có trong mô phỏng): khóa -> (nhãn, số giây)
SIM_ACTIONS = {
    "phun_suong": ("Phun sương 45 giây", 45),
    "tuoi_nen": ("Tưới ẩm nền 60 giây", 60),
    "mo_cua": ("Mở cửa thông gió 2 phút", 120),
    "bat_quat": ("Bật quạt 2 phút", 120),
    "che_sang": ("Che / bỏ che lưới", 0),
}

SCENARIOS = {
    "binh_thuong": "Trở về bình thường",
    "nang_nong": "Trưa nắng nóng",
    "kho_hanh": "Gió khô hanh",
    "che_ldr": "Che quang trở 60 giây",
    "loi_dht22": "DHT22 hỏng 40 giây",
    "mat_bt": "Mất Bluetooth 40 giây",
    "mat_ket_noi": "Mất kết nối 20 giây",
}

FLAG_TAG = ["LANH", "NONG", "AM THAP", "AM CAO", "THIEU SANG", "QUA SANG", "LOI DHT22"]
FLAG_TIP = ["Can: giu nhiet", "Can: lam mat", "Can: phun suong", "Can: mo thong gio",
            "Can: bat den", "Can: che bot sang", "Kiem tra DHT22"]
FLAG_PRIORITY = ["sensor", "t_high", "h_low", "h_high", "t_low", "l_low", "l_high"]


# ============================================================
#  Mô hình môi trường
# ============================================================
class Environment:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.temp = 26.0
        self.rh = 89.0
        self.lux = 0.0
        self.timers = {"phun_suong": 0.0, "tuoi_nen": 0.0, "mo_cua": 0.0, "bat_quat": 0.0}
        self.shade = False
        self.cover_until = 0.0
        self.reset_scenario()

    def reset_scenario(self):
        self.scenario = {"name": "binh_thuong", "t_out": None, "rh_out": None, "light_mul": 1.0, "until": 0.0}

    def outside(self, hour):
        """Thời tiết ngoài trời theo giờ trong ngày: nóng và khô nhất khoảng 15 giờ."""
        phase = 2 * math.pi * (hour - 9) / 24
        t_out = 27 + 4 * math.sin(phase)
        rh_out = 72 - 8 * math.sin(phase)
        sun = math.sin(math.pi * (hour - 6) / 12) if 6 <= hour <= 18 else 0.0
        sc = self.scenario
        if sc["t_out"] is not None:
            t_out = sc["t_out"]
        if sc["rh_out"] is not None:
            rh_out = sc["rh_out"]
        return t_out, rh_out, 420 * max(0.0, sun) * sc["light_mul"]

    def step(self, dt, now_ts, hour, lamp_pwm):
        if self.scenario["until"] and now_ts >= self.scenario["until"]:
            self.reset_scenario()
        t_out, rh_out, sun_lux = self.outside(hour)
        door = self.timers["mo_cua"] > 0
        # Trao đổi nhiệt, ẩm với bên ngoài; mở cửa thì trao đổi nhanh hơn nhiều
        k_t = 1 / 60 if door else 1 / 400
        k_h = 1 / 90 if door else 1 / 600
        self.temp += (t_out - self.temp) * k_t * dt
        self.rh += (rh_out - self.rh) * k_h * dt
        if self.timers["phun_suong"] > 0:
            self.rh += 0.22 * dt
            self.temp -= 0.01 * dt
        if self.timers["tuoi_nen"] > 0:
            self.rh += 0.12 * dt
        if self.timers["bat_quat"] > 0:
            self.temp -= 0.02 * dt
            self.rh -= 0.02 * dt
        self.rh = min(99.0, max(20.0, self.rh))
        for key in self.timers:
            self.timers[key] = max(0.0, self.timers[key] - dt)

        lux = sun_lux * (0.35 if self.shade else 1.0) + lamp_pwm / 255 * LAMP_LUX_FULL
        if now_ts < self.cover_until:
            lux *= 0.05
        self.lux = lux


# ============================================================
#  Arduino ảo
# ============================================================
class Band:
    """Bản Python của struct Band trong status.h."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.low_out = self.high_out = False
        self.beyond_since = None
        self.danger = False

    def update(self, v, mn, mx, margin_low, margin_high, hyst, now, danger_after):
        if not self.low_out and v < mn:
            self.low_out = True
        elif self.low_out and v >= mn + hyst:
            self.low_out = False
        if not self.high_out and v > mx:
            self.high_out = True
        elif self.high_out and v <= mx - hyst:
            self.high_out = False
        beyond = False
        if self.low_out:
            beyond = (mn - v) > margin_low
        elif self.high_out:
            beyond = (v - mx) > margin_high
        if beyond:
            if self.beyond_since is None:
                self.beyond_since = now
            self.danger = now - self.beyond_since >= danger_after
        else:
            self.beyond_since = None
            self.danger = False

    def apply(self, low_key, high_key, flags, dflags):
        if self.low_out:
            flags |= 1 << FLAG_BIT[low_key]
        if self.high_out:
            flags |= 1 << FLAG_BIT[high_key]
        if self.danger:
            dflags |= 1 << FLAG_BIT[low_key if self.low_out else high_key]
        return flags, dflags


class VirtualNode:
    def __init__(self, env, danger_after_s=60.0, threaded=True):
        self.env = env
        self.danger_after = danger_after_s
        self.cfg = {"t_min": 22.0, "t_max": 28.0, "h_min": 85.0, "h_max": 95.0,
                    "lux_min": 200, "lux_max": 500, "lp": 1}
        self.bands = {"t": Band(), "h": Band(), "l": Band()}
        self.lock = threading.RLock()
        self.seq = 0
        self.temp = self.hum = None
        self.lux = 0.0
        self.flags = self.dflags = self.status = 0
        self.muted = False
        self.light = 0
        self.backlight = True
        self.msg, self.msg_until = "", 0.0
        self.test_until = 0.0
        self.fault_until = 0.0
        self.offline_until = 0.0
        self.last_cmd_at, self.last_cmd_link = 0.0, None
        self.links = []
        self._inbox = queue.Queue()
        if threaded:
            threading.Thread(target=self._inbox_loop, name="sim-node", daemon=True).start()

    # ---------- kết nối ----------
    def attach(self, link):
        self.links.append(link)

    def receive(self, text, link):
        self._inbox.put((text, link))

    def _inbox_loop(self):
        while True:
            text, link = self._inbox.get()
            # Độ trễ giống thật: USB nhanh, Bluetooth chậm hơn
            time.sleep(random.uniform(0.01, 0.04) if link.name == "USB" else random.uniform(0.05, 0.14))
            for line in text.splitlines():
                reply = self.handle(line.strip(), link.name)
                if reply and time.time() >= self.offline_until:
                    link.deliver(reply)

    # ---------- lệnh ----------
    def handle(self, line, source="USB"):
        if not line.startswith("#") or "|" not in line:
            return None
        head, _, rest = line.partition("|")
        cmd, _, args = rest.partition("|")
        try:
            cmd_id = int(head[1:])
        except ValueError:
            return None
        ok = True
        with self.lock:
            self.last_cmd_at, self.last_cmd_link = time.time(), source
            try:
                if cmd == "TH":
                    v = [float(x) for x in args.split(",")]
                    if len(v) != 6 or not (v[0] < v[1] and v[2] < v[3] and v[4] < v[5]):
                        ok = False
                    else:
                        self.cfg.update(t_min=v[0], t_max=v[1], h_min=v[2], h_max=v[3],
                                        lux_min=int(v[4]), lux_max=int(v[5]))
                        for band in self.bands.values():
                            band.reset()
                elif cmd == "LP":
                    self.cfg["lp"] = 1 if int(args or 0) else 0
                elif cmd == "MUTE":
                    self.muted = int(args or 0) != 0
                elif cmd == "MSG":
                    self.msg = "".join(c for c in args if 32 <= ord(c) < 127)[:20]
                    self.msg_until = time.time() + 60 if self.msg else 0
                elif cmd == "BL":
                    self.backlight = int(args or 0) != 0
                elif cmd == "TEST":
                    self.test_until = time.time() + 3
                elif cmd == "LIGHT":
                    self.light = max(0, min(255, int(args or 0)))
                elif cmd == "PING":
                    pass
                else:
                    ok = False
            except ValueError:
                ok = False
        return f'{{"ack":{cmd_id},"ok":{1 if ok else 0}}}'

    # ---------- đọc cảm biến và đánh giá ----------
    def sample(self, now):
        env, rng = self.env, self.env.rng
        if now < self.fault_until:
            self.temp = self.hum = None
        else:
            self.temp = round(env.temp + rng.gauss(0, 0.05), 1)
            self.hum = round(env.rh + rng.gauss(0, 0.2), 1)
        self.lux = max(0.0, env.lux * (1 + rng.gauss(0, 0.02)))
        self.evaluate(now)

    def evaluate(self, now):
        c, b = self.cfg, self.bands
        flags = dflags = 0
        if self.temp is None:
            b["t"].reset()
            b["h"].reset()
            flags |= 1 << FLAG_BIT["sensor"]
            dflags |= 1 << FLAG_BIT["sensor"]
        else:
            b["t"].update(self.temp, c["t_min"], c["t_max"], MARGIN_T, MARGIN_T, HYST_T, now, self.danger_after)
            b["h"].update(self.hum, c["h_min"], c["h_max"], MARGIN_H, MARGIN_H, HYST_H, now, self.danger_after)
            flags, dflags = b["t"].apply("t_low", "t_high", flags, dflags)
            flags, dflags = b["h"].apply("h_low", "h_high", flags, dflags)
        if c["lp"]:
            m_low = max(MARGIN_LUX_MIN, c["lux_min"] * MARGIN_LUX_RATIO)
            m_high = max(MARGIN_LUX_MIN, c["lux_max"] * MARGIN_LUX_RATIO)
            b["l"].update(self.lux, c["lux_min"], c["lux_max"], m_low, m_high, HYST_LUX, now, self.danger_after)
            flags, dflags = b["l"].apply("l_low", "l_high", flags, dflags)
        else:
            b["l"].reset()
        self.flags, self.dflags = flags, dflags
        self.status = 2 if dflags else (1 if flags else 0)
        if self.status < 2:
            self.muted = False

    def build_frame(self):
        self.seq += 1
        return {
            "seq": self.seq, "t": self.temp, "h": self.hum, "lux": int(self.lux), "light": self.light,
            "st": self.status, "f": self.flags, "d": self.dflags,
            "bz": 1 if self.status == 2 and not self.muted else 0, "mu": 1 if self.muted else 0,
            "lp": self.cfg["lp"], "err": 1 if self.temp is None else 0,
        }

    def step(self, now):
        """Một chu kỳ 2 giây của firmware: đọc, đánh giá, gửi khung lên mọi kênh."""
        import json
        with self.lock:
            self.sample(now)
            line = json.dumps(self.build_frame(), separators=(",", ":"))
        if now < self.offline_until:
            return
        for link in self.links:
            link.deliver(line)

    # ---------- màn hình LCD và đèn ảo ----------
    def worst_flag(self):
        for source in (self.dflags, self.flags):
            for key in FLAG_PRIORITY:
                if source & (1 << FLAG_BIT[key]):
                    return FLAG_BIT[key]
        return None

    def lcd_lines(self, now):
        with self.lock:
            if self.temp is None:
                l1 = "T: --.-C   H: --.-%"
            else:
                l1 = f"T:{self.temp:4.1f}C   H:{self.hum:5.1f}%"
            alive = self.last_cmd_at and now - self.last_cmd_at < 15
            link = ("BT" if self.last_cmd_link == "BT" else "USB") if alive else "--"
            l2 = f"Sang:{int(self.lux):5d} lux {'*' if self.light else ' '} {link:>3}"
            worst = self.worst_flag()
            st = ["OK", "CHU Y", "NGUY HIEM"][self.status]
            l3 = f"{st:<9} {FLAG_TAG[worst] if worst is not None else 'ON DINH'}"
            if self.msg and now < self.msg_until:
                l4 = self.msg
            elif worst is not None:
                l4 = ">" + FLAG_TIP[worst]
            else:
                l4 = "Moi thu on dinh"
            return [s[:20].ljust(20) for s in (l1, l2, l3, l4)]

    def leds(self, now):
        with self.lock:
            if now < self.test_until:
                step = int((self.test_until - now) / 0.25) % 3
                return {"green": step == 2, "yellow": step == 1, "red": step == 0, "buzzer": True,
                        "light": self.light}
            return {"green": self.status == 0, "yellow": self.status == 1, "red": self.status == 2,
                    "buzzer": self.status == 2 and not self.muted, "light": self.light}


# ============================================================
#  Bộ mô phỏng
# ============================================================
class Simulator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.env = Environment()
        self.node = VirtualNode(self.env, danger_after_s=20.0 if cfg.sim_fast else 60.0)
        self.links = {}
        self.lock = threading.Lock()
        self.events = []

    def make_links(self):
        from ..links import SimLink
        self.links = {"BT": SimLink("BT", self.node), "USB": SimLink("USB", self.node)}
        return list(self.links.values())

    def start(self):
        threading.Thread(target=self._run, name="simulator", daemon=True).start()

    def _run(self):
        last = time.time()
        next_frame = last
        while True:
            now = time.time()
            dt = now - last
            last = now
            dt_obj = datetime.now()
            hour = dt_obj.hour + dt_obj.minute / 60 + dt_obj.second / 3600
            with self.lock:
                self.env.step(dt, now, hour, self.node.light)
                for name, link in self.links.items():
                    until = getattr(link, "down_until", 0)
                    if until and now >= until:
                        link.enabled, link.down_until = True, 0
            if now >= next_frame:
                next_frame = now + 2.0
                self.node.step(now)
            time.sleep(0.25)

    def _log(self, text):
        self.events.insert(0, {"ts": datetime.now().strftime("%H:%M:%S"), "text": text})
        del self.events[8:]

    def action(self, key):
        if key not in SIM_ACTIONS:
            raise ValueError("Hành động không hợp lệ")
        label, seconds = SIM_ACTIONS[key]
        with self.lock:
            if key == "che_sang":
                self.env.shade = not self.env.shade
                label = "Che lưới giảm sáng" if self.env.shade else "Bỏ lưới che sáng"
            else:
                self.env.timers[key] = seconds
        self._log(label)
        return label

    def scenario(self, key):
        if key not in SCENARIOS:
            raise ValueError("Kịch bản không hợp lệ")
        now = time.time()
        with self.lock:
            env = self.env
            if key == "binh_thuong":
                env.reset_scenario()
                env.cover_until = 0
                self.node.fault_until = 0
                self.node.offline_until = 0
                for link in self.links.values():
                    link.enabled, link.down_until = True, 0
            elif key == "nang_nong":
                env.scenario = {"name": key, "t_out": 36.0, "rh_out": 60.0, "light_mul": 1.8, "until": now + 600}
            elif key == "kho_hanh":
                env.scenario = {"name": key, "t_out": None, "rh_out": 42.0, "light_mul": 1.0, "until": now + 600}
            elif key == "che_ldr":
                env.cover_until = now + 60
            elif key == "loi_dht22":
                self.node.fault_until = now + 40
            elif key == "mat_bt":
                link = self.links.get("BT")
                if link:
                    link.enabled, link.down_until = False, now + 40
            elif key == "mat_ket_noi":
                self.node.offline_until = now + 20
        self._log(SCENARIOS[key])
        return SCENARIOS[key]

    def snapshot(self):
        now = time.time()
        with self.lock:
            env = self.env
            dt_obj = datetime.now()
            t_out, rh_out, _ = env.outside(dt_obj.hour + dt_obj.minute / 60)
            sc = env.scenario
            return {
                "env": {"temp": round(env.temp, 1), "rh": round(env.rh, 1), "lux": int(env.lux),
                        "t_out": round(t_out, 1), "rh_out": round(rh_out, 1)},
                "running": {k: int(v) for k, v in env.timers.items() if v > 0},
                "shade": env.shade,
                "scenario": {"key": sc["name"], "label": SCENARIOS.get(sc["name"], ""),
                             "left_s": int(sc["until"] - now) if sc["until"] else None},
                "links": {name: link.enabled for name, link in self.links.items()},
                "lcd": self.node.lcd_lines(now),
                "lcd_backlight": self.node.backlight,
                "leds": self.node.leds(now),
                "actions": {k: v[0] for k, v in SIM_ACTIONS.items()},
                "scenarios": SCENARIOS,
                "events": list(self.events),
            }

    # ---------- sinh lịch sử để biểu đồ có dữ liệu ngay ----------
    def backfill(self, db, profile, hours=24):
        from ..scheduler import light_period
        rng = random.Random(20261122)
        env = Environment(rng)
        node = VirtualNode(env, danger_after_s=60.0, threaded=False)
        node.cfg.update(t_min=profile["t_min"], t_max=profile["t_max"], h_min=profile["h_min"],
                        h_max=profile["h_max"], lux_min=profile["lux_min"], lux_max=profile["lux_max"])
        end = datetime.now()
        t = end - timedelta(hours=hours)
        rows, step = [], 5
        while t < end:
            ts = t.timestamp()
            hour = t.hour + t.minute / 60 + t.second / 3600
            node.cfg["lp"] = light_period(profile, t)
            # Người vận hành ảo: thấy ẩm thấp thì phun sương, nóng thì bật quạt, thiếu sáng thì bật đèn
            if env.rh < profile["h_min"] + 0.5 and env.timers["phun_suong"] <= 0 and rng.random() < 0.12:
                env.timers["phun_suong"] = 45
            if env.temp > profile["t_max"] - 0.3 and env.timers["bat_quat"] <= 0 and rng.random() < 0.1:
                env.timers["bat_quat"] = 120
            sun_only = env.lux - node.light / 255 * LAMP_LUX_FULL
            node.light = 150 if node.cfg["lp"] and sun_only < profile["lux_min"] + 30 else 0
            env.step(step, ts, hour, node.light)
            node.sample(ts)
            f = node.build_frame()
            rows.append((t.strftime("%Y-%m-%d %H:%M:%S"), f["seq"], f["t"], f["h"], f["lux"], f["light"],
                         f["st"], f["f"], "SIM-USB"))
            t += timedelta(seconds=step)
        db.insert_readings_bulk(rows)
        # Môi trường thật của mô phỏng bắt đầu từ trạng thái cuối của lịch sử
        self.env.temp, self.env.rh = env.temp, max(env.rh, profile["h_min"] + 3)
        return len(rows)


__all__ = ["Simulator", "SIM_ACTIONS", "SCENARIOS", "FLAG_KEYS"]
