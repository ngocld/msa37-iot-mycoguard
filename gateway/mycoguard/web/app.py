"""Flask app: trang dashboard và REST API."""
import csv
import io
import re
import time
from datetime import datetime, timedelta

from flask import Flask, Response, jsonify, render_template, request

from ..db import now_str
from ..profiles import HUMAN_ACTIONS

RANGES = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}
METRIC_FLAGS = {"temp": ["t_low", "t_high"], "humidity": ["h_low", "h_high"], "light": ["l_low", "l_high"]}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def create_app(ctx):
    """ctx có các thuộc tính: cfg, db, processor, links, scheduler, sim (None khi chạy thật), display."""
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    def body():
        return request.get_json(silent=True) or {}

    def bad(message, code=400):
        return jsonify({"ok": False, "error": message}), code

    def operator_name(data):
        return (str(data.get("operator") or "").strip()[:40]) or "Người vận hành"

    def command_reply(result, text=None):
        ok = bool(result.get("ok"))
        reasons = {"no_link": "Chưa kết nối được với Arduino", "no_ack": "Arduino không phản hồi",
                   "rejected": "Arduino từ chối lệnh", "timeout": "Hết thời gian chờ"}
        return jsonify({"ok": ok, "text": text, "result": result,
                        "error": None if ok else reasons.get(result.get("status"), "Gửi lệnh thất bại")})

    @app.get("/")
    def index():
        return render_template("index.html", site_name=ctx.cfg.site_name, mode=ctx.cfg.link,
                               actions=HUMAN_ACTIONS)

    @app.get("/api/state")
    def state():
        snap = ctx.processor.snapshot()
        snap["now"] = datetime.now().strftime("%H:%M:%S")
        snap["mode"] = ctx.cfg.link
        snap["link"] = ctx.links.snapshot()
        snap["kpi"] = ctx.db.kpi()
        snap["next_vent"] = ctx.scheduler.next_vent()
        snap["tm1637"] = bool(ctx.display and ctx.display.enabled)
        snap["sim"] = ctx.sim.snapshot() if ctx.sim else None
        return jsonify(snap)

    @app.get("/api/history")
    def history():
        metric = request.args.get("metric", "temp")
        rng = request.args.get("range", "1h")
        if metric not in METRIC_FLAGS or rng not in RANGES:
            return bad("Tham số không hợp lệ")
        seconds = RANGES[rng]
        points, bucket = ctx.db.history(metric, seconds)
        since = now_str(datetime.now() - timedelta(seconds=seconds))
        p = ctx.processor.profile
        band = {"temp": [p["t_min"], p["t_max"]], "humidity": [p["h_min"], p["h_max"]],
                "light": [p["lux_min"], p["lux_max"]]}[metric]
        return jsonify({
            "metric": metric, "range": rng, "bucket_s": bucket, "points": points, "band": band,
            "marks": ctx.db.alert_marks(METRIC_FLAGS[metric], since),
            "from": int((time.time() - seconds) * 1000), "to": int(time.time() * 1000),
        })

    @app.get("/api/readings")
    def readings():
        date = request.args.get("date") or None
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return bad("Ngày không hợp lệ")
        page = max(1, request.args.get("page", 1, type=int))
        size = min(100, max(5, request.args.get("size", 15, type=int)))
        rows, total = ctx.db.readings_page(date, page, size)
        return jsonify({"rows": rows, "total": total, "page": page, "size": size})

    @app.get("/api/export.csv")
    def export_csv():
        date = request.args.get("date") or None
        if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return bad("Ngày không hợp lệ")

        def generate():
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["thoi_gian", "nhiet_do_C", "do_am_pct", "anh_sang_lux", "den_pwm", "trang_thai", "kenh"])
            yield "﻿" + buf.getvalue()           # BOM để Excel đọc đúng UTF-8
            for row in ctx.db.iter_readings(date):
                buf.seek(0)
                buf.truncate()
                writer.writerow(row)
                yield buf.getvalue()

        name = f"mycoguard_{date or 'tat_ca'}.csv"
        return Response(generate(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={name}"})

    @app.get("/api/alerts")
    def alerts():
        return jsonify({"alerts": ctx.db.recent_alerts(30), "device_actions": ctx.db.recent_device_actions(8),
                        "kpi": ctx.db.kpi()})

    @app.post("/api/alerts/<int:aid>/ack")
    def ack(aid):
        try:
            alert, result = ctx.processor.ack(aid)
        except ValueError as exc:
            return bad(str(exc), 409)
        return jsonify({"ok": True, "alert": alert, "mute": result})

    @app.post("/api/alerts/<int:aid>/handle")
    def handle(aid):
        data = body()
        action = str(data.get("action") or "").strip()[:60]
        if not action:
            return bad("Hãy chọn việc đã làm")
        note = str(data.get("note") or "").strip()[:200] or None
        try:
            alert = ctx.processor.handle(aid, action, operator_name(data), note)
        except ValueError as exc:
            return bad(str(exc), 409)
        return jsonify({"ok": True, "alert": alert})

    @app.post("/api/device")
    def device():
        data = body()
        cmd = data.get("cmd")
        value = data.get("value")
        if cmd == "light":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return bad("Độ sáng phải là số từ 0 đến 100")
            if not 0 <= value <= 100:
                return bad("Độ sáng phải là số từ 0 đến 100")
        try:
            result, text = ctx.processor.device_command(cmd, value, operator_name(data))
        except ValueError as exc:
            return bad(str(exc))
        return command_reply(result, text)

    @app.get("/api/profiles")
    def profiles():
        return jsonify({"profiles": ctx.db.list_profiles()})

    @app.post("/api/profiles/<int:pid>/activate")
    def activate(pid):
        try:
            profile = ctx.processor.activate_profile(pid)
        except ValueError as exc:
            return bad(str(exc), 404)
        ctx.db.insert_action(None, f"Chuyển sang hồ sơ {profile['name']}", operator_name(body()), None)
        return jsonify({"ok": True, "profile": profile})

    @app.put("/api/profiles/<int:pid>")
    def update_profile(pid):
        data = body()
        if not ctx.db.get_profile(pid):
            return bad("Không tìm thấy hồ sơ", 404)
        try:
            clean = {
                "name": str(data.get("name") or "").strip()[:60],
                "t_min": float(data["t_min"]), "t_max": float(data["t_max"]),
                "h_min": float(data["h_min"]), "h_max": float(data["h_max"]),
                "lux_min": int(data["lux_min"]), "lux_max": int(data["lux_max"]),
                "light_on": (data.get("light_on") or None), "light_off": (data.get("light_off") or None),
                "vent_remind_hours": int(data.get("vent_remind_hours") or 0),
            }
        except (KeyError, TypeError, ValueError):
            return bad("Ngưỡng phải là số")
        if not clean["name"]:
            return bad("Hồ sơ cần có tên")
        if not (clean["t_min"] < clean["t_max"] and clean["h_min"] < clean["h_max"]
                and 0 <= clean["lux_min"] < clean["lux_max"]):
            return bad("Giá trị nhỏ nhất phải nhỏ hơn giá trị lớn nhất")
        if not (0 <= clean["h_min"] and clean["h_max"] <= 100):
            return bad("Độ ẩm phải trong khoảng 0–100%")
        if bool(clean["light_on"]) != bool(clean["light_off"]):
            return bad("Cần nhập cả giờ bật và giờ tắt chiếu sáng, hoặc bỏ trống cả hai")
        for key in ("light_on", "light_off"):
            if clean[key] and not TIME_RE.match(clean[key]):
                return bad("Giờ chiếu sáng có dạng HH:MM, ví dụ 06:00")
        if not 0 <= clean["vent_remind_hours"] <= 24:
            return bad("Nhắc thông gió từ 0 đến 24 giờ")
        return jsonify({"ok": True, "profile": ctx.processor.update_profile(pid, clean)})

    @app.post("/api/sim/action")
    def sim_action():
        if not ctx.sim:
            return bad("Chỉ dùng được ở chế độ mô phỏng", 404)
        try:
            return jsonify({"ok": True, "text": ctx.sim.action(body().get("name"))})
        except ValueError as exc:
            return bad(str(exc))

    @app.post("/api/sim/scenario")
    def sim_scenario():
        if not ctx.sim:
            return bad("Chỉ dùng được ở chế độ mô phỏng", 404)
        try:
            return jsonify({"ok": True, "text": ctx.sim.scenario(body().get("name"))})
        except ValueError as exc:
            return bad(str(exc))

    return app
