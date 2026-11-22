// Xếp mức OK / CHÚ Ý / NGUY HIỂM cho từng thông số, có vùng trễ
#pragma once

// Thứ tự bit dùng chung với Raspberry Pi (trường "f" và "d" trong khung JSON)
enum FlagBit { F_T_LOW = 0, F_T_HIGH, F_H_LOW, F_H_HIGH, F_L_LOW, F_L_HIGH, F_SENSOR, F_COUNT };

// Nhãn ngắn cho LCD dòng 3 và gợi ý cho LCD dòng 4, đánh số theo FlagBit
const char *const FLAG_TAG[F_COUNT] = {
  "LANH", "NONG", "AM THAP", "AM CAO", "THIEU SANG", "QUA SANG", "LOI DHT22"
};
const char *const FLAG_TIP[F_COUNT] = {
  "Can: giu nhiet", "Can: lam mat", "Can: phun suong", "Can: mo thong gio",
  "Can: bat den", "Can: che bot sang", "Kiem tra DHT22"
};
// Thứ tự ưu tiên khi nhiều thông số cùng lệch
const uint8_t FLAG_PRIORITY[F_COUNT] = {
  F_SENSOR, F_T_HIGH, F_H_LOW, F_H_HIGH, F_T_LOW, F_L_LOW, F_L_HIGH
};

// Theo dõi một thông số so với dải [min, max]
struct Band {
  bool lowOut = false;
  bool highOut = false;
  unsigned long beyondSince = 0;   // thời điểm bắt đầu lệch quá biên, 0 = không
  bool danger = false;

  void reset() {
    lowOut = highOut = false;
    beyondSince = 0;
    danger = false;
  }

  void update(float v, float mn, float mx, float marginLow, float marginHigh,
              float hyst, unsigned long now) {
    // Vùng trễ: chỉ hết lệch khi đã vào trong ngưỡng thêm một khoảng hyst
    if (!lowOut && v < mn) lowOut = true;
    else if (lowOut && v >= mn + hyst) lowOut = false;
    if (!highOut && v > mx) highOut = true;
    else if (highOut && v <= mx - hyst) highOut = false;

    bool beyond = false;
    if (lowOut) beyond = (mn - v) > marginLow;
    else if (highOut) beyond = (v - mx) > marginHigh;

    if (beyond) {
      if (beyondSince == 0) beyondSince = now | 1UL;
      danger = (now - beyondSince) >= DANGER_AFTER_MS;
    } else {
      beyondSince = 0;
      danger = false;
    }
  }

  // Ghi bit lệch thấp / cao vào flags, và vào dangerFlags nếu đã NGUY HIỂM
  void apply(uint8_t lowBit, uint8_t highBit, uint8_t &flags, uint8_t &dangerFlags) const {
    if (lowOut) flags |= (1 << lowBit);
    if (highOut) flags |= (1 << highBit);
    if (danger) dangerFlags |= (1 << (lowOut ? lowBit : highBit));
  }
};

// Chọn thông số cần báo trước nhất: ưu tiên bit đã NGUY HIỂM, sau đó bit đang lệch
int8_t worstFlag(uint8_t flags, uint8_t dangerFlags) {
  for (uint8_t i = 0; i < F_COUNT; i++)
    if (dangerFlags & (1 << FLAG_PRIORITY[i])) return FLAG_PRIORITY[i];
  for (uint8_t i = 0; i < F_COUNT; i++)
    if (flags & (1 << FLAG_PRIORITY[i])) return FLAG_PRIORITY[i];
  return -1;
}
