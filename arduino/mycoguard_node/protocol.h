// Gom ký tự nhận được thành từng dòng lệnh "#id|LENH|tham so"
#pragma once

struct LineBuffer {
  char buf[64];
  uint8_t len = 0;
  bool overflow = false;

  // Trả về true khi vừa nhận đủ một dòng hợp lệ (nội dung nằm trong buf)
  bool feed(char c) {
    if (c == '\r') return false;
    if (c == '\n') {
      buf[len] = '\0';
      bool ok = !overflow && len > 0;
      len = 0;
      overflow = false;
      return ok;
    }
    if (len < sizeof(buf) - 1) buf[len++] = c;
    else overflow = true;        // dòng quá dài: bỏ cả dòng
    return false;
  }
};

// Chép chuỗi chỉ giữ ký tự ASCII in được, tối đa maxLen ký tự
void copyAscii(char *dst, const char *src, uint8_t maxLen) {
  uint8_t n = 0;
  while (*src && n < maxLen) {
    char c = *src++;
    if (c >= 32 && c <= 126) dst[n++] = c;
  }
  dst[n] = '\0';
}
