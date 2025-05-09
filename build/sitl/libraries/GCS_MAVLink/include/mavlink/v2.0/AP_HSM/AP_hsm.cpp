#include "AP_hsm.h"
#include <cstring>

AP_LeMonolith::AP_LeMonolith(AP_HAL::UARTDriver* uart) : _uart(uart) {}

void AP_LeMonolith::begin() {
    _uart->begin(115200);
    _uart->set_flow_control(false);
    flush_input();
    _uart->printf("on\r\n");
}

bool AP_LeMonolith::select_tlsse() {
    return send_apdu("A 00A4040006010203040500", nullptr, 0); // Select TLS-SE
}

bool AP_LeMonolith::verify_pin(const char* pin) {
    char apdu[64];
    snprintf(apdu, sizeof(apdu), "A 0020000108%s", pin); // PIN = 8 digits, e.g. "00000000"
    return send_apdu(apdu, nullptr, 0);
}

bool AP_LeMonolith::read_key(uint8_t* out_key, size_t len, uint16_t offset) {
    char apdu[64];
    snprintf(apdu, sizeof(apdu), "A 00B0%02X00%02X", offset, (uint8_t)len);
    char response[128];
    if (!send_apdu(apdu, response, sizeof(response))) return false;

    // Convert hex string to bytes
    for (size_t i = 0; i < len; ++i) {
        sscanf(&response[i * 2], "%2hhx", &out_key[i]);
    }
    return true;
}

bool AP_LeMonolith::send_apdu(const char* apdu, char* response, size_t response_len) {
    flush_input();
    _uart->printf("%s\r\n", apdu);

    // Wait and read response
    uint32_t start = AP_HAL::millis();
    size_t idx = 0;
    while ((AP_HAL::millis() - start) < 1000) {
        if (_uart->available() > 0 && idx < response_len - 1) {
            char c = _uart->read();
            if (response) response[idx++] = c;
            if (c == '\n') break; // response finished
        }
    }

    if (response && idx > 0) {
        response[idx] = '\0';
        return true;
    }
    return false;
}

void AP_LeMonolith::flush_input() {
    while (_uart->available() > 0) {
        _uart->read();
    }
}
