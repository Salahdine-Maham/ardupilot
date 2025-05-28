#include "AP_HSM.h"
#include <AP_HAL/AP_HAL.h>
#include <cstring>
#include <AP_SerialManager/AP_SerialManager.h>
#include <stdio.h>


extern const AP_HAL::HAL& hal;

//AP_HAL::UARTDriver* uart;

// Implémentation du constructeur

// const AP_SerialManager::SerialProtocol AP_SerialManager::SerialProtocol_HSM = 
//     static_cast<AP_SerialManager::SerialProtocol>(AP_SerialManager::SerialProtocol_NumProtocols + 1);

bool AP_HSM::begin() {
      uart = hal.serial(1);
      
    if (uart == nullptr) {
        return false;
    }else{
        hal.console->printf("On commance l'initiation du HSM \n");
        uart->begin(115200);
        uart->set_flow_control(AP_HAL::UARTDriver::FLOW_CONTROL_DISABLE);
        flush_input();
        printf("we are in the HSM begin function \n");
        uart->printf("on\r\n");
        hal.console->printf("Fini initiation du HSM \n");
        return true;

    }

  
}


bool AP_HSM::send_apdu(const char* apdu, char* response, size_t response_len) {
    flush_input();
    uart->printf("%s\r\n", apdu);

    // Wait and read response
    uint32_t start = AP_HAL::millis();
    size_t idx = 0;
    while ((AP_HAL::millis() - start) < 1000) {
        if (uart->available() > 0 && idx < response_len - 1) {
            char c = uart->read();
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


bool AP_HSM::select_tlsse() {
    return send_apdu("A 00A4040006010203040500", nullptr, 0); // Select TLS-SE
}

bool AP_HSM::verify_pin(const char* pin) { 
    return send_apdu("00200001083030303030303030", nullptr, 0);
}

bool AP_HSM::read_key(uint8_t* out_key, size_t len, uint16_t offset) {

    char response[128];
    if (!send_apdu("A 00B0100020", response, sizeof(response))) return false;
    
    return true;
}


void AP_HSM::flush_input() {
    while (uart->available() > 0) {
        uart->read();
    }
}
