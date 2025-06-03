#include "AP_HSM.h"
#include <AP_HAL/AP_HAL.h>
#include <cstring>
#include <AP_SerialManager/AP_SerialManager.h>
#include <stdio.h>

#include <cctype>
#include <iostream>





extern const AP_HAL::HAL& hal;

// Initialise le pointeur à null au départ
AP_HSM* AP_HSM::_singleton = nullptr;


// Constructeur privé pour empêcher l'instanciation directe
AP_HSM::AP_HSM() {
    // Initialisation de uart_hsm (optionnel)
    memset(key_bytes, 0, sizeof(key_bytes));
    uart_hsm = nullptr; // Déjà initialisé par défaut, mais explicite ici
}

// Méthode pour obtenir l'instance unique de la classe
AP_HSM& AP_HSM::get_singleton() {
    if (_singleton == nullptr) {
        _singleton = new AP_HSM();
    }
    return *_singleton;
}




// Initialisation de la communication UART
void AP_HSM::begin(AP_HAL::UARTDriver* uart_dev) {
    if (uart_dev == nullptr) {
        hal.console->printf("Erreur : UART non fourni pour HSM\n");
        return;
    }

    uart_hsm = uart_dev;
    hal.console->printf("Initialisation du HSM...\n");
    uart_hsm->begin(115200);
    uart_hsm->set_flow_control(AP_HAL::UARTDriver::FLOW_CONTROL_DISABLE);
    flush_input();

    uart_hsm->printf("off\r\n");
    hal.scheduler->delay(100);
    uart_hsm->printf("on\r\n");
    hal.scheduler->delay(100);

    hal.console->printf("Initialisation du HSM terminée\n");
}



// Envoie une commande APDU et récupère la réponse
bool AP_HSM::send_apdu(const char* apdu, char* response, size_t response_len) {
    if (uart_hsm == nullptr || apdu == nullptr || response == nullptr || response_len == 0) {
        hal.console->printf("Erreur : Paramètres invalides pour send_apdu\n");
        return false;
    }

    flush_input();
    uart_hsm->printf("%s\r\n", apdu);
    printf(">> Envoi APDU : %s\n", apdu);

    uint32_t start = AP_HAL::millis();
    size_t idx = 0;
    bool response_complete = false;

    while ((AP_HAL::millis() - start) < 1000) { // Timeout de 1s
        while (uart_hsm->available() > 0 && idx < response_len - 1) {
            char rep = uart_hsm->read();
            response[idx++] = rep;
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
        response[idx] = '\0';
        printf("<< Réponse APDU : %s\n", response);
        return true;
    } else {
        response[0] = '\0';
        printf("<< Réponse APDU : <vide>\n");
        return false;
    }
}




void AP_HSM::flush_input() {
    while (uart_hsm->available() > 0) {
        uart_hsm->read();
    }

}



// Récupère la clé de cryptage
bool AP_HSM::get_key(const char* apdu, char* key, size_t key_size) {
    if (uart_hsm == nullptr || apdu == nullptr || key == nullptr || key_size == 0) {
        hal.console->printf("Erreur : Paramètres invalides pour get_key\n");
        return false;
    }

    char response[128];
    if (!send_apdu(apdu, response, sizeof(response))) {
        printf("Erreur : Échec de la récupération de la clé\n");
        return false;
    }

    // Convertir la réponse hexadécimale en bytes et stocker dans key_bytes
    if (!hexstr_to_bytes(response, key_bytes, sizeof(key_bytes))) {
        printf("Erreur : Conversion hexadécimale échouée\n");
        return false;
    }

    // Copier la réponse brute dans le buffer fourni
    strncpy(key, response, key_size);
    key[key_size - 1] = '\0';
    return true;
}




    // Convertit une chaîne hexadécimale en bytes
bool AP_HSM::hexstr_to_bytes(const char* hexstr, uint8_t* out, size_t out_len) {
    if (hexstr == nullptr || out == nullptr || out_len == 0) {
        return false;
    }

    size_t len = strlen(hexstr);
    if (len < out_len * 2) {
        printf("Erreur : Chaîne hexadécimale trop courte\n");
        return false;
    }

    for (size_t i = 0; i < out_len; ++i) {
        char byte_str[3] = { hexstr[i * 2], hexstr[i * 2 + 1], '\0' };
        if (!isxdigit(byte_str[0]) || !isxdigit(byte_str[1])) {
            printf("Erreur : Caractère non-hexadécimal à la position %zu\n", i * 2);
            return false;
        }
        sscanf(byte_str, "%2hhx", &out[i]);
    }
    return true;
}





