"""Khởi chạy MycoGuard gateway.

Ví dụ:
    python run.py --link sim                       # mô phỏng trên máy tính, không cần phần cứng
    python run.py --link usb                       # Raspberry Pi + Arduino qua cáp USB (tự tìm cổng)
    python run.py --link usb --port /dev/ttyACM0
    python run.py --link auto --bt-mac 98:D3:31:F5:12:34   # HC-05 chính, USB dự phòng
    python run.py --link usb --tm1637              # bật LED 4 số TM1637 trên GPIO23/24
"""
import argparse
import logging
import sys
from types import SimpleNamespace

from mycoguard.config import ROOT, Config
from mycoguard.db import Database
from mycoguard.display import Tm1637Display
from mycoguard.link_manager import LinkManager
from mycoguard.links import BluetoothLink, SerialLink
from mycoguard.processor import Processor
from mycoguard.scheduler import Scheduler
from mycoguard.web.app import create_app


def parse_args():
    p = argparse.ArgumentParser(description="MycoGuard gateway")
    p.add_argument("--link", choices=["usb", "bt", "auto", "sim"], default="usb",
                   help="usb: cáp USB; bt: chỉ HC-05; auto: HC-05 chính + USB dự phòng; sim: mô phỏng")
    p.add_argument("--port", default="auto", help="cổng USB của Arduino, mặc định tự tìm")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--bt-mac", default="", help="địa chỉ MAC của HC-05")
    p.add_argument("--db", default=None, help="đường dẫn file SQLite")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--http-port", type=int, default=5000)
    p.add_argument("--site", default=None, help="tên nhà nấm hiển thị trên dashboard")
    p.add_argument("--tm1637", action="store_true", help="bật LED 4 số TM1637 (chỉ trên Raspberry Pi)")
    p.add_argument("--sim-realtime", action="store_true",
                   help="mô phỏng theo thời gian thật: NGUY HIỂM sau 60 giây, theo dõi kết quả 15 phút")
    return p.parse_args()


def main():
    args = parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    log = logging.getLogger("mycoguard")

    cfg = Config(link=args.link, usb_port=args.port, usb_baud=args.baud, bt_mac=args.bt_mac,
                 http_host=args.host, http_port=args.http_port, tm1637=args.tm1637)
    if args.site:
        cfg.site_name = args.site
    sim = None
    if args.link == "sim":
        cfg.sim_fast = not args.sim_realtime
        cfg.db_path = args.db or str(ROOT / "data" / "mycoguard_sim.db")
        if cfg.sim_fast:
            cfg.verify_window_s = 120       # theo dõi kết quả 2 phút thay vì 15 phút
            cfg.time_scale = 60             # nhắc thông gió theo phút thay vì giờ
    elif args.db:
        cfg.db_path = args.db

    db = Database(cfg.db_path)
    log.info("Cơ sở dữ liệu: %s", cfg.db_path)

    if args.link == "sim":
        from mycoguard.sim.greenhouse import Simulator
        sim = Simulator(cfg)
        links = sim.make_links()
        preference = ["BT", "USB"]
        if db.count_readings() == 0 and cfg.sim_backfill_hours:
            n = sim.backfill(db, db.active_profile(), cfg.sim_backfill_hours)
            log.info("Đã sinh %d số đo lịch sử cho %d giờ qua", n, cfg.sim_backfill_hours)
    elif args.link == "usb":
        links, preference = [SerialLink("USB", cfg.usb_port, cfg.usb_baud)], ["USB"]
    elif args.link == "bt":
        links, preference = [BluetoothLink("BT", cfg.bt_mac, cfg.bt_channel)], ["BT"]
    else:
        links = [BluetoothLink("BT", cfg.bt_mac, cfg.bt_channel), SerialLink("USB", cfg.usb_port, cfg.usb_baud)]
        preference = ["BT", "USB"]

    display = Tm1637Display(cfg.tm1637, cfg.tm1637_clk, cfg.tm1637_dio)
    manager = LinkManager(links, preference, cfg, db)
    processor = Processor(cfg, db)
    processor.attach(manager, display)
    scheduler = Scheduler(cfg, db, manager, processor, display)
    manager.start(processor.on_frame, scheduler.request_push)
    scheduler.start()
    if sim:
        sim.start()

    ctx = SimpleNamespace(cfg=cfg, db=db, processor=processor, links=manager, scheduler=scheduler,
                          sim=sim, display=display)
    app = create_app(ctx)
    log.info("Dashboard: http://%s:%d", "localhost" if cfg.http_host == "0.0.0.0" else cfg.http_host,
             cfg.http_port)
    app.run(host=cfg.http_host, port=cfg.http_port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
