"""Quản lý nhiều kênh truyền: bỏ khung trùng theo seq, chọn kênh đang chạy, gửi lệnh có ACK và gửi lại."""
import logging
import queue
import threading
import time
from collections import deque

from .protocol import build_command, parse_line

log = logging.getLogger("mycoguard.links")


class LinkStats:
    def __init__(self, name):
        self.name = name
        self.frames = 0
        self.lost = 0
        self.last_seq = None
        self.last_rx = 0.0
        self.alive_since = None


class LinkManager:
    def __init__(self, links, preference, cfg, db):
        """links: danh sách Link; preference: thứ tự ưu tiên tên kênh, ví dụ ["BT", "USB"]."""
        self.cfg = cfg
        self.db = db
        self.links = {l.name: l for l in links}
        self.preference = [p for p in preference if p in self.links]
        self.stats = {l.name: LinkStats(l.name) for l in links}
        self.active = None
        self.failovers = 0
        self.last_seq = None
        self.latencies = deque(maxlen=30)
        self.events = deque(maxlen=20)       # nhật ký chuyển kênh để hiện trên dashboard
        self.on_frame = None
        self.on_restart = None
        self._lock = threading.Lock()
        self._pending = {}
        self._next_id = 1
        self._jobs = queue.Queue()

    def start(self, on_frame, on_restart=None):
        self.on_frame = on_frame
        self.on_restart = on_restart
        threading.Thread(target=self._command_worker, name="commands", daemon=True).start()
        for link in self.links.values():
            link.start(self._on_line)

    # ---------- nhận ----------
    def _on_line(self, link, line):
        parsed = parse_line(line)
        if not parsed:
            return
        kind, data = parsed
        if kind == "ack":
            with self._lock:
                pending = self._pending.get(data.get("ack"))
            if pending:
                pending["ok"] = bool(data.get("ok"))
                pending["event"].set()
            return

        now = time.time()
        seq = data["seq"]
        st = self.stats[link.name]
        with self._lock:
            reconnected = not st.last_rx or now - st.last_rx > self.cfg.link_timeout_s
            if reconnected:
                st.alive_since = now
            st.last_rx = now
            # Mất gói theo từng kênh, chỉ tính khi kênh vẫn đang sống.
            # Khoảng trống do kênh bị ngắt hẳn được tính là lần mất kết nối, không phải mất gói.
            if not reconnected and st.last_seq is not None and 1 < seq - st.last_seq <= 30:
                st.lost += seq - st.last_seq - 1
            st.last_seq = seq
            st.frames += 1

            # Bỏ trùng giữa các kênh: Arduino gửi cùng một khung lên mọi kênh
            restart = False
            if self.last_seq is None:
                accept, restart = True, True          # khung đầu tiên: đẩy cấu hình xuống
            elif seq > self.last_seq:
                accept = True
            elif seq < self.last_seq - 20:
                accept, restart = True, True          # Arduino vừa khởi động lại
            else:
                accept = False
            if accept:
                self.last_seq = seq

        if restart:
            log.info("Arduino bắt đầu gửi dữ liệu (seq=%s)", seq)
            if self.on_restart:
                self.on_restart()
        if accept and self.on_frame:
            self.on_frame(data, link.name)

    def _alive(self, name, now):
        s = self.stats[name]
        return bool(s.last_rx) and now - s.last_rx <= self.cfg.link_timeout_s

    def tick(self):
        """Gọi mỗi giây: chọn kênh đang chạy theo thứ tự ưu tiên."""
        now = time.time()
        with self._lock:
            current = self.active
            choice = None
            for name in self.preference:
                if not self._alive(name, now):
                    continue
                stable = now - (self.stats[name].alive_since or now) >= self.cfg.link_stable_s
                if name != current and current is not None and self._alive(current, now) and not stable:
                    continue        # chờ kênh ưu tiên ổn định rồi mới chuyển về
                choice = name
                break
            changed = choice != current
            if changed:
                if current is not None and choice is not None:
                    self.failovers += 1
                self.active = choice
        if changed:
            text = f"{current or 'không có'} → {choice or 'mất kết nối'}"
            self.events.appendleft({"ts": time.strftime("%H:%M:%S"), "text": text})
            log.info("Chuyển kênh: %s", text)

    # ---------- gửi lệnh ----------
    def send(self, cmd, args="", wait=True, record=True, timeout=6.0):
        job = {"cmd": cmd, "args": str(args), "record": record, "done": threading.Event(), "result": None}
        self._jobs.put(job)
        if not wait:
            return None
        job["done"].wait(timeout)
        return job["result"] or {"ok": False, "status": "timeout", "retries": 0, "link": self.active}

    def _command_worker(self):
        while True:
            job = self._jobs.get()
            try:
                result = self._execute(job["cmd"], job["args"])
            except Exception:                              # noqa: BLE001
                log.exception("Lỗi khi gửi lệnh %s", job["cmd"])
                result = {"ok": False, "status": "error", "retries": 0, "link": self.active}
            job["result"] = result
            job["done"].set()
            if job["record"]:
                self.db.insert_command(job["cmd"], job["args"], result)

    def _execute(self, cmd, args):
        with self._lock:
            cmd_id = self._next_id
            self._next_id = self._next_id % 9999 + 1
            pending = {"event": threading.Event(), "ok": False}
            self._pending[cmd_id] = pending
        line = build_command(cmd_id, cmd, args)
        link_name = None
        try:
            for attempt in range(self.cfg.cmd_retries + 1):
                link_name = self.active
                if link_name is None:
                    return {"ok": False, "status": "no_link", "retries": attempt, "link": None}
                sent_at = time.time()
                if not self.links[link_name].write(line):
                    time.sleep(0.2)
                    continue
                if pending["event"].wait(self.cfg.ack_timeout_s):
                    latency = int((time.time() - sent_at) * 1000)
                    self.latencies.append(latency)
                    return {"ok": pending["ok"], "status": "acked" if pending["ok"] else "rejected",
                            "retries": attempt, "latency_ms": latency, "link": link_name}
            return {"ok": False, "status": "no_ack", "retries": self.cfg.cmd_retries, "link": link_name}
        finally:
            with self._lock:
                self._pending.pop(cmd_id, None)

    # ---------- số liệu cho dashboard ----------
    def snapshot(self):
        now = time.time()
        links = []
        with self._lock:
            for name, s in self.stats.items():
                link = self.links[name]
                total = s.frames + s.lost
                links.append({
                    "name": name,
                    "kind": link.kind,
                    "alive": self._alive(name, now),
                    "connected": link.connected and getattr(link, "enabled", True),
                    "frames": s.frames,
                    "lost": s.lost,
                    "loss_pct": round(100.0 * s.lost / total, 2) if total else 0.0,
                    "last_rx_age": round(now - s.last_rx, 1) if s.last_rx else None,
                    "port": link.describe(),
                })
            lat = list(self.latencies)
        return {
            "active": self.active,
            "failovers": self.failovers,
            "latency_ms": lat[-1] if lat else None,
            "avg_latency_ms": round(sum(lat) / len(lat)) if lat else None,
            "links": links,
            "events": list(self.events)[:6],
        }
