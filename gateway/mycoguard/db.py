"""Truy cập SQLite. Mọi thời gian lưu dạng giờ địa phương 'YYYY-MM-DD HH:MM:SS'."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT
from .profiles import DEFAULT_PROFILES

SCHEMA_PATH = ROOT / "database" / "schema.sql"
TS_FMT = "%Y-%m-%d %H:%M:%S"
METRIC_COLUMN = {"temp": "temp", "humidity": "humidity", "light": "lux"}
PROFILE_FIELDS = ["name", "t_min", "t_max", "h_min", "h_max", "lux_min", "lux_max",
                  "light_on", "light_off", "vent_remind_hours"]


def now_str(dt=None):
    return (dt or datetime.now()).strftime(TS_FMT)


def parse_ts(text):
    return datetime.strptime(text, TS_FMT) if text else None


def seconds_between(start, end):
    a, b = parse_ts(start), parse_ts(end)
    return (b - a).total_seconds() if a and b else None


def to_epoch_ms(text):
    return int(parse_ts(text).timestamp() * 1000)


class Database:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            self.conn.commit()
        self._seed_profiles()

    # ---------- tiện ích ----------
    def _rows(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def _row(self, sql, params=()):
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.lastrowid

    # ---------- hồ sơ ----------
    def _seed_profiles(self):
        if self._row("SELECT COUNT(*) AS n FROM profiles")["n"]:
            return
        for p in DEFAULT_PROFILES:
            self._exec(
                "INSERT INTO profiles (name,t_min,t_max,h_min,h_max,lux_min,lux_max,light_on,light_off,"
                "vent_remind_hours,active) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (p["name"], p["t_min"], p["t_max"], p["h_min"], p["h_max"], p["lux_min"], p["lux_max"],
                 p["light_on"], p["light_off"], p["vent_remind_hours"], p.get("active", 0)))

    def list_profiles(self):
        return self._rows("SELECT * FROM profiles ORDER BY id")

    def get_profile(self, pid):
        return self._row("SELECT * FROM profiles WHERE id=?", (pid,))

    def active_profile(self):
        return self._row("SELECT * FROM profiles WHERE active=1 ORDER BY id LIMIT 1") or \
            self._row("SELECT * FROM profiles ORDER BY id LIMIT 1")

    def activate_profile(self, pid):
        with self.lock:
            self.conn.execute("UPDATE profiles SET active = CASE WHEN id=? THEN 1 ELSE 0 END", (pid,))
            self.conn.commit()
        return self.get_profile(pid)

    def update_profile(self, pid, data):
        sets = ", ".join(f"{k}=?" for k in PROFILE_FIELDS)
        self._exec(f"UPDATE profiles SET {sets} WHERE id=?", tuple(data[k] for k in PROFILE_FIELDS) + (pid,))
        return self.get_profile(pid)

    # ---------- số đo ----------
    def insert_reading(self, ts, frame, link):
        self._exec(
            "INSERT INTO readings (ts,seq,temp,humidity,lux,light,status,flags,link) VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, frame.get("seq"), frame.get("t"), frame.get("h"), frame.get("lux"), frame.get("light"),
             frame.get("st"), frame.get("f"), link))

    def insert_readings_bulk(self, rows):
        with self.lock:
            self.conn.executemany(
                "INSERT INTO readings (ts,seq,temp,humidity,lux,light,status,flags,link) VALUES (?,?,?,?,?,?,?,?,?)",
                rows)
            self.conn.commit()

    def count_readings(self):
        return self._row("SELECT COUNT(*) AS n FROM readings")["n"]

    def history(self, metric, seconds):
        """Trung bình theo từng khoảng; trả về [[epoch_ms, giá trị], ...]."""
        col = METRIC_COLUMN[metric]
        bucket = 10 if seconds <= 3600 else 120 if seconds <= 86400 else 900
        since = now_str(datetime.now() - timedelta(seconds=seconds))
        rows = self._rows(
            f"SELECT CAST(strftime('%s', ts) AS INTEGER) / ? AS b, AVG({col}) AS v "
            f"FROM readings WHERE ts >= ? AND {col} IS NOT NULL GROUP BY b ORDER BY b",
            (bucket, since))
        points = []
        for r in rows:
            # strftime('%s') coi chuỗi giờ địa phương như UTC: đổi ngược lại về giờ địa phương
            naive = datetime.fromtimestamp(r["b"] * bucket, tz=timezone.utc).replace(tzinfo=None)
            points.append([int(naive.timestamp() * 1000), round(r["v"], 1)])
        return points, bucket

    def readings_page(self, date=None, page=1, size=20):
        where, params = "", []
        if date:
            where, params = "WHERE ts LIKE ?", [f"{date}%"]
        total = self._row(f"SELECT COUNT(*) AS n FROM readings {where}", params)["n"]
        rows = self._rows(
            f"SELECT ts,temp,humidity,lux,light,status,link FROM readings {where} "
            f"ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", params + [size, (page - 1) * size])
        return rows, total

    def iter_readings(self, date=None):
        where, params = "", []
        if date:
            where, params = "WHERE ts LIKE ?", [f"{date}%"]
        with self.lock:
            cur = self.conn.execute(
                f"SELECT ts,temp,humidity,lux,light,status,link FROM readings {where} ORDER BY ts", params)
            rows = cur.fetchall()
        for r in rows:
            yield tuple(r)

    # ---------- cảnh báo ----------
    def open_alert(self, metric, level, value, message, suggestion):
        ts = now_str()
        aid = self._exec(
            "INSERT INTO alerts (opened_at,level,metric,value,message,suggestion,state) VALUES (?,?,?,?,?,?, 'OPEN')",
            (ts, level, metric, value, message, suggestion))
        return self.get_alert(aid)

    def get_alert(self, aid):
        return self._row("SELECT * FROM alerts WHERE id=?", (aid,))

    def update_alert(self, aid, **fields):
        sets = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE alerts SET {sets} WHERE id=?", tuple(fields.values()) + (aid,))
        return self.get_alert(aid)

    def active_alerts(self):
        return self._rows("SELECT * FROM alerts WHERE state != 'RESOLVED' ORDER BY id")

    def recent_alerts(self, limit=30):
        return self._rows(
            "SELECT a.*, "
            " (SELECT action FROM human_actions h WHERE h.alert_id=a.id ORDER BY h.id DESC LIMIT 1) AS action,"
            " (SELECT operator FROM human_actions h WHERE h.alert_id=a.id ORDER BY h.id DESC LIMIT 1) AS operator,"
            " (SELECT note FROM human_actions h WHERE h.alert_id=a.id ORDER BY h.id DESC LIMIT 1) AS note "
            "FROM alerts a ORDER BY a.id DESC LIMIT ?", (limit,))

    def alert_marks(self, metric_keys, since_ts):
        marks = []
        q = ",".join("?" for _ in metric_keys)
        for r in self._rows(
                f"SELECT metric, level, opened_at, handled_at FROM alerts WHERE metric IN ({q}) "
                f"AND (opened_at >= ? OR handled_at >= ?)", tuple(metric_keys) + (since_ts, since_ts)):
            if r["opened_at"] >= since_ts:
                marks.append({"t": to_epoch_ms(r["opened_at"]), "kind": "alert", "level": r["level"]})
            if r["handled_at"] and r["handled_at"] >= since_ts:
                marks.append({"t": to_epoch_ms(r["handled_at"]), "kind": "handled"})
        return marks

    def last_alert_time(self, metric):
        r = self._row("SELECT opened_at FROM alerts WHERE metric=? ORDER BY id DESC LIMIT 1", (metric,))
        return parse_ts(r["opened_at"]) if r else None

    def kpi(self, days=7):
        since = now_str(datetime.now() - timedelta(days=days))
        today = datetime.now().strftime("%Y-%m-%d")
        r = self._row(
            "SELECT "
            " AVG(CASE WHEN acked_at IS NOT NULL THEN (julianday(acked_at)-julianday(opened_at))*86400 END) AS resp,"
            " AVG(CASE WHEN resolution='HUMAN' THEN (julianday(resolved_at)-julianday(opened_at))*86400 END) AS fix,"
            " SUM(CASE WHEN opened_at LIKE ? THEN 1 ELSE 0 END) AS today "
            "FROM alerts WHERE opened_at >= ? AND metric != 'vent'", (f"{today}%", since))
        return {
            "avg_response_s": round(r["resp"]) if r["resp"] is not None else None,
            "avg_fix_s": round(r["fix"]) if r["fix"] is not None else None,
            "alerts_today": r["today"] or 0,
        }

    # ---------- hành động của người vận hành ----------
    def insert_action(self, alert_id, action, operator, note):
        return self._exec("INSERT INTO human_actions (ts,alert_id,action,operator,note) VALUES (?,?,?,?,?)",
                          (now_str(), alert_id, action, operator, note))

    def recent_device_actions(self, limit=8):
        return self._rows("SELECT ts, action, operator FROM human_actions WHERE alert_id IS NULL "
                          "ORDER BY id DESC LIMIT ?", (limit,))

    # ---------- lệnh ----------
    def insert_command(self, cmd, args, result):
        self._exec("INSERT INTO commands (ts,cmd,args,status,retries,latency_ms,link) VALUES (?,?,?,?,?,?,?)",
                   (now_str(), cmd, args, result.get("status"), result.get("retries", 0),
                    result.get("latency_ms"), result.get("link")))
