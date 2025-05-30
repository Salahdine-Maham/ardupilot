#include "AP_HSM.h"
#include <AP_HAL/AP_HAL.h>
#include <cstring>
#include <AP_SerialManager/AP_SerialManager.h>
#include <stdio.h>

#include <cctype>
#include <iostream>





extern const AP_HAL::HAL& hal;

//AP_HAL::UARTDriver* uart;

// Implémentation du constructeur

// const AP_SerialManager::SerialProtocol AP_SerialManager::SerialProtocol_HSM = 
//     static_cast<AP_SerialManager::SerialProtocol>(AP_SerialManager::SerialProtocol_NumProtocols + 1);





void AP_HSM::begin() {
    //  uart = hal.serial(1);
   
    // if (uart_hsm == nullptr) {
    //     return ;
    // }else{
        hal.console->printf("On commance l'initiation du HSM \n");
        uart_hsm->begin(115200);
        uart_hsm->set_flow_control(AP_HAL::UARTDriver::FLOW_CONTROL_DISABLE);
        flush_input();
        printf("we are in the HSM begin function \n");
        uart_hsm->printf("off\r\n");
        hal.scheduler->delay(100); 
        uart_hsm->printf("on\r\n");
        hal.scheduler->delay(100); 
    
        hal.console->printf("Fini initiation du HSM \n");
        

  //  }

  
}


// bool AP_HSM::send_apdu(const char* apdu, char* response, size_t response_len) {
//     flush_input();
//     uart_hsm->printf("%s\r\n", apdu);

//     // Wait and read response
//     uint32_t start = AP_HAL::millis();
//     size_t idx = 0;
//     while ((AP_HAL::millis() - start) < 1000) {
//         if (uart_hsm->available() > 0 && idx < response_len - 1) {
//             char c = uart_hsm->read();
//             if (response) response[idx++] = c;
//             if (c == '\n') break; // response finished
//         }
//     }

//     if (response && idx > 0) {
//         response[idx] = '\0';
//         return true;
//     }
//     return false;
// }


void AP_HSM::send_apdu(const char* apdu, char* response, size_t response_len) {
    // 1. Vide le buffer d'entrée avant l'envoi
    flush_input();
    
    // 2. Envoi de la commande APDU
    uart_hsm->printf("%s\r\n", apdu);
    printf(">> Envoi : %s\r\n", apdu);  // Debug
    
    // 3. Lecture de la réponse avec timeout
    uint32_t start = AP_HAL::millis();
    size_t idx = 0;
    bool response_complete = false;
    char buffer[32];


    // while ((AP_HAL::millis() - start) < 1000) {
    //     while (uart_hsm->available() > 0 && idx < sizeof(buffer) - 1) {
    //         char rep = uart_hsm->read();
    //         printf("0x%02X\n", rep);
    //         response[idx++] = rep;
    //         if (rep == '\n') {
    //             break;
    //         }
    //     }
    // }

    // buffer[idx] = '\0';  // 🔥 Important !
    // printf("Réponse propre : %s", buffer);



    while ((AP_HAL::millis() - start) < 1000) {  // Timeout de 1s
        while (uart_hsm->available() > 0 ) {
            char rep = uart_hsm->read();
            printf("0x%02X\n", rep);
            if (idx <  sizeof(buffer) ) {  // Assure qu'il y a de la place dans le buffer
                buffer[idx++] = rep;
            }
            
            // Fin de réponse détectée (peut être '\n', '\r\n' ou autre selon le protocole)
            if (rep == '\n') {
                response_complete = true;
                break;
            }
        }
        
        if (response_complete) {
            break;
        }
        
        // Petite pause pour éviter de surcharger le CPU
        hal.scheduler->delay(10);
    }
    
    // 4. Gestion de la réponse
    if (buffer && idx > 0) {
        buffer[idx] = '\0';  // Null-terminate
        printf("<< Réponse: %s", buffer);
    } else {
        printf("<< Réponse: <aucune>\n");
    }
}


// void AP_HSM::select_tlsse() {
//     send_apdu("A 00A4040006010203040500", nullptr, 0); // Select TLS-SE
// }

// bool AP_HSM::verify_pin(const char* pin) { 
//     return send_apdu("00200001083030303030303030", nullptr, 0);
// }

// bool AP_HSM::read_key(uint8_t* out_key, size_t len, uint16_t offset) {

//     char response[128];
//     if (!send_apdu("A 00B0100020", response, sizeof(response))) return false;
    
//     return true;
// }


void AP_HSM::flush_input() {
    while (uart_hsm->available() > 0) {
        uart_hsm->read();
    }

}


    bool AP_HSM::get_key(const char* apdu, char* key, size_t key_size){

        if (key == nullptr || key_size == 0) {
            printf("Erreur : buffer 'key' invalide.\n");
            return false;
        }
    
        flush_input();
        uart_hsm->printf("%s\r\n", apdu);
        printf(">> Envoi : %s\r\n", apdu);
    
        uint32_t start = AP_HAL::millis();
        size_t idx = 0;
        bool response_complete = false;
    
        while ((AP_HAL::millis() - start) < 1000) {
            while (uart_hsm->available() > 0 && idx < key_size ) {
                char rep = uart_hsm->read();
                printf("0x%02X\n", rep);
                key[idx++] = rep;
    
                // Fin de réponse
                if (rep == '\n') {
                    response_complete = true;
                    break;
                }
            }
    
            if (response_complete) {
                break;
            }
    
            hal.scheduler->delay(10);
        }
    
        if (idx > 0) {
         key[idx] = '\0';  // Terminer la chaîne
            printf("<< Réponse brute : %s", key);
    
            // // Nettoyer le \r\n si présent
            // while (idx > 0 && (key[idx - 1] == '\n' || key[idx - 1] == '\r')) {
            //     key[--idx] = '\0';
            // }
    
            return true;
        } else {
            key[0] = '\0';
            printf("<< Réponse : <vide>\n");
            return false;
         }
    
        }



bool AP_HSM::hexstr_to_bytes(const char* hexstr, uint8_t* out, size_t out_len) {
            size_t len = strlen(hexstr);
        
            // Ignore les caractères non-hexadécimaux à la fin (ex: "9000", caractères erronés...)
            size_t max_hex = out_len * 2;
            if (len < max_hex) {
                printf("Chaîne trop courte : %zu < %zu\n", len, max_hex);
                return false;
            }
        
            for (size_t i = 0; i < out_len; ++i) {
                char byte_str[3] = { hexstr[i*2], hexstr[i*2 + 1], '\0' };
                if (!isxdigit(byte_str[0]) || !isxdigit(byte_str[1])) {
                    printf("Caractère non-hex à la position %zu\n", i * 2);
                    return false;
                }
                sscanf(byte_str, "%2hhx", &out[i]);
            }
        
            return true;
        }


