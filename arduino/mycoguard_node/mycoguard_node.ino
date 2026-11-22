/*
 * MycoGuard - node Arduino Uno
 * Giám sát nhiệt độ, độ ẩm, ánh sáng nhà trồng nấm.
 *
 *  - Đọc DHT22 + quang trở mỗi 2 giây, xếp mức OK / CHÚ Ý / NGUY HIỂM
 *  - Báo tại chỗ bằng LED xanh / vàng / đỏ, buzzer và LCD2004
 *  - Gửi một dòng JSON lên Raspberry Pi qua USB Serial (và HC-05 nếu có)
 *  - Nhận lệnh "#id|LENH|tham so" từ Pi và trả {"ack":id,"ok":1}
 *  - Không có Pi vẫn tự đánh giá theo ngưỡng cuối cùng lưu trong EEPROM
 *
 * Thư viện cần cài (Library Manager):
 *  - "DHT sensor library" (Adafruit) + "Adafruit Unified Sensor"
 *  - "LiquidCrystal I2C" (Frank de Brabander)
 */
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include "config.h"
#include "settings.h"
#include "status.h"
#include "protocol.h"

#if USE_BT
#include <SoftwareSerial.h>
SoftwareSerial bt(PIN_BT_RX, PIN_BT_TX);
#endif

LiquidCrystal_I2C lcdMain(LCD_ADDR, LCD_COLS, LCD_ROWS);
LiquidCrystal_I2C lcdAlt(LCD_ADDR_ALT, LCD_COLS, LCD_ROWS);
LiquidCrystal_I2C *lcd = nullptr;     // nullptr: không tìm thấy LCD, chương trình vẫn chạy
DHT dht(PIN_DHT, DHT22);
Settings cfg;

// ---------- Số đo ----------
float tempC = NAN, humidity = NAN, lux = 0;
float prevRawT = NAN, prevRawH = NAN;
uint8_t dhtFails = 0;
bool sensorFault = false;

// ---------- Trạng thái ----------
Band bandT, bandH, bandL;
uint8_t flags = 0, dangerFlags = 0, status = 0;
uint32_t seq = 0;
bool muted = false;
bool backlightOn = true;
uint8_t growLight = 0;

// ---------- Hiển thị và kết nối ----------
char lcdMsg[LCD_COLS + 1] = "";
char lcdPrev[LCD_ROWS][LCD_COLS + 1];
unsigned long msgUntil = 0, testUntil = 0;
unsigned long lastSample = 0, lastLcd = 0, lastPiMs = 0;
bool piSeen = false;
char piLink = 'U';
LineBuffer usbBuf;
#if USE_BT
LineBuffer btBuf;
#endif

// ============================================================
//  Cảm biến
// ============================================================
void readDht() {
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  bool ok = !isnan(t) && !isnan(h);
  // So với lần đọc thô trước: nhảy quá xa trong 2 giây là nhiễu.
  // Nếu thay đổi là thật thì lần đọc kế tiếp sẽ khớp và được nhận.
  bool spike = ok && !isnan(prevRawT) &&
               (fabs(t - prevRawT) > DHT_SPIKE_T || fabs(h - prevRawH) > DHT_SPIKE_H);
  if (ok) { prevRawT = t; prevRawH = h; }

  if (ok && !spike) {
    tempC = t;
    humidity = h;
    dhtFails = 0;
    sensorFault = false;
  } else if (dhtFails < DHT_FAIL_LIMIT && ++dhtFails >= DHT_FAIL_LIMIT) {
    sensorFault = true;
  }
}

float readLux() {
  long sum = 0;
  for (uint8_t i = 0; i < 8; i++) sum += analogRead(PIN_LDR);
  float adc = sum / 8.0;
  float value;
#if WOKWI_SIM
  // Công thức của module wokwi-photoresistor-sensor (LDR ở nhánh dưới)
  float voltage = adc / 1024.0 * 5.0;
  if (voltage >= 4.99) return 0;
  float resistance = 2000.0 * voltage / (1.0 - voltage / 5.0);
  if (resistance < 1.0) return LUX_MAX_READ;
  value = pow(50.0 * 1e3 * pow(10, 0.7) / resistance, 1.0 / 0.7);
#else
  // Mạch thật: 5V -> LDR -> A0 -> 10k -> GND, sáng hơn thì adc lớn hơn
  if (adc < 1.0) return 0;
  if (adc > 1022.0) adc = 1022.0;
  float rLdr = LDR_FIXED_R * (1023.0 / adc - 1.0);
  value = 10.0 * pow(LDR_R10 / rLdr, 1.0 / LDR_GAMMA);
#endif
  if (value > LUX_MAX_READ) value = LUX_MAX_READ;
  return value;
}

// ============================================================
//  Đánh giá trạng thái
// ============================================================
void evaluate(unsigned long now) {
  flags = 0;
  dangerFlags = 0;

  if (sensorFault) {
    bandT.reset();
    bandH.reset();
    flags |= (1 << F_SENSOR);
    dangerFlags |= (1 << F_SENSOR);
  } else if (!isnan(tempC)) {
    bandT.update(tempC, cfg.tMin, cfg.tMax, MARGIN_T, MARGIN_T, HYST_T, now);
    bandH.update(humidity, cfg.hMin, cfg.hMax, MARGIN_H, MARGIN_H, HYST_H, now);
    bandT.apply(F_T_LOW, F_T_HIGH, flags, dangerFlags);
    bandH.apply(F_H_LOW, F_H_HIGH, flags, dangerFlags);
  }

  // Ánh sáng chỉ được đánh giá trong khung giờ chiếu sáng
  if (cfg.lp) {
    float mLow = cfg.luxMin * MARGIN_LUX_RATIO;
    float mHigh = cfg.luxMax * MARGIN_LUX_RATIO;
    if (mLow < MARGIN_LUX_MIN) mLow = MARGIN_LUX_MIN;
    if (mHigh < MARGIN_LUX_MIN) mHigh = MARGIN_LUX_MIN;
    bandL.update(lux, cfg.luxMin, cfg.luxMax, mLow, mHigh, HYST_LUX, now);
    bandL.apply(F_L_LOW, F_L_HIGH, flags, dangerFlags);
  } else {
    bandL.reset();
  }

  status = dangerFlags ? 2 : (flags ? 1 : 0);
  if (status < 2) muted = false;   // lần NGUY HIỂM sau sẽ kêu lại
}

// ============================================================
//  Đầu ra: LED, buzzer, đèn chiếu sáng
// ============================================================
void setBuzzer(bool on) {
#if BUZZER_PASSIVE
  static bool current = false;
  if (on && !current) tone(PIN_BUZZER, 2200);
  else if (!on && current) noTone(PIN_BUZZER);
  current = on;
#else
  digitalWrite(PIN_BUZZER, on ? HIGH : LOW);
#endif
}

bool buzzerActive() {
  return status == 2 && !muted;
}

void updateOutputs(unsigned long now) {
  if ((long)(testUntil - now) > 0) {
    // Chạy thử: 3 LED sáng lần lượt, còi kêu ngắt quãng
    uint8_t step = ((testUntil - now) / 250) % 3;
    digitalWrite(PIN_LED_GREEN, step == 2);
    digitalWrite(PIN_LED_YELLOW, step == 1);
    digitalWrite(PIN_LED_RED, step == 0);
    setBuzzer(((testUntil - now) / 250) % 2 == 0);
    return;
  }
  digitalWrite(PIN_LED_GREEN, status == 0);
  digitalWrite(PIN_LED_YELLOW, status == 1);
  digitalWrite(PIN_LED_RED, status == 2);

  // NGUY HIỂM: 3 tiếng bíp mỗi 10 giây
  bool on = false;
  if (buzzerActive()) {
    unsigned long ph = now % 10000UL;
    on = ph < 150 || (ph >= 300 && ph < 450) || (ph >= 600 && ph < 750);
  }
  setBuzzer(on);
}

// ============================================================
//  Gửi dữ liệu lên Pi
// ============================================================
void sendFrame() {
  char buf[180];
  char ts[8], hs[8];
  int n;
  seq++;
  if (sensorFault || isnan(tempC)) {
    n = snprintf(buf, sizeof(buf), "{\"seq\":%lu,\"t\":null,\"h\":null", (unsigned long)seq);
  } else {
    dtostrf(tempC, 1, 1, ts);
    dtostrf(humidity, 1, 1, hs);
    n = snprintf(buf, sizeof(buf), "{\"seq\":%lu,\"t\":%s,\"h\":%s", (unsigned long)seq, ts, hs);
  }
  snprintf(buf + n, sizeof(buf) - n,
           ",\"lux\":%u,\"light\":%u,\"st\":%u,\"f\":%u,\"d\":%u,\"bz\":%u,\"mu\":%u,\"lp\":%u,\"err\":%u}",
           (unsigned)lux, growLight, status, flags, dangerFlags,
           buzzerActive() ? 1 : 0, muted ? 1 : 0, cfg.lp, sensorFault ? 1 : 0);
  Serial.println(buf);
#if USE_BT
  bt.println(buf);
#endif
}

// ============================================================
//  Nhận lệnh từ Pi
// ============================================================
void reply(Stream &port, long id, bool ok) {
  port.print(F("{\"ack\":"));
  port.print(id);
  port.print(F(",\"ok\":"));
  port.print(ok ? 1 : 0);
  port.println('}');
}

// "TH|tMin,tMax,hMin,hMax,luxMin,luxMax"
bool applyThresholds(char *args) {
  float v[6];
  char *p = args;
  for (uint8_t i = 0; i < 6; i++) {
    char *end;
    v[i] = strtod(p, &end);
    if (end == p) return false;
    p = end;
    if (*p == ',') p++;
  }
  if (!(v[0] < v[1] && v[2] < v[3] && v[4] < v[5])) return false;
  cfg.tMin = v[0];  cfg.tMax = v[1];
  cfg.hMin = v[2];  cfg.hMax = v[3];
  cfg.luxMin = (int16_t)v[4];  cfg.luxMax = (int16_t)v[5];
  settingsSave(cfg);
  bandT.reset();  bandH.reset();  bandL.reset();
  return true;
}

void handleLine(char *line, Stream &port, char src) {
  if (line[0] != '#') return;              // bỏ qua nhiễu
  char *sep = strchr(line, '|');
  if (!sep) return;
  *sep = '\0';
  long id = atol(line + 1);
  char *cmd = sep + 1;
  char *args = strchr(cmd, '|');
  if (args) *args++ = '\0';
  else args = cmd + strlen(cmd);

  lastPiMs = millis();
  piSeen = true;
  piLink = src;

  bool ok = true;
  if (!strcmp(cmd, "TH")) {
    ok = applyThresholds(args);
  } else if (!strcmp(cmd, "LP")) {
    uint8_t lp = atoi(args) ? 1 : 0;
    if (lp != cfg.lp) { cfg.lp = lp; settingsSave(cfg); }
  } else if (!strcmp(cmd, "MUTE")) {
    muted = atoi(args) != 0;
  } else if (!strcmp(cmd, "MSG")) {
    copyAscii(lcdMsg, args, LCD_COLS);
    msgUntil = lcdMsg[0] ? millis() + MSG_HOLD_MS : millis();
  } else if (!strcmp(cmd, "BL")) {
    backlightOn = atoi(args) != 0;
    if (lcd) { if (backlightOn) lcd->backlight(); else lcd->noBacklight(); }
  } else if (!strcmp(cmd, "TEST")) {
    testUntil = millis() + 3000UL;
  } else if (!strcmp(cmd, "LIGHT")) {
    int v = atoi(args);
    growLight = (uint8_t)constrain(v, 0, 255);
    analogWrite(PIN_GROW_LIGHT, growLight);
  } else if (!strcmp(cmd, "PING")) {
    // chỉ cần ACK
  } else {
    ok = false;
  }
  reply(port, id, ok);
}

void pollPorts() {
  while (Serial.available()) {
    if (usbBuf.feed((char)Serial.read())) handleLine(usbBuf.buf, Serial, 'U');
  }
#if USE_BT
  while (bt.available()) {
    if (btBuf.feed((char)bt.read())) handleLine(btBuf.buf, bt, 'B');
  }
#endif
}

// ============================================================
//  LCD2004: chỉ ghi lại dòng nào thay đổi để không nhấp nháy
// ============================================================
void lcdLine(uint8_t row, const char *text) {
  if (!lcd) return;
  char line[LCD_COLS + 1];
  uint8_t i = 0;
  for (; i < LCD_COLS && text[i]; i++) line[i] = text[i];
  for (; i < LCD_COLS; i++) line[i] = ' ';
  line[LCD_COLS] = '\0';
  if (strcmp(line, lcdPrev[row]) != 0) {
    lcd->setCursor(0, row);
    lcd->print(line);
    strcpy(lcdPrev[row], line);
  }
}

void updateLcd(unsigned long now) {
  char l[LCD_COLS + 4];
  char a[8], b[8];

  // Dòng 1: nhiệt độ, độ ẩm
  if (sensorFault || isnan(tempC)) {
    strcpy(l, "T: --.-C   H: --.-%");
  } else {
    dtostrf(tempC, 4, 1, a);
    dtostrf(humidity, 5, 1, b);
    snprintf(l, sizeof(l), "T:%sC   H:%s%%", a, b);
  }
  lcdLine(0, l);

  // Dòng 2: ánh sáng, đèn chiếu sáng (*), kênh nối với Pi
  bool piAlive = piSeen && (now - lastPiMs) < PI_TIMEOUT_MS;
  const char *link = piAlive ? (piLink == 'B' ? "BT" : "USB") : "--";
  snprintf(l, sizeof(l), "Sang:%5u lux %c %3s", (unsigned)lux, growLight ? '*' : ' ', link);
  lcdLine(1, l);

  // Dòng 3: mức trạng thái + thông số đang lệch
  int8_t worst = worstFlag(flags, dangerFlags);
  const char *st = status == 0 ? "OK" : (status == 1 ? "CHU Y" : "NGUY HIEM");
  snprintf(l, sizeof(l), "%-9s %s", st, worst >= 0 ? FLAG_TAG[worst] : "ON DINH");
  lcdLine(2, l);

  // Dòng 4: lời nhắn từ dashboard, nếu không có thì gợi ý hành động
  if (lcdMsg[0] && (long)(msgUntil - now) > 0) {
    lcdLine(3, lcdMsg);
  } else if (worst >= 0) {
    snprintf(l, sizeof(l), ">%s", FLAG_TIP[worst]);
    lcdLine(3, l);
  } else {
    lcdLine(3, "Moi thu on dinh");
  }
}

// ============================================================
void setup() {
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_GROW_LIGHT, OUTPUT);
  analogWrite(PIN_GROW_LIGHT, 0);

  Serial.begin(USB_BAUD);
#if USE_BT
  bt.begin(BT_BAUD);
#endif
  settingsLoad(cfg);
  dht.begin();

  // Dò LCD trước khi dùng: thiếu LCD hoặc dây I2C lỗi thì vẫn chạy tiếp, không treo
  Wire.begin();
  Wire.setWireTimeout(I2C_TIMEOUT_US, true);    // cần core Arduino AVR 1.8.3 trở lên
  uint8_t lcdAddr = 0;
  if (i2cPresent(LCD_ADDR)) { lcd = &lcdMain; lcdAddr = LCD_ADDR; }
  else if (i2cPresent(LCD_ADDR_ALT)) { lcd = &lcdAlt; lcdAddr = LCD_ADDR_ALT; }
  memset(lcdPrev, 0, sizeof(lcdPrev));
  if (lcd) {
    lcd->init();
    lcd->backlight();
    lcd->setCursor(0, 0);
    lcd->print(F("MycoGuard v1.0"));
    lcd->setCursor(0, 1);
    lcd->print(F("Giam sat nha nam"));
    delay(1500);
    lcd->clear();
  }
  // Dòng báo khởi động (không có "seq" nên gateway bỏ qua); lcd = 0 nghĩa là không thấy LCD
  Serial.print(F("{\"boot\":1,\"lcd\":"));
  Serial.print(lcdAddr);
  Serial.println('}');
}

bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

void loop() {
  unsigned long now = millis();
  pollPorts();

  if (lastSample == 0 || now - lastSample >= SAMPLE_MS) {
    lastSample = now | 1UL;
    readDht();
    lux = readLux();
    evaluate(now);
    sendFrame();
  }

  updateOutputs(now);

  if (now - lastLcd >= LCD_REFRESH_MS) {
    lastLcd = now;
    updateLcd(now);
  }
}
