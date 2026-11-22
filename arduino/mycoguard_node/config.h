// ============================================================
//  MycoGuard - cấu hình node Arduino Uno
// ============================================================
#pragma once

// ---------- Bật / tắt tính năng ----------
// 1: gửi dữ liệu song song qua HC-05 (SoftwareSerial D10/D11).
//    Chưa gắn HC-05 vẫn để 1 được, chỉ là không ai nhận.
#ifndef USE_BT
#define USE_BT          1
#endif
// 1: chạy trên Wokwi (module cảm biến ánh sáng của Wokwi dùng công thức khác)
#ifndef WOKWI_SIM
#define WOKWI_SIM       0
#endif
// 0: buzzer chủ động (có mạch dao động, chỉ cần cấp HIGH)
// 1: buzzer thụ động (cần tone())
#ifndef BUZZER_PASSIVE
#define BUZZER_PASSIVE  0
#endif

// ---------- Chân ----------
#define PIN_DHT          2
#define PIN_LED_GREEN    5
#define PIN_LED_YELLOW   6
#define PIN_LED_RED      7
#define PIN_BUZZER       8
#define PIN_GROW_LIGHT   9    // LED trắng "đèn chiếu sáng", PWM
#define PIN_BT_RX       10    // nối TXD của HC-05
#define PIN_BT_TX       11    // nối RXD của HC-05 qua phân áp 1k/2k
#define PIN_LDR         A0

// ---------- LCD2004 I2C ----------
#define LCD_ADDR      0x27    // địa chỉ thử trước
#define LCD_ADDR_ALT  0x3F    // không thấy 0x27 thì thử địa chỉ này
#define I2C_TIMEOUT_US 3000   // dây I2C lỗi hoặc chưa cắm LCD thì bỏ qua, không treo chương trình
#define LCD_COLS        20
#define LCD_ROWS         4

// ---------- Tốc độ truyền ----------
#define USB_BAUD    115200
#define BT_BAUD       9600

// ---------- Thời gian (ms) ----------
#define SAMPLE_MS          2000UL   // DHT22 đọc tối đa mỗi 2 giây
#define DANGER_AFTER_MS   60000UL   // lệch quá biên liên tục bao lâu thì thành NGUY HIỂM
#define PI_TIMEOUT_MS     15000UL   // không nhận lệnh từ Pi quá lâu thì coi như mất kết nối
#define MSG_HOLD_MS       60000UL   // lời nhắn từ dashboard giữ trên LCD bao lâu
#define LCD_REFRESH_MS      500UL

// ---------- Ngưỡng mặc định: bào ngư · ra quả thể ----------
#define DEF_T_MIN      22.0
#define DEF_T_MAX      28.0
#define DEF_H_MIN      85.0
#define DEF_H_MAX      95.0
#define DEF_LUX_MIN     200
#define DEF_LUX_MAX     500

// ---------- Biên NGUY HIỂM và vùng trễ ----------
#define MARGIN_T          2.0     // °C
#define MARGIN_H          5.0     // %RH
#define MARGIN_LUX_RATIO  0.30    // 30% của ngưỡng
#define MARGIN_LUX_MIN   20.0     // lux
#define HYST_T            0.5
#define HYST_H            2.0
#define HYST_LUX         20.0

// ---------- Lọc DHT22 ----------
#define DHT_FAIL_LIMIT      3     // đọc lỗi liên tiếp bao nhiêu lần thì báo lỗi cảm biến
#define DHT_SPIKE_T       5.0     // nhảy quá 5 °C trong 2 giây coi là nhiễu
#define DHT_SPIKE_H      20.0     // nhảy quá 20 %RH trong 2 giây coi là nhiễu

// ---------- Quang trở (GL5528): R = R10 * (lux/10)^-gamma ----------
// Mạch: 5V -> LDR -> A0 -> 10k -> GND
#define LDR_FIXED_R   10000.0
#define LDR_R10       10000.0     // điện trở LDR ở 10 lux, chỉnh khi hiệu chuẩn
#define LDR_GAMMA         0.7
#define LUX_MAX_READ  60000.0
