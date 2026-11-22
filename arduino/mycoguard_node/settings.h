// Ngưỡng hiện hành, lưu EEPROM để giữ khi mất điện hoặc mất kết nối với Pi
#pragma once
#include <EEPROM.h>

const uint16_t SETTINGS_MAGIC = 0xC0D2;

struct Settings {
  uint16_t magic;
  float tMin, tMax, hMin, hMax;
  int16_t luxMin, luxMax;
  uint8_t lp;            // 1: đang trong khung giờ chiếu sáng (Pi giữ đồng hồ)
};

void settingsDefaults(Settings &s) {
  s.magic = SETTINGS_MAGIC;
  s.tMin = DEF_T_MIN;  s.tMax = DEF_T_MAX;
  s.hMin = DEF_H_MIN;  s.hMax = DEF_H_MAX;
  s.luxMin = DEF_LUX_MIN;  s.luxMax = DEF_LUX_MAX;
  s.lp = 1;
}

void settingsSave(const Settings &s) {
  EEPROM.put(0, s);      // put() chỉ ghi các byte thay đổi
}

bool settingsValid(const Settings &s) {
  return s.magic == SETTINGS_MAGIC && !isnan(s.tMin) && !isnan(s.hMin) &&
         s.tMin < s.tMax && s.hMin < s.hMax && s.luxMin < s.luxMax;
}

void settingsLoad(Settings &s) {
  EEPROM.get(0, s);
  if (!settingsValid(s)) {
    settingsDefaults(s);
    settingsSave(s);
  }
}
