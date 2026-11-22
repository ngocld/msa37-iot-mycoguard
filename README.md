# MycoGuard: giám sát môi trường nhà trồng nấm

Đồ án cuối kỳ IoT Programming (IAD591). Hệ thống IoT 3 tầng theo dõi **nhiệt độ, độ ẩm, ánh sáng** cho nhà
trồng nấm bào ngư, đánh giá mức an toàn, cảnh báo và gợi ý việc cần làm. Người vận hành tự xử lý tại nhà nấm
rồi xác nhận trên dashboard; hệ thống theo dõi xem thông số có về ngưỡng hay không.

```
Arduino Uno (DHT22, LDR, LCD2004, 3 LED, buzzer, đèn chiếu sáng)
      │  JSON mỗi 2 giây  ▲ lệnh + ACK
      ▼  USB Serial (HC-05 Bluetooth khi có)
Raspberry Pi 3B+ (Python gateway, SQLite, TM1637 khi có)
      │  HTTP :5000
      ▼
Flask dashboard (điện thoại, laptop)
```

## Cấu trúc thư mục

| Đường dẫn | Nội dung |
|---|---|
| `arduino/mycoguard_node/` | Firmware Arduino: `mycoguard_node.ino`, `config.h` (chân, ngưỡng, bật HC-05), `status.h` (xếp mức OK / CHÚ Ý / NGUY HIỂM), `settings.h` (EEPROM), `protocol.h` |
| `gateway/run.py` | Điểm khởi chạy gateway |
| `gateway/mycoguard/` | `links.py` (USB, Bluetooth, mô phỏng), `link_manager.py` (bỏ trùng, chuyển kênh, ACK), `processor.py` (cảnh báo, gợi ý, Grow Score), `scheduler.py` (khung giờ sáng, nhắc thông gió), `db.py`, `display.py` (TM1637) |
| `gateway/mycoguard/sim/` | Mô hình nhà nấm + Arduino ảo |
| `gateway/mycoguard/web/` | Flask app, giao diện, biểu đồ canvas tự viết (không cần Internet) |
| `database/schema.sql` | Lược đồ SQLite |
| `database/sample_data.csv` | Dữ liệu mẫu xuất từ chế độ mô phỏng (thay bằng dữ liệu thật sau buổi lab) |
| `wokwi/` | Sơ đồ mạch để chạy firmware trên Wokwi |
| `docs/thiet-ke.html` | Bản thiết kế: kiến trúc, sơ đồ mạch, giao thức, chiến lược điểm |
| `docs/so-do-cam-day.html` | Hướng dẫn cắm dây từng lỗ trên breadboard, bảng dây, danh sách kiểm tra |

## Đấu nối

| Linh kiện | Arduino | Ghi chú |
|---|---|---|
| DHT22 | D2 | Điện trở 10kΩ kéo DATA lên 5V (module 3 chân đã có sẵn) |
| Quang trở LDR | A0 | 5V → LDR → A0 → 10kΩ → GND |
| LED xanh lá / vàng / đỏ | D5 / D6 / D7 | Mỗi LED nối tiếp 220Ω |
| Buzzer | D8 | Buzzer chủ động; buzzer thụ động thì đặt `BUZZER_PASSIVE 1` |
| LED trắng "đèn chiếu sáng" | D9 (PWM) | 220Ω, đặt sát quang trở |
| LCD2004 I2C | A4 SDA, A5 SCL | Địa chỉ 0x27, nếu không hiện thì thử 0x3F |
| Raspberry Pi | USB | Cáp USB vừa cấp nguồn vừa truyền dữ liệu |
| HC-05 *(tùy chọn)* | D10 ← TXD, D11 → RXD | D11 → 1kΩ → RXD → 2kΩ → GND để hạ áp 3.3V |
| TM1637 *(tùy chọn)* | Pi GPIO23 CLK, GPIO24 DIO | VCC 3.3V (chân 1), GND (chân 6) |

## 1. Chạy mô phỏng trên máy tính (không cần phần cứng)

```powershell
cd mycoguard
python -m venv .venv
.venv\Scripts\python -m pip install -r gateway\requirements.txt
cd gateway
..\.venv\Scripts\python run.py --link sim
```

Mở http://localhost:5000. Lần chạy đầu sẽ sinh sẵn 24 giờ lịch sử để biểu đồ có dữ liệu
(file riêng `data/mycoguard_sim.db`, không lẫn với dữ liệu thật).

Chế độ mô phỏng chạy nhanh để demo: NGUY HIỂM sau 20 giây (thật: 60 giây), theo dõi kết quả 2 phút
(thật: 15 phút), nhắc thông gió theo phút thay vì giờ. Dùng `--sim-realtime` để chạy đúng thời gian thật.

Trên dashboard có thêm panel **Nhà nấm mô phỏng**: LCD và đèn ảo, các nút "việc làm tại nhà nấm"
(phun sương, mở cửa, bật quạt...) và kịch bản (khô hanh, nắng nóng, DHT22 hỏng, mất Bluetooth...).

## 2. Nạp firmware Arduino

1. Arduino IDE → Library Manager, cài: **DHT sensor library** (Adafruit), **Adafruit Unified Sensor**,
   **LiquidCrystal I2C** (Frank de Brabander).
2. Mở `arduino/mycoguard_node/mycoguard_node.ino`, chọn board Arduino Uno, nạp.
3. Mở Serial Monitor 115200 baud: mỗi 2 giây có một dòng JSON. Gõ `#1|TEST|1` (Newline) để thử đèn và còi.
4. Dòng đầu tiên sau khi khởi động là `{"boot":1,"lcd":39}`: `lcd` là địa chỉ LCD tìm thấy (39 = 0x27, 63 = 0x3F).
   `"lcd":0` nghĩa là không thấy LCD (kiểm tra dây SDA → A4, SCL → A5, VCC, GND). `"t":null` nghĩa là DHT22 chưa trả lời.
   Firmware tự dò hai địa chỉ LCD và không treo khi thiếu LCD (cần core Arduino AVR 1.8.3 trở lên).

Muốn thử trước trên trình duyệt: xem `wokwi/README.md`.

## 3. Chạy trên Raspberry Pi

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/ngocld/msa37-iot-mycoguard.git mycoguard && cd mycoguard
python3 -m venv .venv
.venv/bin/pip install -r gateway/requirements.txt
sudo usermod -aG dialout $USER      # quyền đọc cổng USB, đăng xuất rồi đăng nhập lại
cd gateway
../.venv/bin/python run.py --link usb
```

Dashboard: `http://<IP của Pi>:5000` (xem IP bằng `hostname -I`). Cổng USB được tự tìm; chỉ định tay bằng
`--port /dev/ttyACM0` nếu cần.

### Khi có HC-05

1. Ghép đôi một lần:
   ```bash
   bluetoothctl
   power on
   scan on            # tìm dòng HC-05 và ghi lại MAC
   pair 98:D3:31:XX:XX:XX     # mã PIN mặc định 1234
   trust 98:D3:31:XX:XX:XX
   quit
   ```
2. Chạy với Bluetooth chính, USB dự phòng:
   ```bash
   ../.venv/bin/python run.py --link auto --bt-mac 98:D3:31:XX:XX:XX
   ```
   Firmware đã gửi song song lên cả hai kênh (`USE_BT 1` trong `config.h`), không cần nạp lại.

### Khi có TM1637

```bash
.venv/bin/pip install raspberrypi-tm1637
../.venv/bin/python run.py --link usb --tm1637
```

## Giao thức

Arduino → Pi, mỗi 2 giây:

```json
{"seq":1532,"t":26.4,"h":81.2,"lux":312,"light":0,"st":1,"f":4,"d":0,"bz":0,"mu":0,"lp":1,"err":0}
```

`st`: 0 OK, 1 CHÚ Ý, 2 NGUY HIỂM. `f`/`d`: bit thông số đang lệch / đã nguy hiểm theo thứ tự
T thấp, T cao, RH thấp, RH cao, sáng thấp, sáng cao, lỗi cảm biến. `bz`: còi đang kêu. `lp`: trong giờ chiếu sáng.

Pi → Arduino: `#id|LỆNH|tham số`, Arduino trả `{"ack":id,"ok":1}`. Không có ACK sau 1 giây thì gửi lại, tối đa 3 lần.

| Lệnh | Ví dụ | Ý nghĩa |
|---|---|---|
| TH | `#21\|TH\|22,28,85,95,200,500` | Ngưỡng tMin,tMax,hMin,hMax,luxMin,luxMax (lưu EEPROM) |
| LP | `#22\|LP\|1` | Đang trong khung giờ chiếu sáng |
| LIGHT | `#23\|LIGHT\|153` | Độ sáng đèn chiếu sáng 0–255 |
| MUTE | `#24\|MUTE\|1` | Tắt còi cho cảnh báo hiện tại |
| MSG | `#25\|MSG\|Kiem tra bon nuoc` | Ghi dòng 4 LCD trong 60 giây |
| BL | `#26\|BL\|0` | Tắt / bật đèn nền LCD |
| TEST | `#27\|TEST\|1` | Chạy thử đèn và còi 3 giây |
| PING | `#28\|PING` | Kiểm tra kết nối |

## Cảnh báo và quy trình xử lý

- **CHÚ Ý**: thông số ra khỏi ngưỡng của hồ sơ. **NGUY HIỂM**: lệch quá biên (2 °C, 5% RH, 30% lux) liên tục
  hơn 60 giây, hoặc DHT22 lỗi. Có vùng trễ để đèn không nhấp nháy quanh mép ngưỡng.
- Thông số lệch quá 10 giây → mở cảnh báo kèm gợi ý → người vận hành bấm **Đã nhận** (còi tắt) →
  xử lý tại nhà nấm, bấm **Đã xử lý** và chọn việc đã làm → về ngưỡng trong 15 phút thì **Đã khắc phục**,
  nếu không thì **Chưa hiệu quả**.
- Dashboard tính thời gian phản hồi và thời gian khắc phục trung bình.
- Arduino tự đánh giá theo ngưỡng lưu trong EEPROM nên vẫn báo đèn, còi khi Pi tắt.

## Hồ sơ mặc định

| Hồ sơ | Nhiệt độ | Độ ẩm | Ánh sáng | Nhắc thông gió |
|---|---|---|---|---|
| Bào ngư · ủ tơ | 24–28 °C | 70–80 % | 0–50 lux, cả ngày | Không |
| **Bào ngư · ra quả thể** (mặc định) | 22–28 °C | 85–95 % | 200–500 lux, 06:00–16:00 | 3 giờ |
| Linh chi · ra quả thể | 25–30 °C | 85–90 % | 500–1000 lux, 06:00–18:00 | 2 giờ |
| Nấm rơm | 30–35 °C | 80–90 % | 50–300 lux, 06:00–18:00 | 3 giờ |
| Demo · phòng lab | 20–31 °C | 45–75 % | 80–2000 lux, cả ngày | Không |

Hồ sơ **Demo** dùng khi quay video trong phòng lab: hà hơi vào DHT22 → ẩm cao; che quang trở → thiếu sáng;
bật đèn chiếu sáng trên dashboard → hết thiếu sáng.
