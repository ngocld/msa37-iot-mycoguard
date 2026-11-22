"""Giao thức giữa Arduino và Raspberry Pi.

Arduino -> Pi, mỗi 2 giây một dòng JSON:
    {"seq":1532,"t":26.4,"h":81.2,"lux":312,"light":0,"st":1,"f":4,"d":0,
     "bz":0,"mu":0,"lp":1,"err":0}
Pi -> Arduino, lệnh dạng văn bản:
    #21|TH|22,28,85,95,200,500
Arduino trả lời:
    {"ack":21,"ok":1}
"""
import json
import unicodedata

# Thứ tự bit của trường "f" (đang lệch) và "d" (đã NGUY HIỂM), khớp với status.h
FLAG_KEYS = ["t_low", "t_high", "h_low", "h_high", "l_low", "l_high", "sensor"]
FLAG_BIT = {key: i for i, key in enumerate(FLAG_KEYS)}

# Thông số mà mỗi bit thuộc về
METRIC_OF = {
    "t_low": "temp", "t_high": "temp",
    "h_low": "humidity", "h_high": "humidity",
    "l_low": "light", "l_high": "light",
    "sensor": "sensor",
}


def parse_line(line):
    """Trả về ("frame", dict), ("ack", dict) hoặc None nếu không phải dòng hợp lệ."""
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if "ack" in data:
        return ("ack", data)
    if isinstance(data.get("seq"), int):
        return ("frame", data)
    return None


def build_command(cmd_id, cmd, args=""):
    return f"#{cmd_id}|{cmd}|{args}\n"


def has_flag(mask, key):
    return bool(int(mask or 0) & (1 << FLAG_BIT[key]))


def to_lcd_text(text, max_len=20):
    """Bỏ dấu tiếng Việt và ký tự lạ vì LCD HD44780 chỉ hiện ASCII."""
    text = str(text).replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = "".join(c for c in text if 32 <= ord(c) < 127 and c not in "|#")
    return text[:max_len]
