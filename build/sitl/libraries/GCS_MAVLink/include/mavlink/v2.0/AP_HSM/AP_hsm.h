#pragma once

#include <AP_HAL/AP_HAL.h>

class AP_LeMonolith {
public:
    AP_LeMonolith(AP_HAL::UARTDriver* uart);

    void begin();
    bool select_tlsse();
    bool verify_pin(const char* pin);
    bool read_key(uint8_t* out_key, size_t len, uint16_t offset = 0x10);
    bool send_apdu(const char* apdu, char* response, size_t response_len);

private:
    AP_HAL::UARTDriver* _uart;
    void flush_input();
};
