# Chạy firmware trên Wokwi

1. Vào https://wokwi.com, tạo dự án **Arduino Uno** mới.
2. Thay nội dung `diagram.json` bằng file `diagram.json` trong thư mục này.
3. Thêm file `libraries.txt` (tab Library Manager → hoặc tạo file cùng tên) với nội dung trong thư mục này.
4. Chép `mycoguard_node.ino`, `config.h`, `settings.h`, `status.h`, `protocol.h` từ `arduino/mycoguard_node/` vào dự án.
5. Trong `config.h`, đổi `#define WOKWI_SIM 0` thành `#define WOKWI_SIM 1` (module cảm biến ánh sáng của Wokwi
   nối khác mạch thật).
6. Bấm Start.

## Thử các luật

- Bấm vào DHT22, kéo độ ẩm xuống dưới 85% → LED vàng, LCD dòng 4 hiện `>Can: phun suong`.
  Kéo xuống dưới 80% và giữ hơn 60 giây → LED đỏ, còi kêu.
- Kéo nhiệt độ lên trên 28 °C → `NONG`, gợi ý `Can: lam mat`.
- Bấm vào cảm biến ánh sáng, kéo dưới 200 lux → `THIEU SANG`.
- Gõ lệnh vào Serial Monitor (chọn kết thúc dòng là Newline):

```
#1|MUTE|1
#2|LIGHT|180
#3|MSG|Xin chao
#4|TH|20,31,45,75,80,2000
#5|TEST|1
```

Mỗi lệnh được trả lời bằng `{"ack":<id>,"ok":1}`. Khung dữ liệu JSON in ra mỗi 2 giây.

HC-05 và TM1637 không có trên Wokwi; firmware vẫn chạy bình thường khi không có HC-05.
