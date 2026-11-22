"""Cấu hình gateway. Giá trị mặc định có thể ghi đè bằng tham số dòng lệnh của run.py."""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # thư mục mycoguard/


@dataclass
class Config:
    # Kênh truyền: usb | bt | auto (BT chính + USB dự phòng) | sim
    link: str = "usb"
    usb_port: str = "auto"          # auto: tự tìm Arduino; hoặc /dev/ttyACM0, COM3...
    usb_baud: int = 115200
    bt_mac: str = ""                # MAC của HC-05, ví dụ 98:D3:31:F5:12:34
    bt_channel: int = 1

    db_path: str = str(ROOT / "data" / "mycoguard.db")
    http_host: str = "0.0.0.0"
    http_port: int = 5000
    site_name: str = "Nhà nấm khu A"

    # LED 4 số TM1637 nối GPIO của Pi
    tm1637: bool = False
    tm1637_clk: int = 23
    tm1637_dio: int = 24

    # Lưu trữ và cảnh báo
    store_every_s: float = 5.0      # ghi số đo mỗi 5 giây (ghi ngay khi trạng thái đổi)
    alert_debounce_s: float = 10.0  # lệch liên tục bao lâu thì mở cảnh báo / về ngưỡng bao lâu thì đóng
    verify_window_s: float = 900.0  # sau khi xử lý, chờ tối đa 15 phút để thông số về ngưỡng
    time_scale: float = 1.0         # >1 khi mô phỏng nhanh: nhắc thông gió theo phút thay vì giờ

    # Kênh truyền và lệnh
    link_timeout_s: float = 6.0     # không nhận khung quá 6 giây thì coi kênh đã mất
    link_stable_s: float = 10.0     # kênh ưu tiên phải ổn định 10 giây mới chuyển về
    ack_timeout_s: float = 1.0
    cmd_retries: int = 3
    ping_every_s: float = 5.0
    resend_config_every_s: float = 300.0

    # Mô phỏng
    sim_fast: bool = True           # NGUY HIỂM sau 20 giây, theo dõi kết quả 2 phút
    sim_backfill_hours: int = 24    # sinh sẵn lịch sử để biểu đồ 24h có dữ liệu
