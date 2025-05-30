#pragma once
#include <AP_HAL/AP_HAL.h>   // Assurez-vous que ce fichier est inclus



/// HSM driver main class
class AP_HSM 
{

// This class provides an interface to communicate with the HSM (Hardware Security Module) over UART
// It allows for operations such as selecting the TLS-SE, verifying a PIN, reading a key, and sending APDUs.


public:

// AP_HSM(AP_HAL::UARTDriver* uart){
//     uart_hsm = uart ;
// }

    //  /* Do not allow copies */
    // // CLASS_NO_COPY(AP_HSM);
    // static AP_HSM *get_singleton() {
    //      return _singleton;
    //  }

    AP_HAL::UARTDriver*  uart_hsm = nullptr;
    void  begin();
   // void select_tlsse();
    // bool verify_pin(const char* pin);
    // bool read_key(uint8_t* out_key, size_t len, uint16_t offset = 0x10);
    void send_apdu(const char* apdu, char* response, size_t response_len);
   // void set_uart(AP_HAL::UARTDriver* uart_dev) { uart = uart_dev; } 
    void flush_input();

    bool get_key(const char* apdu, char* key, size_t key_size);
    bool hexstr_to_bytes(const char* hexstr, uint8_t* out, size_t out_len);

protected:

//  the UART driver used for communication


private:

    static AP_HSM *_singleton;
  //  AP_HAL::UARTDriver*  uart_hsm ;
    
};




// #pragma once

// #include <AP_HAL/AP_HAL.h>

// class AP_LeMonolith {
// public:
//     AP_LeMonolith(AP_HAL::UARTDriver* uart);

//     void begin();
//     bool select_tlsse();
//     bool verify_pin(const char* pin);
//     bool read_key(uint8_t* out_key, size_t len, uint16_t offset = 0x10);
//     bool send_apdu(const char* apdu, char* response, size_t response_len);

// private:
//     AP_HAL::UARTDriver* _uart;
//     void flush_input();
// };



// #include <stdint.h>
// #include <stdbool.h>
// #include <stddef.h>
// #include <AP_HAL/AP_HAL.h>

// // Define the struct for AP_LeMonolith
// typedef struct {
//     UARTDriver* uart;
// } AP_LeMonolith;

// // Function declarations
// void AP_LeMonolith_init(AP_LeMonolith* self, UARTDriver* uart);
// void AP_LeMonolith_begin(AP_LeMonolith* self);
// bool AP_LeMonolith_select_tlsse(AP_LeMonolith* self);
// bool AP_LeMonolith_verify_pin(AP_LeMonolith* self, const char* pin);
// bool AP_LeMonolith_read_key(AP_LeMonolith* self, uint8_t* out_key, size_t len, uint16_t offset);
// bool AP_LeMonolith_send_apdu(AP_LeMonolith* self, const char* apdu, char* response, size_t response_len);
// void AP_LeMonolith_flush_input(AP_LeMonolith* self);

