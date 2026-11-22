-- MycoGuard - lược đồ SQLite
-- Thời gian lưu dạng giờ địa phương 'YYYY-MM-DD HH:MM:SS'

CREATE TABLE IF NOT EXISTS readings (
  id          INTEGER PRIMARY KEY,
  ts          TEXT NOT NULL,
  seq         INTEGER,
  temp        REAL,              -- °C, NULL khi DHT22 lỗi
  humidity    REAL,              -- %RH, NULL khi DHT22 lỗi
  lux         INTEGER,           -- lux ước lượng từ quang trở
  light       INTEGER,           -- độ sáng đèn chiếu sáng 0-255
  status      INTEGER,           -- 0 OK, 1 CHÚ Ý, 2 NGUY HIỂM
  flags       INTEGER,           -- bit thông số đang lệch
  link        TEXT               -- 'USB' | 'BT' (thêm tiền tố SIM- khi mô phỏng)
);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);

CREATE TABLE IF NOT EXISTS alerts (
  id          INTEGER PRIMARY KEY,
  opened_at   TEXT NOT NULL,
  level       INTEGER NOT NULL,  -- 1 CHÚ Ý, 2 NGUY HIỂM
  metric      TEXT NOT NULL,     -- t_low, t_high, h_low, h_high, l_low, l_high, sensor, vent
  value       REAL,
  message     TEXT,
  suggestion  TEXT,
  acked_at    TEXT,
  handled_at  TEXT,
  resolved_at TEXT,
  state       TEXT NOT NULL,     -- OPEN | ACKED | HANDLED | REOPEN | RESOLVED
  resolution  TEXT               -- HUMAN: đã có người xử lý, AUTO: tự về ngưỡng
);
CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts(state);

CREATE TABLE IF NOT EXISTS human_actions (
  id          INTEGER PRIMARY KEY,
  ts          TEXT NOT NULL,
  alert_id    INTEGER REFERENCES alerts(id),   -- NULL: thao tác thiết bị từ dashboard
  action      TEXT NOT NULL,
  operator    TEXT,
  note        TEXT
);

CREATE TABLE IF NOT EXISTS commands (
  id          INTEGER PRIMARY KEY,
  ts          TEXT NOT NULL,
  cmd         TEXT NOT NULL,
  args        TEXT,
  status      TEXT,              -- acked | rejected | no_ack | no_link
  retries     INTEGER,
  latency_ms  INTEGER,
  link        TEXT
);

CREATE TABLE IF NOT EXISTS profiles (
  id                INTEGER PRIMARY KEY,
  name              TEXT NOT NULL,
  t_min             REAL NOT NULL,
  t_max             REAL NOT NULL,
  h_min             REAL NOT NULL,
  h_max             REAL NOT NULL,
  lux_min           INTEGER NOT NULL,
  lux_max           INTEGER NOT NULL,
  light_on          TEXT,        -- 'HH:MM', NULL = luôn đánh giá ánh sáng
  light_off         TEXT,
  vent_remind_hours INTEGER DEFAULT 0,   -- 0 = không nhắc thông gió
  active            INTEGER DEFAULT 0
);
