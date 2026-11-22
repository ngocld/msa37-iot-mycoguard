"""Các kênh truyền giữa Pi và Arduino: USB Serial, Bluetooth RFCOMM (HC-05), kênh mô phỏng."""
import logging
import socket
import threading
import time

log = logging.getLogger("mycoguard.link")


class Link:
    """Lớp cơ sở. on_line(link, line) được gọi mỗi khi nhận đủ một dòng."""
    kind = "base"

    def __init__(self, name):
        self.name = name
        self.on_line = None
        self.connected = False

    def start(self, on_line):
        self.on_line = on_line
        threading.Thread(target=self._run, name=f"link-{self.name}", daemon=True).start()

    def _run(self):
        raise NotImplementedError

    def write(self, text):
        raise NotImplementedError

    def describe(self):
        return self.name

    def _emit_lines(self, buf, data):
        """Ghép dữ liệu vào bộ đệm và phát từng dòng hoàn chỉnh."""
        buf += data
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode("ascii", errors="ignore").strip()
            if line and self.on_line:
                self.on_line(self, line)
        return buf[-1024:]          # chặn bộ đệm phình to khi nhận rác


class SerialLink(Link):
    kind = "usb"

    def __init__(self, name, port="auto", baud=115200):
        super().__init__(name)
        self.port = port
        self.baud = baud
        self.current_port = None
        self._ser = None
        self._wlock = threading.Lock()

    def describe(self):
        return self.current_port or (self.port if self.port != "auto" else "đang tìm cổng")

    def _resolve_port(self):
        if self.port != "auto":
            return self.port
        from serial.tools import list_ports
        best = None
        for p in list_ports.comports():
            text = f"{p.device} {p.description} {p.manufacturer or ''}".lower()
            score = 0
            if p.vid == 0x2341 or p.vid == 0x2A03 or "arduino" in text:
                score = 3
            elif p.vid in (0x1A86, 0x0403, 0x10C4) or "ch340" in text:
                score = 2
            elif "ttyacm" in text or "ttyusb" in text:
                score = 1
            if score and (best is None or score > best[0]):
                best = (score, p.device)
        return best[1] if best else None

    def _run(self):
        import serial
        warned = False
        while True:
            port = self._resolve_port()
            if not port:
                if not warned:
                    log.warning("Chưa thấy Arduino trên cổng USB nào, sẽ thử lại mỗi 3 giây")
                    warned = True
                time.sleep(3)
                continue
            try:
                with serial.Serial(port, self.baud, timeout=0.5) as ser:
                    self._ser, self.current_port, self.connected = ser, port, True
                    warned = False
                    log.info("Đã mở %s (%s, %d baud)", self.name, port, self.baud)
                    buf = b""
                    while True:
                        data = ser.read(ser.in_waiting or 1)
                        if data:
                            buf = self._emit_lines(buf, data)
            except (serial.SerialException, OSError) as exc:
                log.warning("Kênh %s lỗi: %s", self.name, exc)
            finally:
                self._ser, self.connected = None, False
            time.sleep(3)

    def write(self, text):
        ser = self._ser
        if ser is None:
            return False
        with self._wlock:
            try:
                ser.write(text.encode("ascii", errors="ignore"))
                return True
            except Exception as exc:          # noqa: BLE001 - cổng có thể rút bất cứ lúc nào
                log.warning("Gửi qua %s thất bại: %s", self.name, exc)
                return False


class BluetoothLink(Link):
    """HC-05 qua RFCOMM. Dùng socket có sẵn của Python trên Linux, không cần rfcomm bind."""
    kind = "bt"
    SILENT_RECONNECT_S = 15

    def __init__(self, name, mac, channel=1):
        super().__init__(name)
        self.mac = mac
        self.channel = channel
        self._sock = None
        self._wlock = threading.Lock()

    def describe(self):
        return self.mac or "chưa cấu hình MAC"

    def _run(self):
        if not hasattr(socket, "AF_BLUETOOTH"):
            log.error("Hệ điều hành này không hỗ trợ Bluetooth RFCOMM (chỉ chạy trên Linux/Raspberry Pi)")
            return
        if not self.mac:
            log.error("Chưa khai báo MAC của HC-05 (--bt-mac)")
            return
        while True:
            sock = None
            try:
                sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                sock.settimeout(10)
                sock.connect((self.mac, self.channel))
                sock.settimeout(1.0)
                self._sock, self.connected = sock, True
                log.info("Đã kết nối Bluetooth %s", self.mac)
                buf, last_rx = b"", time.time()
                while True:
                    try:
                        data = sock.recv(256)
                    except socket.timeout:
                        if time.time() - last_rx > self.SILENT_RECONNECT_S:
                            raise OSError("không nhận được dữ liệu, kết nối lại")
                        continue
                    if not data:
                        raise OSError("HC-05 đóng kết nối")
                    last_rx = time.time()
                    buf = self._emit_lines(buf, data)
            except OSError as exc:
                log.warning("Bluetooth %s: %s", self.mac, exc)
            finally:
                self._sock, self.connected = None, False
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
            time.sleep(5)

    def write(self, text):
        sock = self._sock
        if sock is None:
            return False
        with self._wlock:
            try:
                sock.sendall(text.encode("ascii", errors="ignore"))
                return True
            except OSError as exc:
                log.warning("Gửi Bluetooth thất bại: %s", exc)
                return False


class SimLink(Link):
    """Kênh nối với Arduino ảo của bộ mô phỏng. enabled=False để giả lập rớt kết nối."""
    kind = "sim"

    def __init__(self, name, node):
        super().__init__(name)
        self.node = node
        self.enabled = True

    def describe(self):
        return f"mô phỏng ({self.name})"

    def start(self, on_line):
        self.on_line = on_line
        self.connected = True
        self.node.attach(self)

    def deliver(self, line):
        """Arduino ảo gọi hàm này để gửi một dòng lên Pi."""
        if self.enabled and self.on_line:
            self.on_line(self, line)

    def write(self, text):
        if not self.enabled:
            return False
        self.node.receive(text, self)
        return True
