"""Hồ sơ nấm mặc định, nội dung cảnh báo và danh sách việc người vận hành có thể làm."""

DEFAULT_PROFILES = [
    {"name": "Bào ngư · ủ tơ", "t_min": 24, "t_max": 28, "h_min": 70, "h_max": 80,
     "lux_min": 0, "lux_max": 50, "light_on": None, "light_off": None, "vent_remind_hours": 0},
    {"name": "Bào ngư · ra quả thể", "t_min": 22, "t_max": 28, "h_min": 85, "h_max": 95,
     "lux_min": 200, "lux_max": 500, "light_on": "06:00", "light_off": "16:00", "vent_remind_hours": 3,
     "active": 1},
    {"name": "Linh chi · ra quả thể", "t_min": 25, "t_max": 30, "h_min": 85, "h_max": 90,
     "lux_min": 500, "lux_max": 1000, "light_on": "06:00", "light_off": "18:00", "vent_remind_hours": 2},
    {"name": "Nấm rơm", "t_min": 30, "t_max": 35, "h_min": 80, "h_max": 90,
     "lux_min": 50, "lux_max": 300, "light_on": "06:00", "light_off": "18:00", "vent_remind_hours": 3},
    # Ngưỡng gần điều kiện phòng lab để quay video chủ động: hà hơi vào DHT22 -> ẩm cao,
    # che quang trở -> thiếu sáng, bật đèn chiếu sáng -> hết thiếu sáng
    {"name": "Demo · phòng lab", "t_min": 20, "t_max": 31, "h_min": 45, "h_max": 75,
     "lux_min": 80, "lux_max": 2000, "light_on": None, "light_off": None, "vent_remind_hours": 0},
]

# Nội dung cảnh báo: (thông điệp, gợi ý cho người vận hành)
ALERT_TEXT = {
    "t_low": ("Nhiệt độ thấp hơn ngưỡng", "Đóng cửa, che chắn để giữ nhiệt"),
    "t_high": ("Nhiệt độ cao hơn ngưỡng", "Mở cửa, bật quạt, phun sương mái để làm mát"),
    "h_low": ("Độ ẩm thấp hơn ngưỡng", "Phun sương, tưới ẩm nền và vách; không phun thẳng lên mũ nấm"),
    "h_high": ("Độ ẩm cao hơn ngưỡng", "Mở cửa thông gió, tạm ngừng tưới"),
    "l_low": ("Thiếu sáng trong khung giờ chiếu sáng", "Bật đèn chiếu sáng trên dashboard hoặc mở rèm"),
    "l_high": ("Ánh sáng quá mạnh", "Che bớt ánh sáng trực tiếp"),
    "sensor": ("Cảm biến DHT22 lỗi", "Kiểm tra dây và vị trí cảm biến DHT22"),
    "vent": ("Đến lịch thông gió", "Mở cửa thông gió 2–3 phút để xả khí CO2"),
}

# Việc người vận hành chọn khi bấm "Đã xử lý"
HUMAN_ACTIONS = [
    "Phun sương",
    "Tưới ẩm nền và vách",
    "Mở cửa thông gió",
    "Đóng cửa, che chắn",
    "Bật quạt",
    "Bật đèn chiếu sáng",
    "Che bớt ánh sáng",
    "Kiểm tra cảm biến",
    "Khác",
]

# Gợi ý việc nên làm theo loại cảnh báo (chọn sẵn trong form)
DEFAULT_ACTION_FOR = {
    "t_low": "Đóng cửa, che chắn", "t_high": "Mở cửa thông gió",
    "h_low": "Phun sương", "h_high": "Mở cửa thông gió",
    "l_low": "Bật đèn chiếu sáng", "l_high": "Che bớt ánh sáng",
    "sensor": "Kiểm tra cảm biến", "vent": "Mở cửa thông gió",
}
